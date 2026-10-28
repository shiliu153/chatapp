# 双机负载均衡架构改造方案（设计稿）

- 日期：2026-10-28
- 状态：待评审（**未写任何代码，等你确认后再开工**）
- 前置约束（你已选定）：目标是**容量 + 高可用**；**不买云 RDS / 云 Redis / OSS**，用其中一台兼做数据节点；**自建 IM 也要双活**。
- 关联文档：[README 部署](../../../README.md#部署)、[自建 IM 运维手册](../ops/imserver.md)、[证书与续期](../ops/certificates.md)

---

## 0. 一句话结论

加一台同规格机器，做成 **A = 入口 + 数据节点，B = 应用节点 + 热备**：Django / Web 天生无状态，直接分流；媒体文件用 NFS 共享；自建 IM 用「**按 uid 亲和 + 跨节点投递**」实现双活。

**必须提前接受的代价**：数据层（MySQL / Redis / 媒体）都在 A 上，所以 **B 挂了用户完全无感，A 挂了需要 5–15 分钟人工接管**。想要「A 挂了也自动无感」，得加第三台或买云服务（见 §3 方案 C），不是两台能解决的。

---

## 1. 现状盘点：哪些能随便复制，哪些不能

先把「状态」找出来。这一步决定方案形状——凡是把状态放在本机的组件，都不能简单再起一份。

| 组件 | 状态存在哪 | 能否多实例 | 代码依据 |
|---|---|---|---|
| Django API | JWT + 数据库 `session_version` | ✅ 天然无状态 | `chatapp/accounts/authentication.py:38` |
| 短信验证码 / 限流计数 / 缓存 | Redis DB0 | ✅ 共享即可 | `chatapp/config/settings.py:150` |
| Celery 任务队列 | Redis DB1 | ✅ 多 worker 竞争消费 | `chatapp/config/settings.py:141` |
| 用户与业务数据 | 本机 MySQL | ❌ 必须共享 | `chatapp/config/settings.py:112` |
| 照片 / 聊天图 / 语音 | 本机磁盘 `MEDIA_ROOT` | ❌ 必须共享 | `chatapp/config/settings.py:404` |
| Web 静态产物 `dist` | 本机目录 | ✅ 各部署一份 | `README.md:449` |
| **imserver 会话表** | **进程内 `unordered_map`** | ❌ **跨节点投递缺失** | `imserver/src/service/session_registry.h:26` |
| imserver 在线态 | Redis DB2 | ✅ 共享 | `imserver/src/service/session_registry.cpp:94` |
| imserver 内部 API | 单一 URL | ❌ 必须 fan-out | `chatapp/im/self_client.py:43` |
| 定时任务（清理/备份/探针/续证） | 宝塔计划任务 | ❌ 只能一处执行 | `docs/ops/imserver.md` §12.4 |

**结论**：Django 侧几乎白送；真正的两块硬骨头是**媒体文件**和**imserver 的进程内会话表**。

---

## 2. 目标与非目标

**目标**

1. 应用层容量约 2×（当前 2C2G 实测约 300–500 同时在线，见 `README.md` 容量表）。
2. B 故障：用户无感，请求自动落到 A。
3. A 故障：按手册 5–15 分钟内接管，数据不丢（从库 + 备份）。
4. 全过程可回滚到今天的单机形态。

**非目标（明确不做）**

- ❌ 自动故障转移（无 VIP / 无健康检查 LB，两台做不了自动选主）。
- ❌ MySQL 读写分离（Django 多库路由改造面太大，收益小）。
- ❌ 跨机房 / 异地多活。
- ❌ 把腾讯云 IM 与自建 IM 混部到不同机器（灰度开关必须全站一致）。

---

## 3. 三种方案对比

| | 方案 A：双机（A 兼数据） | 方案 B：双机 + 一台最小 ECS 做入口 | 方案 C：三节点 / 云服务 |
|---|---|---|---|
| 结构 | A：入口+数据+应用；B：应用+热备 | 入口独立；A：数据+应用；B：应用 | 3 台：入口 / 数据 / 应用，或云 RDS+Redis+OSS |
| 新增成本 | 1 台 2C2G | 1 台 2C2G + 1 台 1C1G（约 ¥30–60/月） | 3 台或云服务（最高） |
| B 挂 | 无感 | 无感 | 无感 |
| A 挂 | 5–15 分钟人工接管 | 5–15 分钟人工接管 | 自动，秒级 |
| 改造量 | 中（IM 双活为主） | 中 | 大 |
| 运维复杂度 | 低 | 中 | 高 |

**推荐方案 A**，理由：完全符合你「不加云服务」的约束，改造集中在 IM 一处，且日后可以平滑升级到 B（入口独立）或 C（数据层外置），不需要推倒重来。

> 说明：阿里云「轻量应用服务器」是否可直接挂到 CLB/ALB 做后端，官方文档口径不一致，**不要在方案里依赖它**。本方案入口就是 A 机 nginx；需要入口冗余时走方案 B。

---

## 4. 推荐架构

### 4.1 拓扑

```
                    DNS: chat.shiliu153.cn → A 公网 IP（TTL 60）
                                    │
                    ┌───────────────▼────────────────┐
                    │ A 机  10.0.0.1                 │
                    │ nginx 443/80（入口）            │
                    │  ├─ /             → 本地 dist   │
                    │  ├─ /api/v1/      → upstream{A,B}│
                    │  ├─ /media/       → 本地(NFS)    │
                    │  ├─ /im/ws?node=a → 127.0.0.1:9100│
                    │  └─ /im/ws?node=b → 10.0.0.2:9100│
                    │ gunicorn 127.0.0.1:8000         │
                    │ celery worker                   │
                    │ imserver 127.0.0.1:9100/9101    │
                    │ MySQL 主 + Redis 主             │
                    │ NFS server（媒体目录）           │
                    │ 定时任务（清理/备份/探针/续证）   │
                    └───────────────┬────────────────┘
                          内网互通（同地域）
                    ┌───────────────▼────────────────┐
                    │ B 机  10.0.0.2                 │
                    │ nginx 443（备用入口）+ 内网转发  │
                    │  ├─ 10.0.0.2:9100 → 127.0.0.1:9100│
                    │  └─ 10.0.0.2:9101 → 127.0.0.1:9101│
                    │ gunicorn 127.0.0.1:8000         │
                    │ celery worker                   │
                    │ imserver 127.0.0.1:9100/9101    │
                    │ MySQL 从（只读）+ Redis 从       │
                    │ NFS client（挂同一路径）         │
                    └────────────────────────────────┘
```

要点：**两台都跑完整的「nginx + gunicorn + celery + imserver」**，B 与 A 的唯一区别是「数据在本机还是在内网另一台」。这样 B 随时可以顶成入口（改 DNS 即可），不需要临时装环境。

### 4.2 请求路径

| 路径 | 走哪 | 说明 |
|---|---|---|
| `/`、静态资源 | A nginx 本地直出 | 带哈希的 js/css 长缓存，`index.html` 不缓存 |
| `/api/v1/*` | `upstream` A:8000 / B:8000，`least_conn` + keepalive | 无粘性需求（JWT 无状态） |
| `/media/*` | A nginx 本地（NFS 挂载点）直出 | 签名 URL 校验仍是 `auth_request` → Django |
| `/admin/`、`/ops/` | 同 `/api/v1/`（可只指向 A） | 后台是低频操作，建议**固定走 A**，少一类变量 |
| `/im/ws?node=a\|b` | `map` 到对应节点 | 见 §6.2 |
| `/im/api/*` | `map` 到对应节点（或直接给 A） | 会话/搜索只读共享库，节点无关 |

`/im/ws` 的 nginx 片段（**关键**：用 `$arg_node` 而不是 `ip_hash`——移动端大量用户在 CGNAT 后面，IP 粘性会把一整个运营商出口压到同一台）：

```nginx
map $arg_node $im_ws_backend {
    default 127.0.0.1:9100;
    a       127.0.0.1:9100;
    b       10.0.0.2:9100;
}

location /im/ws {
    proxy_pass http://$im_ws_backend;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
```

B 机内部转发（**不改 imserver 的 L9 回环限制**，仍只监听 127.0.0.1）：

```nginx
server {
    listen 10.0.0.2:9100;
    allow 10.0.0.1; deny all;
    location / { proxy_pass http://127.0.0.1:9100;
                 proxy_http_version 1.1;
                 proxy_set_header Upgrade $http_upgrade;
                 proxy_set_header Connection "upgrade";
                 proxy_set_header X-Real-IP $proxy_add_x_forwarded_for; }
}
server {
    listen 10.0.0.2:9101;
    allow 10.0.0.1; deny all;
    location / { proxy_pass http://127.0.0.1:9101; }
}
```

---

## 5. 数据层（都在 A）

### 5.1 MySQL：A 主、B 从（异步）

A `my.cnf`：

```ini
bind-address = 10.0.0.1
server-id = 1
log_bin = mysql-bin
binlog_format = ROW
gtid_mode = ON
enforce_gtid_consistency = ON
sync_binlog = 1
```

B `my.cnf`：`server-id = 2`、`read_only = ON`、`super_read_only = ON`，然后 `CHANGE REPLICATION SOURCE TO ... SOURCE_HOST='10.0.0.1'` + `START REPLICA`。

- 应用两台都**只连主库**（`DB_HOST=10.0.0.1`），从库纯粹是「A 挂了以后能提升」的保险。
- 防火墙：3306 只对 `10.0.0.2` 开放，公网一律不开。
- `CONN_MAX_AGE=60` + `CONN_HEALTH_CHECKS=True`（`settings.py:123`）已能扛住主库短暂抖动；切换主库后建议直接重启 web/worker，别指望连接池自愈。

### 5.2 Redis：A 主、B 从

A：`bind 127.0.0.1 10.0.0.1`、`requirepass`、`appendonly yes`。
B：`replicaof 10.0.0.1 6379`、`replica-read-only yes`。

- 两台应用都连 A（`REDIS_URL` / `BROKER_URL` 指向 10.0.0.1）。
- 提升命令：B 上 `REPLICAOF NO ONE`，再把 B 的 `.env` 改成 `127.0.0.1` 并重启 web + worker。
- ⚠️ 异步复制会丢最后几秒写入：可能丢一条验证码、几个限流计数、几条排队任务。**这是可接受的**（验证码重发即可），但要写进故障手册。

### 5.3 媒体：NFS 从 A 导出，B 挂载到**完全相同的路径**

```conf
# A: /etc/exports
/www/wwwroot/chatapp/chatapp/media 10.0.0.2(rw,sync,no_subtree_check,all_squash,anonuid=1001,anongid=1001)
```

```fstab
# B: /etc/fstab
10.0.0.1:/www/wwwroot/chatapp/chatapp/media /www/wwwroot/chatapp/chatapp/media nfs4 defaults,hard,_netdev,noatime 0 0
```

- `anonuid/anongid` 用 A 上 `id www` 的实际值；**路径必须与 A 一致**，否则 `MEDIA_ROOT` 指向不同目录，上传到 B 的图在 A 上 404。
- 为什么用 NFS 而不是 rsync：rsync 有窗口期（B 上传的图 A 上没有，反向亦然），表现为「随机一半图片 404」，很难查。
- 代价：图片读写多一次网络往返（内网，毫秒级），可接受。

### 5.4 备份

- A 上 `mysqldump --single-transaction` 每日 03:00 + binlog 保留 7 天，产物**同步到 B 一份**（A 挂了还能从 B 恢复）。
- 媒体目录每周 `rsync` 到 B 的本地盘（不是 NFS 挂载点）做冷备。

---

## 6. 自建 IM 双活（本方案唯一需要改代码的地方）

### 6.1 为什么不能简单起两个 imserver

`SessionRegistry` 的会话表是**进程内** `unordered_map<uint64_t, weak_ptr<WsSession>>`（`session_registry.h:26`）。A 上的用户给 B 上的用户发消息时：

- 消息**会**正确落库（共享 MySQL，`uk_conv_seq` / `uk_from_client` 保证顺序与幂等）；
- 但 `send_to()` 在本地找不到会话 → 直接返回 false → **对方收不到实时推送**，只能等下次重连补拉。

表现就是「消息发了没反应，杀进程重进才看到」——这是最容易被误判成「消息丢了」的故障。

### 6.2 亲和：`ws_url` 由服务端下发（**不用改客户端**）

`/im/user_sig` 返回的 `ws_url` 来自 `settings.IM_SELF_WS_URL`（`chatapp/im/views.py:91`），客户端只是照着连。所以只要 Django 按 uid 分配节点即可：

```python
# 目标形态（示意，不是最终代码）
WS_URLS = os.getenv("IM_SELF_WS_URLS", "").split(",")   # ["wss://chat.shiliu153.cn/im/ws?node=a", "...?node=b"]
ws_url = WS_URLS[user.id % len(WS_URLS)]
```

同一个用户永远落到同一台 → 单设备登录、本地会话表、踢人都还在「一个节点内」的熟悉语义里。

### 6.3 跨节点投递：Redis 记 owner + 内部 HTTP 转发

不改消息落库路径，只补「最后一公里」：

1. 连接建立时写 `im:owner:{uid} = {IM_NODE_ID}`（TTL 与在线态一致，掉线即过期）。
2. `SessionRegistry::send_to()` 本地找不到会话时：读 `im:owner:{uid}` →
   - 是自己 → 说明对方已掉线，直接返回（走离线补拉）；
   - 是另一台 → `POST http://{peer}:9101/internal/deliver`，带现有 HMAC 签名，body `{uid, frame}`；
   - 键不存在 → 离线，返回。
3. 目标节点新增 `/internal/deliver`：**只做本地推送，不落库**（避免重复消息）。

选 HTTP 转发而不是 Redis pub/sub 的原因：`RedisClient`（`redis_client.h`）目前只有 `get/setex/del/incr/ping`，加 pub/sub 要新写订阅线程和断线重订阅；而内部 HTTP + HMAC 的骨架（`http_api.cpp` 的 `/internal/*`）已经现成，改造面小一半，排障也直观（能直接 curl）。

### 6.4 内部 API 必须 fan-out

Django 现在只有一个 `IM_SELF_HTTP_URL`（`settings.py:355`），既当「客户端用的 `http_url`」又当「Django 调 imserver 的基地址」（`im/self_client.py:43`）。双机后必须拆成三个配置：

| 新配置 | 用途 | 例子 |
|---|---|---|
| `IM_SELF_INTERNAL_URLS` | Django → imserver，**列表**，逐台调用 | `http://127.0.0.1:9101,http://10.0.0.2:9101` |
| `IM_SELF_PUBLIC_HTTP_URL` | 下发给客户端的 `http_url` | `https://chat.shiliu153.cn/im/api` |
| `IM_SELF_WS_URLS` | 按 uid 下发的 `ws_url` 列表 | 见 §6.2 |

必须 fan-out 的接口（只发一台就会出现「一半用户行为不一致」）：

- `/internal/kick` —— 不 fan-out 则**单设备登录失效**（旧设备在另一台，踢不到）。
- `/internal/profile` —— 不 fan-out 则另一台的 `profiles_` 缓存（上限 10 万）保留旧昵称/头像。
- `/internal/session_version` —— 必须保证「用户即将连接的那台」成功；建议 fan-out 后**要求目标节点成功**才签发 token（保持现在的 fail-closed 语义）。
- `/internal/pair`、`/internal/blacklist`、`/internal/unblock`、`/internal/delete_account` —— 无状态写库，fan-out 冗余但安全。
- `/internal/send` —— 系统灰条。有 `uk_from_client` 幂等兜底，但**重复插入的那台不会推送**，所以要么按 owner 路由，要么让「重复命中」分支也执行本地推送。

### 6.5 双活的已知代价（接受即可，别当成 bug）

1. **限流翻倍**：`auth_buckets_` / 每账号发送配额都是进程内的，双活后单账号额度实际 ×2。要精确就挪到 Redis，暂不做。
2. **缓存两份**：`profiles_` 每节点独立，靠 fan-out 保持一致。
3. **seq 不重复**：仍由共享 MySQL 的 `uk_conv_seq` 保证，跨节点安全。
4. **在线态天然一致**：`touch_online` 写 Redis DB2，两台共享。

---

## 7. 改造清单

### 7.1 运维侧（不改代码）

- [ ] 两台 `chrony` 对时——**签名 URL（TTL 3600）和 JWT 都吃时间**，偏差大会出现「刚上传的图 403」。
- [ ] A 防火墙：3306 / 6379 / 2049 只对 `10.0.0.2` 开放；9100 / 9101 保持只监听回环。
- [ ] B 的 nginx 内网监听 `10.0.0.2:9100/9101`（`allow 10.0.0.1; deny all;`）。
- [ ] 两台 nginx 配置保持同一份（用 git 管理 `/www/server/panel/vhost/nginx/`，别在面板里手改）。
- [ ] 证书：A 上 certbot 签发，`--deploy-hook` 里 `rsync` 到 B 并 reload B 的 nginx（扩展 `docs/ops/certificates.md` §4）。
- [ ] `NUM_PROXIES` 保持 `1`：B 的 gunicorn 只被 A 的 nginx 反代一跳。**如果中间又加了一层 nginx，必须改成 2**，否则全站限流共用一个桶（`settings.py:242`）。
- [ ] `IM_TRUSTED_PROXIES` 追加 `10.0.0.1`：否则 imserver 看到的所有连接都来自入口内网 IP，`IM_MAX_CONN_PER_IP` 会把全站当成一个人（`imserver/src/net/guard.cpp`）。
- [ ] `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` 加备用入口域名（如 `chat-b.shiliu153.cn`）。
- [ ] 定时任务只在 A：媒体清理（04:00）、探针（5 分钟）、备份（03:00）、续证。B 上**不启用**，但手册里写清「接管时手动开」。
- [ ] 两台 `.env` 用 diff 校验一致性（`IM_SELF_GRAYLIST`、`IM_MEDIA_SIGN_SECRET`、`MIN_APP_VERSION` 三件套、`MEDIA_BASE_URL` 必须完全相同）。

### 7.2 Django 侧

- [ ] `settings.py`：新增 `IM_SELF_INTERNAL_URLS`、`IM_SELF_PUBLIC_HTTP_URL`、`IM_SELF_WS_URLS`，保留旧键做兼容。
- [ ] `im/views.py:91-92`：`ws_url` 按 uid 取模；`http_url` 用 public 配置。
- [ ] `im/self_client.py`：`_post` 改为「逐台 fan-out，单台失败记日志不抛出」，`set_session_version` 例外（目标节点必须成功）。
- [ ] `imserver/deploy/*`：`.env` 增加 `IM_NODE_ID`。
- [ ] 测试：`im/tests.py` 补「两台 internal URL」用例；`imserver` 补 `/internal/deliver` 单测 + 双实例集成测试。

### 7.3 imserver 侧

- [ ] `SessionRegistry`：新增 owner 写入 / 查询 / 跨节点转发（`send_to` 内部完成，调用方无感）。
- [ ] `http_api.cpp`：新增 `/internal/deliver`（HMAC 鉴权，只推不落库）。
- [ ] `config`：`IM_NODE_ID`、`IM_PEER_URLS`（对端 9101 地址）。
- [ ] 失败降级：对端不可达 → WARN 日志 + 返回 false，靠离线补拉兜底，**不能让发送方失败**。

### 7.4 客户端（可选，但建议做）

- [ ] App `self_im_client.dart:178` 的重连固定用 `bootstrap.wsUrl`：连续失败 3 次后**重新拉一次 `/im/user_sig`**（节点故障时能自动换到健康节点）。
- [ ] Web `im/self/client.ts` 目前**没有自动重连**：补一个指数退避重连，逻辑同上。

---

## 8. 分阶段实施

| 阶段 | 内容 | 产出 / 验收 | 回滚 |
|---|---|---|---|
| **P0** 准备（0.5 天） | B 装环境（同版本 Python/Node/MySQL/Redis/nginx）、内网互通验证、时钟同步 | `ping 10.0.0.1`、`nc -z 10.0.0.1 3306` 通 | 无影响 |
| **P1** 数据共享（1 天） | MySQL 主从、Redis 主从、NFS 导出/挂载、备份 | B 上 `SELECT` 能读到 A 的新数据；B 上传的图 A 能直出 | 停从库、卸载 NFS |
| **P2** 应用双活（1 天） | A 的 upstream 加入 B:8000；B 部署 dist；两台 `.env` 对齐 | 反复刷 `/api/v1/users/me`，`X-Node` 头（临时加）能看到两台都命中；`python manage.py test` 两台全绿 | 从 upstream 摘掉 B |
| **P3** IM 双活（2–4 天） | §6 全部改造 + 双实例集成测试 + 压测 | 两台各 500 连接；A 用户发 B 用户，实时收到；`verify_graylist.py` 17 条断言全过 | `IM_SELF_WS_URLS` 只留一台 |
| **P4** 故障演练（1 天） | 按 §11 逐项演练，写进运维手册 | 演练记录 + RTO 实测值 | — |

**顺序不能换**：P3 依赖 P1（共享 DB/Redis），P4 依赖 P2/P3。每阶段全绿再进下一步。

---

## 9. 容量与压测

- 目标：两台各 500 WS 连接（合计 1000），沿用 `imserver/scripts/bench_ws.py`，分别打 `?node=a` / `?node=b`。
- 关注指标：ack p99（现基线 93ms @50msg/s）、RSS（现 22MB/500 连接）、跨节点投递的额外延迟（内网 HTTP，预期 +1ms 内）。
- 注意：压测时 `IM_MAX_CONN_PER_IP` 会误伤（所有连接同一出口），临时调大后再压，压完改回。
- HTTP 侧：`GET /users/me` 目标从 ~53 req/s 提升到 ~100 req/s 量级，用 `wrk`/`hey` 双机对比。

---

## 10. 风险与坑

| 坑 | 后果 | 对策 |
|---|---|---|
| A 挂 = 数据层挂 | 全站不可用（登录、聊天全停） | 明确写进 SLA；从库/副本 + 手册人工接管；想彻底解决走方案 C |
| Redis 异步复制丢最后写入 | 少量验证码/计数/任务丢失 | 接受；验证码重发；关键任务靠 DB 状态兜底 |
| NFS uid 映射错 | 上传报 500 / 图片 404 | `all_squash` + 固定 anonuid，P1 阶段用真实上传验证 |
| 媒体路径两台不一致 | 一半图片 404 | 挂载点路径与 `MEDIA_ROOT` 完全一致，写进核对单 |
| `NUM_PROXIES` 与实际跳数不符 | 全站限流共用一个桶，或可被伪造 XFF 绕过 | 每加一层代理都要复核 `settings.py:242` |
| `IM_TRUSTED_PROXIES` 未加内网 IP | 500 连接上限被当成 1 个 IP，用户连不上 | P3 前先改配置并验证 `X-Real-IP` |
| 双 worker 重复执行 | 灰条/通知发两遍 | 任务本身按 `client_msg_id`/状态位幂等；上线前跑一遍双 worker 冒烟 |
| 两台 `.env` 漂移 | 同一用户两台行为不同（灰度、版本号） | 部署脚本 diff 校验，不一致直接拒绝重启 |
| 证书只在 A 续 | B 顶入口时证书过期 | `--deploy-hook` rsync 到 B，续期后自动 reload |
| 时钟偏差 | 签名 URL / JWT 异常 | chrony + 监控 `chronyc tracking` |
| 宝塔面板双份手改 | 配置漂移，回滚困难 | nginx 配置入 git，面板只读 |

---

## 11. 故障手册（RTO 矩阵）

| 故障 | 影响 | 自动恢复 | 人工步骤 | 目标 RTO |
|---|---|---|---|---|
| B 的 gunicorn 挂 | 无（upstream 摘除） | ✅ | 无 | 0 |
| B 整机挂 | WS 上 B 的用户断线 | 部分（重连打回同一 URL，见 §7.4） | 把 `map` 里 `b` 指回 `127.0.0.1:9100` | 1 分钟 |
| A 的 nginx 挂 | 全站不可达 | ❌ | DNS 切 B（TTL 60） | 2–5 分钟 |
| A 的 MySQL 挂 | 全站 503 | ❌ | B 提升从库 → 改 `DB_HOST` → 重启 web/worker | 5–15 分钟 |
| A 的 Redis 挂 | 登录/限流/队列全停 | ❌ | B 提升副本 → 改 `REDIS_URL`/`BROKER_URL` → 重启 | 5–15 分钟 |
| A 的 NFS 挂 | 图片/语音 404，上传失败 | ❌ | 修 NFS；B 本地无副本（除非做冷备恢复） | 视情况 |
| imserver 单台挂 | 该节点用户断线 | 部分 | 改 `map` 指向另一台（跨节点投递自动兜住） | 1 分钟 |

> 结论再强调一次：**只有「B 相关故障」是真正无感的**。A 是数据节点，这是你选择「不买云服务」的直接代价。

---

## 12. 需要你确认的 5 件事

1. 第二台是否**同地域**？（轻量「内网互通」的前提，跨地域只能走公网，方案要改。）
2. 域名 DNS 的 TTL 能否降到 **60 秒**？（决定 A 挂后切 B 的速度。）
3. 能否接受「A 挂 = 5–15 分钟人工接管」？如果不能，我们得改方案 C（加一台或买云服务）。
4. 要不要顺便加一台最小 ECS 做入口（方案 B，约 ¥30–60/月）？加了之后 A 挂时入口还在，切换更快。
5. B 机是否已有公网 IP 与备案？（`chat.shiliu153.cn` 已在 A 上备案；B 作为备用入口建议用同主域的子域，避免重新备案。）

---

## 13. 这份方案**没有**做的事

- 没有改任何代码、没有动服务器、没有新增依赖。
- 没有把「自动故障转移」包装成能做到——两台机器 + 无托管数据层，做不到。
- 没有引入 Kubernetes / Docker Swarm / 服务网格：2C2G × 2 的规模，这些只会增加故障面。
