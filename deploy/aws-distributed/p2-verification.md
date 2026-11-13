# P2 验证结果：HTTP 层双副本 + nginx 分流（2026-11-13）

> 状态：**已跑通并实测**。但跨机链路暂时走 **SSH 隧道**（安全组未放行内网业务端口，
> 且 `aws login` 会话过期改不了）。因此：**功能结论可信，容量数字是保守下界**。

## 1. 拓扑（隧道版）

```
                        访问 :8080
                            │
        ┌───────────────────▼────────────────────┐
        │ EDGE 13.211.212.232 (172.31.14.4)      │
        │  nginx ── least_conn ──┐               │
        │  Django-A  web:8000  ◄─┤               │
        │  MySQL / Redis / Celery / imserver-A   │
        └───────────┬────────────┴───────────────┘
                    │                     ▲
     隧道A(APP→EDGE)│  13306/16379/19101  │ 隧道B(EDGE→APP) 18000→18080
                    ▼                     │
        ┌───────────────────────────────────┴────┐
        │ APP 32.236.245.150 (172.31.35.181)     │
        │  Django-B  (宿主 127.0.0.1:18080)      │
        │  与既有 chaoxing-web 共存              │
        └────────────────────────────────────────┘
```

- 隧道都用 SSH（两台之间 22 端口本来通），`ServerAliveInterval=30` 保持。
- APP 侧容器访问宿主隧道用**本网段网关** `172.19.0.1`（见 §4.3 的坑）。

## 2. 实测数字（口径与单机基线完全一致）

同一台压测机（EDGE）、同一个 `perf/run.py`、同一个路径（经 nginx `127.0.0.1:8080`）、
同样 30 秒。

| 并发 | 单机 rps | 双副本 rps | 提升 | p50 单机 → 双副本 | 错误 |
|---|---|---|---|---|---|
| 100 | 801.3 | **1 215.2** | **+52%** | 122 ms → 82.5 ms | 0 |
| 400 | 767.9 | **1 229.1** | **+60%** | 511 ms → 329.9 ms | 0 |

**结论：加一台同 region 的副手，读吞吐提升 5–6 成，尾延迟同时下降。**

### 为什么不是 2×

这不是配置问题，是测量条件：

1. **压测器就跑在 EDGE 上**，与副本 A、nginx、MySQL、Redis、Celery 抢同 2 个核；
2. **APP 副本的每条 SQL 都要走 SSH 隧道**（客户端在 APP 容器里 → SSH 加密 → EDGE → MySQL），
   Django 一个请求 8 条串行查询，这段开销被放大 8 次；
3. **t3.small 是突发型**，两台基线算力各 0.4 vCPU（设计稿 §7.1）。

第 2 条在安全组放行、改成直连内网后会显著改善 —— 那时应当**重测一遍**，
本表数字视为下界。

## 3. 分流与故障摘除都验过了

| 验证 | 做法 | 结果 |
|---|---|---|
| 双副本都在干活 | 连打 20 次 `/api/v1/app/config` | EDGE 处理 22、APP 处理 18，全部 200 |
| 摘掉副本不挂站 | `docker stop chatapp-app-web-1` 后连打 10 次 | **10/10 仍 200**（`max_fails=3 fail_timeout=10s` 生效） |
| 恢复后重新参与 | `docker start` 后重测 | 吞吐回到 1 215 rps |

## 4. 落地时踩到的 4 个坑（安全组放行后仍有 2 条成立）

### 4.1 APP 上 `127.0.0.1:8000` 被占用

`chaoxing-web` 正听着 `127.0.0.1:8000`，首次部署直接
`failed to bind host port 127.0.0.1:8000: address already in use`。
**改用 18080**。这条与安全组无关，长期有效。

### 4.2 APP 上 ufw 是 active、INPUT 策略 DROP

容器连宿主隧道端口全部**超时**（不是拒绝，很像网络不通，容易误判）。
`22` 是放行的，所以问题只在业务端口。加窄规则即可：

```bash
sudo ufw allow from 172.19.0.0/16 to any port 16379 proto tcp comment "chatapp tunnel"
```

EDGE 侧同理要给 nginx 容器放行 `172.28.0.0/16 → 18000`。
**安全组放行后这些 ufw 规则仍然需要**（容器到宿主/内网也是 ufw 管的）。

### 4.3 `host.docker.internal` 在自建 compose 网络里**不可用**

Docker 的 `host-gateway` 解析到的是 **docker0 的 172.17.0.1**，
而新建的 compose 网络被分到 `172.19.0.0/16`，跨网桥被 iptables 拦掉 → 连接超时。
**必须用容器自己网段的网关**（本例 `172.19.0.1`）。
写死网关也有风险（网络重建会换网段），生产态应改成直连对端内网 IP，彻底绕开。

### 4.4 `pkill -f` 会杀掉自己的 ssh 会话

用 `pkill -f "172.17.0.1:13306"` 清理旧隧道时，远端 shell 的命令行里含同样字符串，
**把自己这条连接杀了**（表现为无输出、退出码 1）。改用 `sudo fuser -k 13306/tcp`。

## 5. 复现步骤（隧道版）

```bash
# ① 互信
#    EDGE 生成密钥 -> 追加到 APP ~/.ssh/authorized_keys（EDGE→APP）
#    APP  生成密钥 -> 追加到 EDGE ~/.ssh/authorized_keys（APP→EDGE）

# ② 隧道A（在 APP 上）：数据层 + IM 内部接口
ssh -f -N -o ServerAliveInterval=30 \
  -L 0.0.0.0:13306:172.18.0.3:3306 \
  -L 0.0.0.0:16379:172.18.0.2:6379 \
  -L 0.0.0.0:19101:172.18.0.5:9101 \
  -i ~/.ssh/id_ed25519_app2edge ubuntu@172.31.14.4

# ③ 隧道B（在 EDGE 上）：nginx -> APP 副本
ssh -f -N -o ServerAliveInterval=30 \
  -L 172.28.0.1:18000:127.0.0.1:18080 \
  -i ~/.ssh/id_ed25519_aws2aws ubuntu@172.31.35.181

# ④ APP 侧部署（compose.app.yml + secrets/chatapp.app.env）
cd /opt/chatapp-app && sudo docker compose -f compose.app.yml up -d

# ⑤ EDGE 侧换成双上游
sudo cp deploy/aws-distributed/nginx/edge.conf /opt/chatapp-edge/nginx/conf.d/default.conf
sudo docker exec chatapp-nginx-1 nginx -s reload
```

## 6. 安全组放行后要改的东西（一次一处）

| 位置 | 从 | 改成 |
|---|---|---|
| APP `chatapp.app.env` 的 `DB_HOST`/`REDIS_URL`/`BROKER_URL`/`IM_SELF_URL` | `172.19.0.1:隧道端口` | EDGE 内网 `172.31.14.4:原生端口` |
| EDGE nginx `upstream chatapp_api` 的第二个 server | `172.28.0.1:18000` | `172.31.35.181:8000` |
| 两条 SSH 隧道 | 需要 | **删掉** |
| ufw 里那 4 条隧道端口规则 | 需要 | 可删（改用内网直连） |

## 6.1 跨机 IM 两节点簇（2026-11-13 18:20 实测通过）

在 APP 节点上又跑了一份 **imserver**（`IM_INSTANCE_ID=app`），与 EDGE 的 `edge` 组成两节点簇。
数据层经隧道回源（IM 的 MySQL/Redis 都在 EDGE）。

| 验证 | 做法 | 结果 |
|---|---|---|
| 两节点都在跑 | `delivery_bus_started` 日志 | `instance_id=edge` + `instance_id=app`，各自 `redis_sub_subscribed` |
| EDGE 能到 APP 的 imserver | 从 EDGE 探 `172.28.0.1:19101/internal/healthz` | `{"ok":true}` |
| **真跨机投递** | 客户端 A 连 `imserver:9100`(EDGE)、客户端 B 连 `172.28.0.1:19100`(APP) | **`split_a_b delivered=True`，`verdict=FIXED`** |

这是**两台不同 EC2、不同可用区**之间的真跨机投递（不是同机两容器）。

nginx 侧不需要 sticky（会话归属在 Redis 的 owner 键里）：

```nginx
upstream chatapp_im_ws   { least_conn; server imserver:9100; server 172.28.0.1:19100; }
upstream chatapp_im_http { least_conn; server imserver:9101; server 172.28.0.1:19101; }
```

新增隧道（EDGE → APP）：`172.28.0.1:19100 → APP 127.0.0.1:9100`、`19101 → 9101`；
EDGE 的 ufw 要放行 `172.28.0.0/16 → 19100`。

## 6.2 ⚠️ 血的教训：绝不要在 APP 节点上编译 imserver

2026-11-13 尝试在 APP 上 `docker build imserver`，结果：

- 2 vCPU / 2G 上编译 boost + MySQL 客户端头文件，**内存打满 → 3G swap 全部用上**；
- **load average 冲到 36**，sshd 连 banner 都发不出来，机器失联约 30 分钟；
- 该节点还跑着 `chaoxing-web`（另一个项目）—— 差点把别人的服务一起拖垮；
- 期间宝塔 `bt.service` 也掉了（事后已 `systemctl start bt` 恢复）。

**正确做法（已验证，10 秒）**：在 EDGE 构建好，走内网传镜像：

```bash
# EDGE 上构建（2G 但已装好依赖层，实测 ~4 分钟）
docker build -t chatapp-imserver:local imserver
# 内网传输 + 载入，533MB 实测 10 秒
docker save chatapp-imserver:local | ssh ubuntu@172.31.35.181 'sudo docker load'
```

同理：t3.small 的 CPU 积分在长时间高负载后会耗尽、被限速到 0.4 vCPU，
这时编译不是「慢」而是**近乎卡死**。这条与设计稿 §7.1 是同一件事的两个侧面。

## 6.3 IM 吞吐：两节点对照（2026-11-13 18:30）

同一份负载（4000 条消息）分别压「1 个节点」与「2 个节点」，用仓库自带的
`imserver/scripts/bench_ws.py`（burst 模式：每条连接连发 20 条并等 ack）。

| 跑法 | 连接 | ack | 错误 | p50 | p95 | p99 | max |
|---|---|---|---|---|---|---|---|
| 单节点（全压 EDGE） | 200 | 4 000 | 0 | **1 752 ms** | 1 845 ms | **1 872 ms** | 1 935 ms |
| 双节点 · EDGE 侧 | 100 | 2 000 | 0 | 1 265 ms | 1 408 ms | 1 463 ms | 1 572 ms |
| 双节点 · APP 侧 | 100 | 2 000 | 0 | 1 494 ms | 1 644 ms | 1 707 ms | 1 803 ms |

**结论：两节点把同一负载下的 p99 从 1 872 ms 降到 1 707 ms（约 −9%），提升有限。**

为什么不是接近 2×？——因为**瓶颈不在 imserver 进程，而在它下面共享的单点**：

1. 两个节点的消息**落库**都打 EDGE 的 MySQL（`im_message`/`im_conversation` 等），
   而 EDGE 只有 2 核，还要同时跑 nginx/Redis/Celery/Django；
2. 两侧的**发送配额、在线键、owner 键**全部读写 EDGE 的 Redis；
3. APP 侧的 DB/Redis 流量还要**经 SSH 隧道**（比内网直连更慢）。

也就是说：**IM 的水平扩展在这套拓扑里被数据层单点卡住了**，与设计稿 §3.1「数据层单点（有意为之）」
的取舍一致。真要提 IM 吞吐，顺序是「数据层从 EDGE 拆出去 → 内网直连 → 再谈加 imserver 节点」。

> 附件说明：EDGE 侧那轮第一次跑出现 20 个 `40302`（无法发送），是**造数漏洞**
> ——压测账号的环形对端没建配对，不是容量问题；补齐配对后重跑为 0 错误，上表是重跑数据。

## 7. 仍然没做的

| 项 | 原因 |
|---|---|
| IM 多实例 | 等 #288（`lab_cross_node.py` 已备好判据） |
| `POST /posts` 落图钉本机 | `limit_except` 与 `proxy_pass` 的组合需实测，本轮先只钉了三个上传接口 |
| 写路径双副本对照 | 本轮只对比了读；写路径受隧道延迟影响更大，等直连后测更有意义 |
| 公网域名/证书 | 安全组未放行 80/443 |
