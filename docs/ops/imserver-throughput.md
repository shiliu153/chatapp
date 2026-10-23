# 自建 IM 吞吐优化记录(2026-10-22)

> 环境:阿里云轻量 **2C2G** · Alibaba Cloud Linux 3 · MySQL 8.0.45(同机,binlog 开启)
> · Redis 7.4 · imserver 容器(`network_mode: host`)· 压测脚本 `imserver/scripts/bench_ws.py`
>
> 关联:`docs/ops/imserver.md`(部署与运维)、`docs/superpowers/plans/2026-10-20-self-hosted-im-rollout.md`(灰度核对单)

## 1. 结论

| 指标 | 优化前 | 优化后 |
|---|---|---|
| 1000 条消息突发耗时 | 9.4 s | **4.7 s** |
| 吞吐 | 106 msg/s | **215 msg/s** |
| 每条消息 MySQL 往返 | ~18 次 | ~7 次 |
| 500 连接稳态 p99(50 msg/s) | 93 ms | 93 ms(未退化) |
| RSS | 22 MB | 22 MB |

**2C2G 的天花板约 200–250 msg/s**:MySQL 实测 1500–2000 条简单 SQL/秒,而一条消息仍需
~7 条 SQL。要到 1000 msg/s,只能升配(4C8G+)、应用层批量提交、或把 unread 异步化,
详见第 7 节。

## 2. 测试方法

```bash
# 服务器上(直连 127.0.0.1:9100,逐连接伪造 X-Real-IP)
IM_JWT_SECRET=$(grep '^IM_JWT_SECRET=' /www/server/imserver/imserver.env | cut -d= -f2) \
  /root/bench-venv/bin/python imserver/scripts/bench_ws.py \
  --n 32 --count 32 --hold 0

# 公网经 nginx(同一出口 IP,需临时调大 IM_MAX_CONN_PER_IP / IM_AUTH_RATE / IM_AUTH_BURST)
python imserver/scripts/bench_ws.py --uri ws://<SERVER_IP>/im/ws \
  --n 500 --interval 10 --duration 60
```

要点:

- 服务端默认**单 IP 最多 20 条连接、鉴权 1 次/秒(burst 60)**,同机压测要逐连接伪造
  `X-Real-IP`;公网压测则临时调大三个配置项,压完改回。
- 吞吐模式 `--count N`:每条连接发固定 N 条、不 sleep,量的是服务端极限;
  稳态模式 `--interval/--duration` 量的是正常聊天速率下的延迟。
- **不要在同一台 2C2G 上同时跑压测客户端和被测服务**:客户端会抢走一个核,
  把服务端延迟放大成"假瓶颈"。早期就踩过这个坑(见 3.2)。

## 3. 定位过程(按时间顺序,含失败假设)

### 3.1 基线

500 连接、每人 2 条(1000 条),服务端直连:**9.4 s ≈ 106 msg/s**。
把并发从 8 提到 32、100、200,**吞吐始终 ~106/s**——说明存在全局串行点,
不是连接数问题。

### 3.2 失败假设一:压测客户端抢 CPU

外部(公网)压测时服务器 CPU 只有 imserver 13% / mysqld 6%,但 1000 条仍要 ~4 s。
换成 5 个本地进程 × 100 连接后依旧。结论:**客户端不是主因**,但同机压测确实会放大
延迟,后续改用多进程/公网侧客户端。

### 3.3 失败假设二:fsync / binlog

MySQL 单条 autocommit 插入实测 306/s(3.27 ms/条),批量 50 条一提交 1023/s。
但把 `sync_binlog=0` + `innodb_flush_log_at_trx_commit=2` 后,imserver 吞吐只从
106 → 122/s。**提交刷盘不是主因**(至少不是唯一)。

### 3.4 失败假设三:Redis 在线状态

每帧都调 `refresh_online()` → 单连接 + 全局锁的 `SETEX`。实测 Redis `SETEX`
0.2 ms/次,1000 次只有 0.2 s;按 30 s 节流后吞吐无变化。**排除**。

### 3.5 定位:每条写语句 3 次往返

打开 MySQL general log,单条消息的事务跨度 ~55 ms,语句间隙 2–12 ms;
`slow_log` 里只有 `COMMIT` 超 5 ms(51–64 ms),普通语句都不慢。
再看 `stmt.cpp`:**每条写语句都是 `prepare + execute + close` 三次往返**,
一条消息 4 条写语句 + 2 条查询 + `START` + `COMMIT` ≈ **18 次往返**。

### 3.6 逐步优化与实测

| 步骤 | 1000 条耗时 | 吞吐 |
|---|---|---|
| 基线 | 9.4 s | 106/s |
| + prepared statement 按连接缓存 | 7.0 s | 146/s |
| + 合并 unread / 去掉预查 / 画像缓存(8 线程) | 5.6 s | 182/s |
| + `IM_DB_THREADS=16` | 5.0 s | 205/s |
| + `IM_DB_THREADS=32` | 4.7 s | 215/s |

线程 8→32 只多 18%,再次说明瓶颈在 MySQL 的 SQL 吞吐,不在 imserver 并发。

## 4. 最终改动(提交 `fa0c82a`)

1. **prepared statement 按连接缓存**(`store/stmt.cpp`):以 `(MYSQL*, SQL)` 为键,
   首次 prepare 后复用;连接销毁时 `clear_stmt_cache()` 统一关闭。写语句 3 次往返 → 1 次。
2. **收发双方 unread 合并**:`ConversationRepo::upsert_states()` 用一条多行
   `INSERT ... ON DUPLICATE KEY UPDATE` 写两行,少一次往返。
3. **去掉消息前的 `client_msg_id` 预查**:直接插入,唯一键冲突(1062)时回滚并查已存在
   消息,幂等语义不变(DB 测试 `SameClientMsgIdIsIdempotent` 覆盖)。
4. **用户画像进程内缓存**(`UserRepo::profiles_`):消息热路径不再 `SELECT im_user`;
   `update_profile`/`remove` 时失效。
5. **在线状态节流**(`WsSession::refresh_online`):Redis 写入从每帧一次改为每 30 s
   一次;在线键 TTL 仍是 90 s,「120 s 内有认证请求」的判定语义不变。
6. **诊断开关** `IM_SLOW_SEND_MS`(默认 0):超过阈值的消息打印
   `slow_send` 分阶段耗时(blacklist/lock/insert/touch/state/commit/profile)。

服务器最终配置:`IM_DB_THREADS=32`、`IM_DB_POOL=64`、`IM_SLOW_SEND_MS=0`。

## 5. 最终数据

- 1000 条突发:**4.7 s(215/s)**,0 失败。
- 500 连接 + 50 msg/s 经 nginx 60 s:ack p50 52 ms / p95 67 ms / **p99 93 ms**,RSS 22 MB。
- 幂等:同 `client_msg_id` 重发返回同一 `msg_id`,对端只收到一条。
- 回归:单元 11/11、DB 5/5 全绿。

## 6. 为什么是 ~200–250/s(天花板计算)

| 事实 | 数值 |
|---|---|
| MySQL 简单查询吞吐(8 连接 `SELECT 1`) | 3146 q/s(p50 1.2 ms) |
| 单条消息 SQL 数(优化后) | ~7:START / 黑名单 / 会话锁 / 插消息 / 更新会话 / 合并 unread / COMMIT |
| 理论上限 | 2000 ÷ 7 ≈ **285/s** |
| 实测 | **215/s**(插入唯一索引还有锁竞争) |

所以 2C2G 上 1000 条 ≈ 4.7 s 是**硬件 + schema 的物理结果**;
继续加线程、调 fsync、换客户端都不会有数量级变化。

## 7. 要继续提升的三条路

| 方案 | 预期 | 代价 |
|---|---|---|
| **升配 4C8G+** | 400–800/s,1000 条约 1.5–2.5 s | 花钱,不改代码 |
| **应用层批量提交**:N 条消息一个事务,一次 COMMIT | 3–5x,约 600–900/s | 排队 + ack 延后 1–2 ms + 错误隔离,需独立设计与测试 |
| **unread 异步化**:未读数走 Redis,DB 只存消息 | 1.5–2x | 未读数最终一致,刷新可能短暂不准 |

建议:**先升配**,4C8G 即可把 1000 条压到 2 s 内且零代码风险;
若必须留在 2C2G,再单独立项做批量提交。

## 8. 复现与观测

```bash
# 单条消息分阶段耗时(只打印 >20ms 的)
echo 'IM_SLOW_SEND_MS=20' >> /www/server/imserver/imserver.env
docker compose -f /www/server/imserver/docker-compose.yml up -d
docker logs imserver --since 2m | grep slow_send

# MySQL 侧慢查询(含锁等待)
mysql -uroot -p -e "SET GLOBAL long_query_time=0.005; SET GLOBAL log_output='TABLE';
  SET GLOBAL log_slow_extra=ON; TRUNCATE TABLE mysql.slow_log;"
# ...压测...
mysql -uroot -p -e "SELECT Query_time,Lock_time,LEFT(SQL_text,80)
  FROM mysql.slow_log ORDER BY Query_time DESC LIMIT 10;"
```

注意:诊断开关会为每条慢消息写一行日志,压测完记得置 0。
