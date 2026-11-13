# AWS 两台悉尼机的分布式部署设计

- 日期：2026-11-13
- 状态：**设计稿，待拍板**；不含实施计划，未改任何业务代码
- 分支：`feat/aws-distributed`
- 输入：[双机负载均衡设计 v2（2026-10-28）](../archive/specs/2026-10-28-dual-server-load-balancing-design.md)、
  [双机 vs 升配决策（2026-11-04）](../../ops/dual-server-vs-upgrade-2026-11-04.md)、
  [容量与可靠性](../../ops/capacity-and-reliability.md)

---

## 0. 结论先行（五句话）

1. **这不是推翻 2026-11-04 的决策，而是走它预留的那条路。** 决策文档否掉的是「跨云双活」和「DNS 轮询」，
   同时明确写：*同 region 两台是唯一成立的负载均衡形态*；设计 v2 §9 又写：*若目标是海外用户，
   正确做法是整套迁到 AWS 悉尼、两台同 region*。本方案正是后者，且**只用于演练环境，生产仍留阿里云**。
2. **扩容的主力在 HTTP 层，不在 IM 层。** 容量归因实测：同机裸 WSGI 2626 rps、Django 只有 478 rps，
   瓶颈是「Django 每请求 2.7ms × 2 核 GIL」。所以两台 2 核的收益 **≈ 2×**，与「升配到 4 核」同量级，
   不是 10×。
3. **IM 多实例是本次唯一的 C++ 改动**，因为会话表是进程内内存表，Redis 只有在线键与限流、**没有 pub/sub**。
   本方案给它加一层「Redis 发布订阅 + owner 路由」，**不改任何 WS 帧格式** ——
   因此 App / Web 一行都不用动，跨栈契约门禁不受影响。
4. **`t3.small` 会削弱这次演练的说服力**：burstable 基线是 20% × 2 vCPU = **0.4 vCPU 持续**，
   压测几分钟就会耗光 CPU 积分然后被限速。**建议先升到 `t3.medium`（2 vCPU / 4G）再做验收压测**，
   否则测出来的是「AWS 积分余额」，不是架构容量。
5. **媒体共享是这次最容易被忽略的坑**：图片/语音都在本地盘，两个 Django 副本不共享。
   本方案用「**写媒体接口钉到入口机、读媒体由入口 nginx 直出本地盘**」绕开，不引入 NFS、不改 Django 存储层。

---

## 1. 目标与非目标

### 目标

| # | 目标 | 可验收的形式 |
|---|---|---|
| G1 | 应用层可水平扩展：Django 副本跨机，加机器就加容量 | 两副本同时在跑，摘掉任一副本入口仍可用 |
| G2 | IM 可多实例：任意客户端连任意 imserver 节点，消息都能正确投递 | 两个 WS 客户端分别连两个节点，双向收发正常 |
| G3 | 数据层单点收敛：MySQL / Redis 只有一份，由入口机承担 | 只有一台跑 MySQL/Redis |
| G4 | 容量提升可量化 | 同一压测脚本下，读写吞吐相对单机基线有可比数字 |
| G5 | 生产零影响 | 阿里云 `chat.shiliu153.cn` 全程不动 |

### 非目标（明确不做）

- ❌ 跨云双活（阿里云 ↔ AWS 共享数据库）——物理不成立，v2 §2 已论证
- ❌ DNS 轮询做负载均衡 / 600s TTL 故障切换——决策文档已否
- ❌ K8s / 服务网格 / 跨云专线——2C2G 规模，故障面大于收益
- ❌ 承接真实用户数据（本环境为演练环境，用造数用户）
- ❌ 动阿里云生产机的任何配置、`deploy/` 下既有脚本的相对行为

---

## 2. 已核实的事实（不是推测）

### 2.1 机器

| | 32.236.245.150 | 13.211.212.232 |
|---|---|---|
| 实例 ID | `i-0940cb6e04cb736d1` | `i-0eba990451c2d2e2d` |
| 类型 | t3.small | t3.small |
| 规格 | 2 vCPU / 1905 MB / 1G swap | 同左 |
| 可用区 | ap-southeast-2**b** | ap-southeast-2**a** |
| 内网 IP | 172.31.35.181/20 | 172.31.14.4/20 |
| 磁盘 | 38G（用 32%） | 28G（用 19%） |
| 现状负载 | **757 MB 已用**：`chaoxing-web.service`(uvicorn :8000)、宝塔、n8n(容器已停) | 497 MB 已用：宝塔面板（`:41631`），无业务 |
| 80 / 443 | **宝塔 nginx 占用** | **空闲** |
| 系统 | Ubuntu 24.04 / kernel 7.0.0-1014-aws | Ubuntu 24.04 / kernel 7.0.0-1017-aws |
| Docker | 29.9.2 | 29.1.3 + compose v2.40.3 |

两台**同 region、同 VPC（172.31.0.0/16 默认 VPC）、不同子网/可用区**，内网 22 端口实测可通。

### 2.2 网络与凭证现状（两个阻塞项）

| 项 | 状态 | 影响 |
|---|---|---|
| 13.211.212.232 公网 80/443 | **未放行**（实测 False） | 入口与 Let's Encrypt HTTP-01 都做不了 |
| 两台内网业务端口（8000/9100/9101/3306/6379） | **未放行**（实测仅 22 通，ICMP 也不通） | 跨机反代与 IM 跨节点投递做不了 |
| 32.236.245.150 公网 80/443 | 已开放（宝塔 nginx 在听） | 可用于对照验证 |
| `aws` CLI | 已装（v2.39.0），profile `moonaws` 存在 | 可自动化改安全组 |
| `aws` 凭证 | **`aws login` 会话已过期** | 改不了安全组，需你重新登录 |
| AWS MCP 工具 | **端点不可用**（`aws___*` 全部 `Unknown tool`） | 同上，改走 CLI |

### 2.3 现有单机拓扑（`deploy/docker-compose.yml.tmpl`）

```
nginx(80/443, 非 root, 容器内 8080/8443)
  ├─ /                      → Vue dist
  ├─ /api /admin /ops       → web:8000 (gunicorn -w 2)
  ├─ /im/ws                 → imserver:9100
  ├─ /im/api/               → imserver:9101
  ├─ /media/chat/           → auth_request → Django → 直出
  └─ /media/                → 直出
mysql:3306 + redis:6379 只在 backend(internal) 网络
web / worker / imserver 同时挂 default + backend
固定子网 + nginx 固定 IP(172.28.0.10)，TRUSTED_PROXY_IPS 只信它
```

`chatapp/config/settings.py:554`：`IM_SELF_URL = http://127.0.0.1:9101`（Django → imserver 唯一地址）。

### 2.4 imserver 的并发模型（决定了改造方式）

- `main.cpp`：`io_context` + `cfg.io_threads`（默认 **2**）个线程跑 `io.run()`；另有 `db_pool`（`db_threads=4`）。
- `RedisClient`：单条 hiredis 同步连接 + `std::mutex` 串行化；已有 `setex/get/del/incr/ping`，**无订阅能力**。
- `SessionRegistry`：`std::unordered_map<uint64_t, ClientSessions> sessions_` + mutex，**纯进程内**。
  语义：一个 uid 最多 `app` + `web` 两端；`send_to` 扇出本人所有端；`kick` 踢全部端；`kick_client` 踢一端。
- 投递调用点全部收敛在 `SessionRegistry` 的 6 个方法上（`ws_server.cpp` / `http_api.cpp`）：
  `register_session` / `unregister` / `kick` / `kick_client` / `send_to` / `send_to_other_clients`，
  外加只读的 `is_online` / `online_count` / `touch_online`。
- Redis 现有键：`im:online:{uid}`（TTL 90s）、`im:block:{uid}`（TTL 86400）、每账号每分钟发送配额计数。
- **`touch_online` 是每帧都会调用的**，`ws_server.cpp:264` 的注释明确警告「每帧都 SETEX 会把单连接 Redis
  变成全局串行点」，所以 owner 键**不能**走「每帧刷新」这条老路。

---

## 3. 目标架构

### 3.1 角色分配

按你定的「入口 + DB/Redis 都在 13.211.212.232」：

```
                    DNS: <子域> → 13.211.212.232
                              │
        ┌─────────────────────▼──────────────────────┐
        │  EDGE 节点   13.211.212.232  (ap-southeast-2a, 172.31.14.4)
        │  nginx  :80/:443           ← 唯一入口、唯一 TLS 终点
        │  MySQL 8                   ← 唯一主库(单点,接受)
        │  Redis 7                   ← 唯一实例(单点,接受)
        │  Django-A (gunicorn)       ┐ /api 按 least_conn 双副本
        │  Celery worker             ← 定时任务只此一处
        │  imserver-A :9100/:9101    ┐ IM 双节点
        │  媒体卷 chatapp_media      ← 唯一媒体落盘处(见 §5)
        └──────────────┬─────────────┘
                       │ VPC 内网(同 region 跨 AZ,~1ms)
        ┌──────────────▼─────────────┐
        │  APP 节点   32.236.245.150  (ap-southeast-2b, 172.31.35.181)
        │  Django-B (gunicorn)      │
        │  imserver-B :9100/:9101   │
        │  (与 chaoxing-web / 宝塔共存,不占用 80/443)
        └───────────────────────────┘
```

要点：
- **APP 节点不发布任何宿主机端口**，全部经 EDGE 的 nginx 走内网反代 → 不碰该机被占用的 80/443，
  也不影响 `chaoxing-web`。
- **数据层单点**（MySQL/Redis 各一份）是有意为之：跨机共享数据层才需要复制/一致性，而本环境不追求 HA。
- **Celery 单实例**：定时任务（备份、`media_cleanup`、`refresh_shuffle_keys`）只能一处跑，否则重复执行。
  放 EDGE 是因为它需要读媒体卷。

### 3.2 端口与信任关系

| 端口 | 谁在听 | 谁需要访问 | 安全组 |
|---|---|---|---|
| 80, 443 | EDGE nginx | 公网 | `0.0.0.0/0`（新增） |
| 22 | 两台 sshd | 你的 IP | 已通 |
| 8000 | Django-A/B | EDGE nginx（内网） | 仅 `172.31.0.0/16`（新增） |
| 9100, 9101 | imserver-A/B | EDGE nginx + 两台 Django（内网） | 仅 `172.31.0.0/16`（新增） |
| 3306 | MySQL | Django-A/B、imserver-A/B、Celery | 仅 `172.31.0.0/16`（新增） |
| 6379 | Redis | Django-A/B、Celery、imserver-A/B | 仅 `172.31.0.0/16`（新增） |

`TRUSTED_PROXY_IPS`（Django）与 `IM_TRUSTED_PROXIES`（imserver）都要改成**跨机后真实的代理地址**：
- EDGE 上：信任 docker 网桥里 nginx 容器的固定 IP（沿用现有做法）。
- APP 节点上：**新增信任 EDGE 的内网地址** `172.31.14.4`（否则 `X-Real-IP` 被拒，全站限流挤在一个 key 上）。

`IM_INTERNAL_ALLOW`（imserver `/internal/*` 来源网段）在 APP 节点上必须包含 EDGE 的 `172.31.14.4`，
否则 Celery/Django-A 调到 imserver-B 会 403。

### 3.3 为什么不需要 sticky / ip_hash（这是本设计的关键简化）

v2 文档曾设想 `/im/ws?node=a|b` + `map $arg_node` 显式分片。**本方案不需要**：
因为投递走「Redis owner 路由 + 发布订阅」，**任意客户端连任意节点都能被正确投递**。
连接归属由 `im:owner:*` 键在运行期自然形成，nginx 侧只需 `least_conn` + `ip_hash` 的**反面**：
**不要**用 `ip_hash`（移动端 CGNAT 会把整个运营商出口压到一台，这在 v2 §4 已记录）。

---

## 4. IM 多实例改造（唯一的 C++ 改动）

### 4.1 设计原则

**把所有投递收口到一个新抽象 `DeliveryBus`，`SessionRegistry` 退化为「本节点投递器」。**
调用点（`ws_server.cpp` / `http_api.cpp` 共 10 余处）的**语义不变**，只把 `registry_.xxx` 换成 `bus_.xxx`。
这样改造面最小，且原有单实例行为成为「永远命中本地」的特例，可用现有 61 个 imserver 测试守住。

### 4.2 新增 Redis 键与频道

| 用途 | 形态 | 生命周期 |
|---|---|---|
| 连接归属 | `im:owner:{uid}:{ct}` = `{instance_id}` | 注册时写入，注销时删；**TTL 10s 心跳续期**（见 §4.4），不随帧刷新 |
| 节点存活 | `im:node:{instance_id}` = 心跳时间戳 | TTL 30s，节点每 10s 续一次 |
| 节点列表 | `im:nodes`（SET） | 节点启动 SADD、优雅退出 SREM；读侧用 `im:node:*` 存在性校验剔除僵尸 |
| 定向投递 | 频道 `im:deliver:{instance_id}` | 发布订阅，载荷 `{uid,ct?,frame,op}` |
| 全节点广播 | 频道 `im:broadcast` | `kick` / 节点上下线，稀有事件，广播可接受 |

`instance_id` 由新增环境变量 `IM_INSTANCE_ID` 提供（缺省取 `hostname`，容器里就是容器 id），
启动时打日志 `startup{instance_id=...}`。

### 4.3 各方法的跨节点语义

| 方法 | 本地命中 | 本地未命中 |
|---|---|---|
| `send_to(uid, frame)` | 照旧扇出本人所有端，返回 `true` | 读 `im:owner:{uid}:{ct}`（两端都查）→ 有归属就 `PUBLISH im:deliver:{owner}`；有归属即返回 `true` |
| `send_to_other_clients(uid, except, frame)` | 照旧（`except` 恒为本地连接） | 同上，`except` 为空（远端节点不可能持有本连接） |
| `kick(uid, reason)` | 照旧 + `PUBLISH im:broadcast` | 直接 `PUBLISH im:broadcast` |
| `kick_client(uid, ct, reason)` | 照旧 + 定向发 owner（若 owner≠self） | 定向发 owner |
| `register_session` 的同类互顶 | 照旧踢本地旧连接 | 若 owner≠self → 定向发 `kick_client` 到 owner，再覆盖 owner 键 |
| `unregister` | 照旧；**当且仅当该 uid 已无任何本地端**才 `DEL im:owner:{uid}:*` | 不适用 |
| `is_online(uid)` | — | 读 `im:online:{uid}`（已是全局键，**无需改**） |
| `online_count()` | 本节点数 | `/metrics` 标注为**本节点**计数；另暴露 `im:online:{uid}` 的 SCAN 计数作为全局近似（低频，仅 metrics） |

### 4.4 owner 键的心跳续期（避开「每帧 SETEX」这个雷）

`ws_server.cpp:264` 的既有结论：每帧 SETEX 会把单条 Redis 连接变成全局串行点。
所以 owner 键**不做**按帧刷新，改为：每条连接持一个「上次刷新时间」的本地变量，
`touch_online` 被调用时顺带判断「距上次刷新 >5s 才 SETEX」——与既有的在线键节流策略一致。
TTL 设 10s，5s 刷新一次，留 2× 余量。节点崩溃时最多 10s 后 owner 键自然过期。

### 4.5 订阅侧实现

- 新增 `RedisSubscriber`：**独立 hiredis 连接**（`redisConnect` + `SUBSCRIBE`，与现有 `RedisClient`
  的连接分开，后者被 mutex 串行化，不能复用）。
- 一个专用线程跑 `redisGetReply` 阻塞循环，收到消息后**投递回 `io_context`**
  （`boost::asio::post`）再调用本地 `SessionRegistry`，避免在订阅线程里直接碰 `WsSession` 的 outbox。
- 断线重连：指数退避（1s→30s 上限），重连成功后重新 `SUBSCRIBE` 两个频道；期间**降级为纯本地投递**，
  **绝不阻断发送路径**（与 `im/server` 现有「Redis 故障不阻断聊天」的取向一致）。
- 优雅退出：`signal_set` 回调里先 `SREM im:nodes`、再关订阅线程。

### 4.6 明确不做

- **不改任何 WS 帧格式** → `imserver/tests/fixtures/ws/*.json` 不动，App / Web 不动，三条契约轨不受影响。
- 不做消息顺序的跨节点全局保证：同一会话的顺序仍由 `MessageService` 落库的 `seq` 决定（现有机制），
  pub/sub 只负责「把已落库的帧送到正确的节点」，**不承担排序职责**。
- 不做 Redis Cluster / Sentinel：单 Redis 单点，本环境接受。

### 4.7 验收口径（imserver 侧）

1. 现有 61 个 imserver 测试全绿（单实例行为不变）。
2. 新增双实例集成测：起两个 imserver 进程连同一 Redis/MySQL，A 的会话给 B 的会话发消息 → 双向可达。
3. 新增「跨节点互顶」测：同 uid 同 `ct` 连两个节点，后者上线 → 前者收到 `kicked{multi_device}`。
4. 新增「跨节点 kick」测：`/internal/kick` 打到节点 A，`uid` 的会话在节点 B → 仍被踢。
5. 新增「Redis 断连」测：订阅断开期间本地投递仍工作，进程不崩。

---

## 5. 媒体共享：本次最容易翻车的地方

**问题**：`MEDIA_ROOT` 在本地盘。两个 Django 副本各写各的盘 → 上传到 A 的图片，B 读不到；反之亦然。
预览缩略图、语音转码产物同样如此。

**三个候选**：

| 方案 | 做法 | 评价 |
|---|---|---|
| NFS over VPC | EDGE 导出媒体卷，APP 挂载 | 同 region 内网可行，但 2C2G 上跑 NFS server 增加故障面，且锁/超时调参成本高 |
| 对象存储 | `django-storages` + S3 | 架构上最正确，但要改 Django 存储层（跨栈）+ 产生费用 + 签名 URL 逻辑要复核 |
| **写路径钉 EDGE（推荐）** | nginx 把**所有写媒体**的 location 只转发到 Django-A；读媒体由 EDGE nginx 直出本地卷 | 零代码改动、零新依赖；代价是「上传吞吐不能横向扩展」 |

**推荐第三个**，理由：容量表里上传本来只有 **26 rps**、且瓶颈是 CPU（图片重编码），本就无法靠加副本线性提升；
而读媒体（占绝大多数流量）由 nginx 直出，天然水平扩展。钉住的 location：

```
/api/v1/im/images          （聊天图上传 + 缩略图生成）
/api/v1/im/voices          （语音上传 + ffmpeg 转码）
/api/v1/users/me/photos    （资料图）
/api/v1/posts              （POST 才落图；GET 仍走双副本）
```

同时 `media_bytes_backfill` / `media_cleanup` 这类管理命令**只能在 EDGE 跑**（必须看见真实媒体卷）——
写进运维文档，作为硬约束。

---

## 6. 部署编排

### 6.1 目录与边界（要你确认，因为涉及 `deploy/`）

仓库 `AGENTS.md` §六 明令「不改 `deploy/` 下任何脚本」。所以：

- **不修改** `deploy/oneclick.sh`、`deploy/docker-compose.yml.tmpl`、`deploy/nginx/*.tmpl` 的既有行为；
- **新增** `deploy/aws-distributed/`（全部是新文件）：`compose.edge.yml` / `compose.app.yml` /
  `nginx/*.conf` / `env/*.env.example` / `README.md` / `bootstrap-*.sh`；
- 与现有单机栈的差异点（跨机 upstream、媒体钉 EDGE、数据层内网暴露）全部只在这个新目录里表达。

> 如果你希望直接复用 `oneclick.sh` 的渲染逻辑，那就必须改它 —— 与本条约定冲突，需要你明确授权二选一。

### 6.2 镜像分发（避开「2C2G 编译 imserver」）

`deploy/README.md` 已明确：2C2G 不建议在服务器编译 imserver。做法沿用它的建议：
本机（或一台大机器）`docker build` → `docker save` → `scp` 到两台 → `docker load`。
镜像清单：`chatapp-web:local`、`chatapp-nginx:local`、`chatapp-imserver:local`。

### 6.3 内存预算（关键：2GB 很紧）

按实测已用内存倒推可用余量：EDGE 可用 ≈1407 MB、APP 可用 ≈1148 MB。

| 服务 | mem_limit | 放哪 | 说明 |
|---|---|---|---|
| nginx | 64m | EDGE | 现有模板 96m，跨机可略降 |
| MySQL 8 | 420m | EDGE | `innodb-buffer-pool-size=128M`（现模板 256M，2G 机器要降） |
| Redis 7 | 200m | EDGE | `maxmemory 128mb` |
| Django-A | 300m | EDGE | gunicorn `-w 2` |
| Django-B | 300m | APP | 同上 |
| imserver-A | 200m | EDGE | |
| imserver-B | 200m | APP | |
| Celery | 192m | EDGE | `--concurrency=1` |

- EDGE 合计 ≈ **1176 MB** + 系统 ~500 MB ≈ 1.68 G / 1.91 G（余 ~230 MB + 1G swap）
- APP 合计 ≈ **500 MB**（Django-B + imserver-B）+ 现有 757 MB ≈ 1.26 G（余 ~650 MB）

**结论：2GB 能跑，但 EDGE 没有余量，压测时必 OOM。** 压测阶段必须升配（见 §7）。
另外 EDGE 上已有宝塔面板常驻（~200 MB），若它开了数据库/计划任务会进一步挤压 —— 建议在 EDGE 上
**停掉宝塔除面板外的组件**（不动 APP 节点上别人的服务）。

### 6.4 与 APP 节点既有服务的隔离

`32.236.245.150` 上跑着 `chaoxing-web.service`（uvicorn :8000）。为避免冲突：
- Docker 容器**不发布** 8000/9100/9101 到宿主机，只在内网监听；
- 需要确认 compose 不用宿主机网络（现有模板有 `network: host` **仅用于构建期**，运行期是 bridge，可保留）；
- 部署前先 `sudo docker ps -a` 确认无同名容器；部署脚本不得 `docker system prune`（会误删别人的镜像）。

---

## 7. 容量预期与验收（含 t3 积分这个坑）

### 7.1 t3.small 的真实算力

t3.small：基线 **20% × 2 vCPU = 0.4 vCPU 持续**，积分 24/小时，突发上限 2 vCPU。
→ **持续压测几分钟就会耗尽积分并限速到 0.4 vCPU**，测出来的吞吐会远低于单机阿里云基线（478 rps）。

| 机型 | vCPU / RAM | 基线 | 两台合计持续算力 | 估月费（ap-southeast-2，仅机时） |
|---|---|---|---|---|
| t3.small（现状） | 2 / 2G | 20% | **0.8 vCPU** | ~$15 × 2 |
| **t3.medium（建议）** | 2 / 4G | 40% | **1.6 vCPU** | ~$30 × 2 |
| t3.large | 2 / 8G | 60% | 2.4 vCPU | ~$60 × 2 |

**建议**：
- 架构落地与功能验收（G1/G2/G3）用 t3.small 就够（短时突发足够）；
- **容量验收压测（G4）必须先升 t3.medium**，或临时开 `unlimited` 模式并接受积分费用；
- 否则「提升容量」这个结论不成立 —— 测到的是积分余额。

### 7.2 验收指标（沿用现有口径，便于与生产对比）

| 指标 | 单机基线（2C2G 阿里云） | 本次目标（t3.medium ×2） | 工具 |
|---|---|---|---|
| 极简读 `/app/config` @100 并发 | 476 rps | ≥ 700 rps | `perf/run.py` |
| 业务读 `/users/me` @20 并发 | 52 rps | ≥ 70 rps | 同上 |
| 写 `/discovery/swipe` 饱和 | ~40 rps | ≥ 55 rps | 同上 |
| WS 连接 / 消息 | 1000 连接 / 2000 条 0 失败 | 同口径 0 失败，**且连接分布在两个节点** | `imserver/scripts/bench_*` |
| IM 吞吐 | 215 msg/s（单实例） | 两节点合计 ≥ 300 msg/s | 同上 |
| 跨节点投递延迟 | — | p99 ≤ 50ms（内网 pub/sub 开销） | 新增脚本 |

---

## 8. 域名与证书方案（你要的建议）

**推荐：用现有域名 `shiliu153.cn` 的一个子域指向 EDGE。**

```
A 记录：  aws.shiliu153.cn  →  13.211.212.232
```

理由：
- 与生产 `chat.shiliu153.cn` **完全隔离**，演练环境挂了不影响主站，也不会被 App 的 `MIN_APP_VERSION` 逻辑扫到；
- Let's Encrypt **HTTP-01** 只需要 80 端口可达（EDGE 的 80 空闲），无需 DNS API 权限；
- 证书在 EDGE 上独立签发（沿用 `deploy/` 现有 certbot 容器玩法），不复制生产的私钥。

需要你做的两件事：
1. 在域名解析处加这条 A 记录；
2. 确认 EDGE 安全组放行 80/443（见 §2.2，当前是关的）。

若你不想用 `shiliu153.cn` 的子域，备选是**纯 IP + 自签证书**（App 侧要单独编译带 `--dart-define=API_BASE`
指向 IP 的包，且 Web 端浏览器会拦自签）；仅适合「不上浏览器的纯 API 压测」。

---

## 9. 分阶段实施（阻塞项在前）

| 阶段 | 内容 | 阻塞? | 谁做 |
|---|---|---|---|
| **P0 前置** | ① `aws login` 恢复凭证；② EDGE 安全组放行 80/443；③ 两台安全组放行内网 8000/9100/9101/3306/6379；④ 解析 `aws.shiliu153.cn` | **是，全卡在这** | 你（①②④）+ 我（③ 用 CLI，前提是①好了） |
| **P1 单机跑通** | 在 EDGE 上把现有单机栈跑起来（含建库、迁移、造数），验证基线 | 否 | 我 |
| **P2 跨机扩容** | imserver **仍单实例**；Django-B 上线；nginx 双 upstream；媒体钉 EDGE | 否 | 我 + 工单 |
| **P3 IM 多实例** | §4 的 C++ 改造 + 双实例集成测 | 否 | 工单（imserver 栈） |
| **P4 容量验收** | 升 t3.medium → 跑 §7.2 全套 → 出报告 | 否 | 我 |

**顺序理由**：P2 就能拿到「HTTP 横向扩展」这个主要收益，且验证成本低；P3 是最贵的一步（改 C++），
放在「跨机链路已被证明可用」之后，避免两头同时排障。P4 最后做，因为它要花钱升配。

---

## 10. 风险与回滚

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| EDGE 内存不足 OOM（2GB + 宝塔 + MySQL + Redis + 双副本） | **高** | 服务抖 | 按 §6.3 限额；停宝塔非面板组件；压测前必须升 t3.medium |
| t3 积分耗尽导致压测数字失真 | **高** | 结论无效 | §7.1：压测用 t3.medium 或 unlimited |
| 跨节点投递有隐蔽竞态（互顶/踢人） | 中 | 偶发收不到 / 踢不掉 | §4.7 的 5 条验收；pub/sub 只送已落库的帧，不涉排序 |
| 媒体写在 APP 节点导致 404 | 中 | 图片裂 | §5 写路径钉 EDGE；`ws` 与上传分开配 |
| 与 `chaoxing-web` 冲突 | 中 | 别人的服务挂 | 不发布宿主机端口；不 `prune`；变更前记录该服务状态 |
| 安全组开太大 | 低 | 暴露内网 | 数据层只对 `172.31.0.0/16` 放行，不对公网 |
| 演练环境数据出境 | 低 | 合规 | 只用造数用户，**不导真实用户数据进来** |

**回滚**：整套环境是「新增」的，回滚 = 两台 `docker compose down` + 删 `/opt/chatapp`。
不影响阿里云产线。**唯一不可逆项**是 APP 节点上可能改动的系统配置 —— 所以部署脚本只写 `/opt/chatapp` 下的东西，
不动系统服务。

---

## 11. 待你拍板的 3 件事

1. **§6.1 的边界**：新增 `deploy/aws-distributed/` 全新文件（推荐），还是授权修改 `deploy/oneclick.sh` 做双机模式？
2. **§7.1 的机型**：P4 压测是否升 `t3.medium`（约 +$30/月）？还是接受 t3.small 的积分限制、把结论口径改成
   「功能验证通过，容量数字受积分限制不具代表性」？
3. **§8 的域名**：确认用 `aws.shiliu153.cn`（或你指定的子域）？

拍板后我拆工单：**T1** imserver 多实例（imserver 栈）、**T2** 双机编排（deploy 栈新目录）、
**T3** 压测脚本扩展（perf）、**T4** 运维文档（docs）。
其中 T2 的**实际部署执行必须由本会话做** —— worker 没有 SSH 权限，也没被授权碰云主机。

---

## 12. P1 实测记录（2026-11-13，已完成）

### 12.1 结论

入口机 `13.211.212.232` 上的单机全栈**已跑通并验证**，全程未开公网端口（安全组仍只开 22，
访问走 SSH 隧道）。因此 §9 里「P0 安全组」这一阻塞**不阻塞 P1**，只阻塞 P2/P4。

实测通过项：nginx `/healthz`、`/api/v1/app/config`、前端首页、`/auth/sms/send`（名单内 200 /
名单外 `403 40301`）、`/auth/sms/verify` 换 JWT、`/users/me`、`/im/user_sig`、
以及 **WebSocket `/im/ws` 收到 `auth_ok`**。

细节与可复现命令见 [`deploy/aws-distributed/README.md`](../../../deploy/aws-distributed/README.md)。

### 12.2 P1 暴露的 4 个模板缺陷（都要在 T2 正式修）

| # | 缺陷 | 为何生产没暴露 | 影响 |
|---|---|---|---|
| 1 | `backend`(internal) 网络没有 ipam，被 Docker 分到 `172.18.0.0/16`；`MYSQL_ROOT_HOST` 由 `DOCKER_SUBNET` 推导成 `172.28.0.%` | 生产若 backend 也落在 172.18 会同样失败，属**未触发**而非不存在 | 首次部署 `db-init` 必失败 |
| 2 | `cap_drop:[ALL]` 让容器内 root 失去 `CAP_DAC_OVERRIDE`，部署目录若在 750 的 home 下则无法遍历 | 生产部署目录是 `/opt`（755） | 换部署目录即炸，坑很隐蔽 |
| 3 | redis 官方镜像用 `setpriv` 降权，`cap_drop:[ALL]` 抹掉 `CAP_SETUID` | 与镜像 tag `redis:7-alpine` 浮动有关（7.4.12 行为） | redis 无限重启 |
| 4 | imserver 运行镜像基于 `ubuntu:24.04`，无 `curl`，但 healthcheck 用 `curl` | 生产 `oneclick.sh` 的启动时序没暴露 | 容器永远 unhealthy，`depends_on` 卡死 nginx |

**建议单开一单**修第 4 条（RUN apt-get install curl，或镜像内建 `--healthz`），
不要在部署侧长期用 override 绕过；第 1、3 条也建议进 `deploy/` 模板修正（需你授权改 `deploy/`）。

### 12.3 另一处文档与实现不一致

`chatapp/accounts/checks.py:40-45`：`accounts.E001` 只读 `SMS_PHONE_WHITELIST`，
**不读 `SMS_ALLOWLIST_STRICT`**，但它的 hint 把「设 `SMS_ALLOWLIST_STRICT=0`」当作第三条出路。
照 hint 做**仍然红**。建议一并修 hint（或让 check 真的认这个开关）。

### 12.4 环境妥协（已记录，不长期保留）

- `ALLOWED_HOSTS` 追加了 `nginx` / `imserver`：容器间互调时 `Host` 是服务名，否则 Django 400。
- `SMS_PHONE_WHITELIST` 配了 5 个测试号码作为准入种子（`accounts.E001` 的有效解）。
- 手工补跑了 `imserver --migrate`（`oneclick.sh:744` 有这步，render-only + 手工 up 会漏）。
- 入口机额外加了 2G swap（`/swapfile2`），否则 imserver 编译会 OOM。

## 13. 实施现状（2026-11-13 收尾）

> 本文 §1–§12 是**设计与决策记录**，写于动手之前。实际落地与本文有几处偏差，
> 以本节和 [`deploy/aws-distributed/p2-verification.md`](../../../deploy/aws-distributed/p2-verification.md) 为准。

| 设计稿说 | 实际做的 | 原因 |
|---|---|---|
| 安全组放行内网 8000/9100/9101/3306/6379 | **全部走 SSH 隧道**（两台 22 端口本来就通） | `aws login` 会话过期，安全组改不了；隧道让 P2/P3 得以先行验证 |
| 入口机跑 nginx + MySQL + Redis + Django + Celery + imserver | 一致 | — |
| 应用机跑 Django + imserver | 一致（web 绑 `127.0.0.1:18080`） | 该机 `chaoxing-web` 占着 8000 |
| 媒体写路径钉入口机 | 一致（nginx 三个上传接口钉死 `web:8000`） | 媒体卷只在入口机 |
| t3.medium 升配 | **未做** | 需付费决策；因此所有容量数字是 t3.small 口径，且是**保守下界** |

### 已交付

- **imserver 多实例**（#288）：`RedisSubscriber` + `DeliveryBus` + `SessionRegistry::RemoteHooks`，
  **未改任何 WS 帧**（App/Web 零改动）。跨节点投递 `verdict=FIXED`，同机双容器与**两台真机**都验过。
- **双机编排**：`compose.app.yml` / `nginx/edge.conf` / `bin/topology.sh`（verify/apply/teardown）。
- **容量数字**（同口径，均为 30 秒）：

  | 指标 | 单机 | 双机 | 结论 |
  |---|---|---|---|
  | HTTP 读 @100 并发 | 801 rps | **1 215 rps** | +52% |
  | HTTP 读 @400 并发 | 768 rps | **1 229 rps** | +60% |
  | HTTP 写（滑卡）@50 并发 | 74.9 rps | 未测 | 隧道延迟会失真 |
  | IM 4000 条突发 p99 | 1 872 ms | 1 707 ms | −9%，**被数据层单点卡住** |

### 关键结论（与 §0 的预期一致，但更精确）

**HTTP 层加机器有效（+52~60%），IM 层加机器几乎无效（−9%）** —— 因为 IM 的消息落库与
Redis 都集中在入口机，加 imserver 节点只是多了两个消费者去抢同一个 2 核数据库。
真要提 IM 吞吐，顺序是「数据层先从入口机拆出去 → 内网直连 → 再谈加 imserver 节点」。

### 仍未闭环

| 项 | 卡在 |
|---|---|
| 安全组放行 → 把隧道换成内网直连并重测 | **`aws login` 会话过期**（唯一硬阻塞） |
| 写路径双副本对照 | 同上（隧道延迟会严重失真） |
| t3.medium 升配 | 需付费决策（设计稿 §7.1） |
| 域名 / 证书 | 设计稿 §8 已给方案，需你加 A 记录 |

> 本节之前还有一张「P1 当时仍未解决」的表，内容已被上面 §13 的下两行完全覆盖
> （安全组 / 内网端口 → 同一件事；t3 积分 → t3.medium 升配决策），故删除避免两处口径打架。

