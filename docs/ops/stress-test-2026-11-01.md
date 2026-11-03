# 2026-11-01 高并发压测与「打崩自愈」演练

> 目标:把线上 `https://chat.shiliu153.cn`（阿里云轻量 2C2G）压到崩，验证各组件能否自动恢复。
> 结论先行:**应用层能自愈，数据库层不能**；另外压出一个线上还没暴露的**冷启动死锁**。

## 0. 结论速览

| 组件 | 故障方式 | 自动恢复 | 实测恢复时间 |
|---|---|---|---|
| Django(gunicorn) | `kill -9` 主进程 | ✅ supervisor `autorestart` | < 1s（1 个 502 采样） |
| 自建 IM(imserver) | `kill -9` 进程 | ✅ Docker `restart: unless-stopped` | 3.2s |
| 自建 IM | `docker kill` | ❌ | 人工 90s（见 §4 坑） |
| MySQL | `kill -9 mysqld` | ✅ `mysqld_safe` 拉起 | 2.6s |
| MySQL | `kill -9 mysqld` + `mysqld_safe` | ❌ **永久宕机** | 必须人工 |
| MySQL | 被 OOM 杀 | ✅ `mysqld_safe` 拉起 | ~6s |
| 全栈同时打崩 | 三个一起 `kill -9` | ⚠️ 部分 | 111s（其中 MySQL 靠人工） |

容量基线:HTTP 稳定 **~550–600 rps**（超过只排队、不出 5xx）；WS **1000 连接 / 2000 条消息 0 失败**，热会话吞吐 ~165–400 msg/s。

---

## 1. 环境与方法

- 机器:2 vCPU / 1870MB RAM / 1024MB swap（压测前已用 678MB），负载 0。
- 组件:nginx(80/443) → gunicorn `-w 2 --threads 4`(127.0.0.1:8000)；imserver 容器(host 网络，9100/9101)；mysqld 由 `mysqld_safe` 托管；Redis。
- 采样:服务器上每 2s 记录 load/内存/swap/TCP 连接/各进程 RSS；混沌期间另起 0.5s 粒度的健康探针（`docs/ops/stress/chaos_watch.sh`）。
- 压测器（全部放在 `docs/ops/stress/`，可直接复用）:
  - `http_load.py`（公网侧，httpx）——**只用来验证公网表现，不代表服务器容量**：本机出口先饱和，conc=400 时 p50 4.1s、RPS 反降到 72，但服务器 0 个 5xx。
  - `srv_load.py`（服务器内网侧，纯 asyncio）——真实容量。
  - `imserver/scripts/bench_ws.py`（仓库自带，伪造 `X-Real-IP` 模拟多客户端）。
- 数据:临时造了 1000 个 `u900001+` 的 IM 账号/配对/会话做 WS 压测，**测试后已全部清理**（库内恢复 9 用户 / 3 配对 / 56 条消息，最后 1 条是压测后的连通性检查）。

## 2. 容量基线

### 2.1 HTTP（直连 gunicorn，排除公网干扰）

| 并发 | RPS | p50 | p95 | p99 | 非 200 |
|---|---|---|---|---|---|
| 20 | 608 | 31ms | 70ms | 101ms | 0 |
| 50 | 576 | 98ms | 186ms | 294ms | 0 |
| 100 | 601 | 165ms | 276ms | 329ms | 0 |
| 200 | 569 | 325ms | 488ms | 566ms | 0 |
| 400 | 552 | 692ms | 887ms | 995ms | 0 |

**读法**:并发从 20 加到 400，RPS 稳在 550–600，延迟线性上涨 —— 典型的「排队而不是崩溃」。2 个 worker × 4 线程 = 8 个并发处理位，单请求服务端耗时约 1ms，理论上限就在 600 附近，实测吻合。**没有出现 5xx，也没有 OOM**。

### 2.2 WebSocket（imserver）

| 场景 | 连接 | 消息 | 失败 | ack p50 |
|---|---|---|---|---|
| 热会话 burst | 500 | 1000 | 0 | 2.55s |
| 热会话 burst | 1000 | 2000 | 0 | 5.01s |
| **冷会话 burst** | 500 | 1000 | **819** | 5.55s |

1000 连接全部握手成功（`connect_fail=0`），imserver RSS 仍只有 ~50MB。冷/热会话的差别就是 §4 的 P0。

## 3. 崩溃与自愈矩阵（逐条实测）

### 3.1 gunicorn 主进程 `kill -9`
```
19:54:45.561 kill -9
19:54:45.637 http=502   ← 只有 1 个采样点
19:54:46.1xx http=200
```
supervisor 3 秒内换新 PID（`chatapp-web_00 RUNNING pid 1228231`）。**用户侧感知 < 1 秒**。

### 3.2 imserver 进程 `kill -9`
```
19:52:57.992 kill -9
19:52:58.065 readyz=000
19:53:01.227 readyz=200   → 3.2s，RestartCount 0→1
```
`docker inspect` 显示 `restart: unless-stopped` 生效。

### 3.3 MySQL 单杀 / 双杀
```
kill -9 mysqld        → readyz 503 约 1.5s → 2.6s 后 200（mysqld_safe 拉起）
kill -9 mysqld_safe + mysqld → 3 分钟后仍然 DEAD，没有任何东西拉起
```
`systemctl cat mysqld` 是 sysv 生成的 unit，**`Restart=no`**。也就是说:MySQL 的「自动恢复」完全押在 `mysqld_safe` 这一个用户态包装进程上，它自己挂了就没人管了。

### 3.4 OOM
- 普通场景:压力进程涨到 ~1GB 时内核挑它下手（`Out of memory: Killed process ... (python)`），**其余服务毫发无损**。
- 定向场景:把 `mysqld` 的 `oom_score_adj` 调到 1000 后施压 → mysqld 被杀，**6 秒后 mysqld_safe 拉回，`SELECT 1` 恢复，imserver readyz=200**。

### 3.5 全栈同时打崩
```
20:03:16 kill -9 gunicorn + imserver + mysqld + mysqld_safe
T+4s   http=200（gunicorn 已回来）
T+60s  imserver readyz 仍是 000（容器在 crash loop）
20:04:16 人工拉起 mysqld
20:05:03 imserver 才起来（比 DB 恢复晚 47s）
20:05:07 全绿 → 总计 111s
```

## 4. 发现的问题

### P0-1 冷启动并发建会话死锁（线上未暴露，但一定会踩）
500 对**全新**配对同时发第一条消息：**819/1000 失败**，错误码 50001，imserver 日志刷 `deadlock retry exhausted`。把会话行预先插好再跑同一份脚本：**1000/1000 成功、0 错误**。

根因在 `imserver/src/store/conversation_repo.cpp::lock_pair`：
```sql
SELECT ... FROM im_conversation WHERE user_a=? AND user_b=? FOR UPDATE;  -- 行不存在
INSERT INTO im_conversation ...;                                          -- 并发插入互相死锁
```
MySQL 默认 REPEATABLE READ 下，对**不存在的行**做 `FOR UPDATE` 会加间隙锁，几百个事务同时抢同一段间隙 → 1213 死锁。`message_service.cpp` 只重试 3 次、退避 2/4/6ms，扛不住这个并发度。

线上现在只有 9 个用户，所以没炸；一旦有一波集中配对（活动/推荐位），第一批消息会大面积失败。

### P0-2 MySQL 没有系统级守护
`systemd` 的 `Restart=no`。实测双杀后**永久宕机**，只能人工 `/etc/init.d/mysqld start`。数据库是整个系统的单点，这一条必须补。

### P1-3 imserver 启动强依赖 MySQL，会陷入 crash loop
DB 不可达时 imserver 直接 `fatal: mysql connect failed` 退出，Docker 按指数退避重启（0.1s→0.2s→…→60s）。结果:
- DB 宕机期间它一直起不来（本次 RestartCount 涨到 11）；
- **DB 恢复后还要再等一个退避周期**，实测多等了 47s。

### P2-4 DB 故障时 Django 返回 HTML 500
`/users/me` 在 MySQL 宕机期间返回的是 Django 的 `Server Error (500)` HTML 页，不是约定的 `{"code":500,...}` JSON。客户端解析会二次报错。

### P2-5 探针粒度不够，且没有推送通道
`imserver-readyz-探针` 每分钟一次、连续 2 轮才 ALERT。实测 19:51 那次 90 秒的宕机只记了 1 次失败，**没触发 ALERT**；全栈那次 20:05:01 才告警。另外 `probe.env` 没配 webhook，告警只落 `/www/wwwlogs/imserver_probe.log`，没人看得到。

## 5. 数据完整性

| 检查项 | 结果 |
|---|---|
| `(conv_id, seq)` 重复 | 0 |
| `im_conversation.last_seq` 与 `MAX(seq)` 不一致 | 0 |
| 崩溃期间消息丢失/重复 | 0（崩溃前后 `im_message` 计数一致） |
| `manage.py check` | 无问题 |
| `(from_id, client_msg_id)` 重复 | 仅 2 条历史 e2e 数据（不同发送方，唯一键允许） |

结论:**进程级打崩没有污染数据**，InnoDB 崩溃恢复可靠。

## 6. 修复建议（按优先级）

> 2026-11-02 更新：P0-1、P1-3、P2-4 已修复并通过回归（含 500 冷会话端到端 0 失败）；
> P0-2 的看门狗脚本与 systemd drop-in 已入库，待上线安装。执行记录见
> [2026-11-02-observability-and-capacity.md](../superpowers/plans/2026-11-02-observability-and-capacity.md) §7。

1. **P0-1**:`lock_pair` 改成「先 `INSERT ... ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)` 拿到 id，再 `SELECT ... FOR UPDATE`」，让插入在事务最前面、不持有间隙锁；同时把重试从 3 次提到 8 次并加随机抖动。这是改动最小、收益最大的一条。
2. **P0-2**:给 `mysqld` 的 systemd unit 加 `Restart=always` + `RestartSec=5`；再补一条每分钟的计划任务探 3306，失败就 `/etc/init.d/mysqld start`（和现有 readyz 探针同思路）。
3. **P1-3**:imserver 启动时 DB 连接失败不要 `fatal`，改成「60 秒内每 2 秒重试」，或给容器加 `healthcheck` 并把重启退避压到 5s 内。
4. **P2-4**:加 DRF 的 500 异常处理器，保证任何情况下都返回 JSON 错误契约。
5. **P2-5**:探针改 30s 一次，`probe.env` 配一个企业微信/钉钉机器人；顺手把 gunicorn/MySQL 也纳入探针。

## 7. 复现方式

```bash
# 容量（脚本都在 docs/ops/stress/）
scp docs/ops/stress/srv_load.py root@<IP>:/root/
ssh root@<IP> '/www/wwwroot/chatapp-venv/bin/python /root/srv_load.py --port 8000 --conns 200 --dur 20'

# 单点打崩
ssh root@<IP> 'kill -9 $(pgrep -f "127.0.0.1:8000 -w 2" | head -1)'          # gunicorn
ssh root@<IP> 'kill -9 $(pgrep -f "^/usr/local/bin/imserver" | head -1)'     # imserver
ssh root@<IP> 'kill -9 $(pgrep -x mysqld)'                                   # 只杀 mysqld
ssh root@<IP> 'kill -9 $(pgrep -x mysqld) $(pgrep -f "^/bin/sh /www/server/mysql/bin/mysqld_safe")'  # 双杀=永久宕机

# 全栈
scp docs/ops/stress/fullstack.sh root@<IP>:/tmp/ && ssh root@<IP> 'bash /tmp/fullstack.sh'
```

> **踩过的坑**:`pkill -f <pattern>` 会匹配到 ssh 自己的命令行（因为命令串里就含这个 pattern），把会话一起杀掉。要么用 `pgrep -x`，要么用 `^` 锚定完整路径。

## 8. 本次未测

- 机器整机重启（会走 init.d 自启，但没验证）；
- Redis 挂掉的影响（`kill -9 redis-server`）；
- nginx 挂掉；
- 长时间（>1h）稳定性与内存泄漏趋势；
- 客户端侧断线重连体验（App/Web 在 imserver 重启后能否自动重连并补拉）。
