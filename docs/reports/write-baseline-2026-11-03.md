# 2026-11-03 写路径容量基线（swipe）

> 目标：把「写路径」也纳入容量基线——此前 `perf/baseline.json` 只有读接口（公开/极简）与 WS，
> 写接口因为要登录态一直空着。本文是补上这一块之后的**实测记录**。
> 结论先行：**2C2G 上写路径饱和在 ~40 rps，且加并发只涨延迟不涨吞吐（0 个 5xx）**；
> 顺手量到一件更要紧的事——**观测栈上线后，这台机器的读基线从 608 rps 掉到了 410 rps**。

## 0. 结论速览

| 项 | 数字 | 说明 |
|---|---|---|
| 写路径饱和吞吐 | **~40 rps** | `POST /discovery/swipe`，20→200 并发在 33–39 rps 之间，不再增长 |
| 写路径延迟 | p50 **552ms @20 并发 → 4922ms @200 并发** | 线性排队，全程 0 个 5xx、0 个 429（账号额度够） |
| 单请求服务时间 | **~40ms**（单连接 25 rps / p50 30ms） | 8 个处理位理论上限 ~200 rps，实测 40 → 天花板不在线程 |
| MySQL 成本 | 每次 swipe **≈10 条查询、读 4.7 行** | 无全表扫，DB 不是瓶颈（§4.2） |
| 同机对照（20 并发） | app/config **410** · users/me **52** · candidates **23.5 rps** | 极简读仍是写路径的 10 倍以上（§3） |
| 读基线漂移 | 608 → **410 rps**（同接口/同并发/同机器） | 观测栈 5 个容器上线后下降 ~1/3（§4.3） |

## 1. 环境与方法

- 机器：阿里云轻量 **2 vCPU / 1870MB / 1024MB swap**；压测期间 `load1` 9–13，swap 已用 **514MB**。
- 同时在跑的容器（`docker ps`）：`imserver`、`observability-{prometheus,grafana,alertmanager,alert-relay,node-exporter}`
  （这 5 个**都有 mem_limit，合计上限约 344MB**）、`workbuddy2api`。
- 内存占用排序（`ps -eo rss --sort=-rss`）：**mysqld 510MB**、宝塔面板 76MB、grafana 68MB、阿里云 agent 63MB、imserver 50MB。
- 服务：nginx(80/443) → gunicorn `-w 2 --threads 4`(127.0.0.1:8000)；mysqld；Redis；celery worker。
- 压测器：`perf/run.py` **在服务器上跑、打 127.0.0.1:8000**（沿用 2026-11-01 的做法，见 `stress-test-2026-11-01.md` §1；
  注意这会让压测器与被压服务抢同一份 CPU，是个**已知的保守偏置**，两次基线口径一致）。
- 数据：
  - `seed_scale_users --count 20000`（199 号段，9.9 秒建完 2 万「资料完善 + 一张过审照片」账号）；
  - 目标池 = 前 19,000 个账号的 id；施压账号 = 后 1,000 个（`perf_tokens` 按偏移签发）；
  - **每一档并发用一批互不重叠的施压账号，并用不同的 `--i-start` 换目标区间** ——
    否则第二档会压到「已划过的幂等路径」（`get_or_create` 命中已有行），数字会虚高；
  - 压测后已清理：199 段账号 0 个、施压令牌文件删除，库内 swipe 只剩 25 条 9 月的旧数据。

## 2. 写路径基线（`POST /api/v1/discovery/swipe`）

请求体 `{"target_user_id": {i}, "action": "like"}`，`{i}` 全局自增 → 每次都是**新目标、新 INSERT**，
不是重复提交。30 秒一档。

| 并发 | RPS | p50 | p95 | p99 | 错误 | load1 峰值 |
|---|---|---|---|---|---|---|
| 20 | 33.4 | 552ms | 809ms | 970ms | 0 | 11.7 |
| 50 | 35.8 | 1212ms | 1979ms | 9716ms | 0 | 9.1 |
| 100 | 38.5 | 2004ms | 3333ms | 8675ms | 0 | 10.0 |
| 200 | 39.2 | 4922ms | 5789ms | 5910ms | 0 | 11.4 |

**读法**：并发 ×5，吞吐只从 33 涨到 39（+18%），延迟线性翻 9 倍 —— 已经饱和，
再加并发只是把人排在队里。**全程 0 个 5xx**：过载表现是慢，不是坏。
（50/100 两档 p99 出现 4–10 秒的尖刺，成因见 §4.3。）

## 3. 同机读对照（同一时段，20 并发，15 秒）

| 接口 | 有没有鉴权 / 打不打库 | RPS | p50 | p99 |
|---|---|---|---|---|
| `GET /app/config`（压测刚结束时量） | 无鉴权、无 DB | 147.1 | 103ms | 270ms |
| `GET /app/config`（清完造数、空闲复测） | 无鉴权、无 DB | **410.4** | 53ms | 155ms |
| `GET /users/me` | 鉴权 + 2–3 条 DB | 52.1 | 372ms | 593ms |
| `GET /discovery/candidates` | 鉴权 + 候选池 | 23.5 | 446ms | **9485ms** |
| `POST /discovery/swipe` | 鉴权 + 写 + 缓存版本 | 33.4 | 552ms | 970ms |

两点值得注意：

1. **写路径不比「要鉴权的读」贵多少**（33 vs 52 rps，同量级）；真正便宜的是 `/app/config` 这种
   不碰 DB 的极简接口。所以「HTTP 550–600 rps」这个老数字只对极简接口成立，别拿去推业务接口容量。
2. `GET /discovery/candidates` 在同一台机器上只有 **23.5 rps、p99 9.5 秒** ——比写路径还差，
   这是候选池路径（含缓存失效后的池查询）的老问题，值得单独查（见 §7）。

## 4. 三个发现

### 4.1 天花板是整机，不是线程数

单连接 p50 **29.7ms**（≈25 rps）是纯服务时间；8 个处理位（2 worker × 4 线程）按此推算应有
**~200 rps**，实测只有 40。压测中 `top`：两个 gunicorn worker 各 ~50% CPU、mysqld ~44%、
整机 6% idle、`load1` 到 11、`cs`（上下文切换）~7000/s。
即：**CPU 与内存一起被吃满，线程再多也没用**。要提写容量只能升配，或把单请求的 CPU 降下来。

### 4.2 MySQL 不是瓶颈

`performance_schema` 对应用账号不可读（root 口令在宝塔面板里），改用 `SHOW GLOBAL STATUS` 差值法：
351 次 swipe 期间 `Questions +3596`、`Com_select +2694`、`Com_insert +225`、`Innodb_rows_read +1641`。

- 每次 swipe **≈10.2 条查询、读 4.7 行** —— 没有全表扫、没有锁等待堆积；
- 单条查询成本极低，`mysqld` 那 44% 是「请求量大 × 每条十几条语句」堆出来的，不是某条慢 SQL。

### 4.3 内存压力：swap 在用，p99 尖刺与它同源

压测期间 `vmstat 1`：`si`（换入）≈ **1MB/s**、`bi`（块读）2–3k、`so` 偶发；
`free -m`：used **1295–1371MB / 1870MB**，swap **已用 514MB**。
4–10 秒的 p99 尖刺正好出现在这些换页窗口里 —— **不是应用逻辑抖动，是内存不够换页**。

**更要紧的副产品**：同一台机器、同一接口、同样 20 并发：

| 时间 | `GET /app/config` @20 并发 |
|---|---|
| 2026-11-01（观测栈上线前，8 个容器里只有 imserver） | 608 rps / p99 101ms |
| 2026-11-03（观测栈 5 个容器 + workbuddy2api 在跑） | **410 rps / p99 155ms** |

也就是说 **`perf/baseline.json` 里 11-01 的读点现在偏乐观约 1/3**，
拿它判「RPS −20% 即回归」会天天误报。这一条已记进计划（§7）。

至于「是谁把这 1/3 吃掉的」，我没有做逐一隔离实验，只列**已核实**的事实，不编根因：
观测栈 5 个容器合计 mem_limit 约 344MB（实际 grafana 68MB 等）、prometheus 每 15s 抓 3 个 target、
mysqld RSS **510MB**、宝塔面板 + 阿里云 agent 约 **140MB**、swap 长期占用 514MB。
要定位到具体那一个，得逐容器停掉复测——这是 §7 的第 3 条。

## 5. 口径与局限（照旧，别省略）

- **压测器与被压服务同机**：加了客户端 CPU 争用，数字偏保守；跨机器/跨日期不可比。
- 本文所有写路径数字**只与 §3 的同日同机对照比**，不与 11-01 的读点混着看。
- 合成数据 + 合成请求：20,000 个资料完善账号、每个请求目标全新、`action=like`（含反向检查）。
  真实流量的目标分布、action 比例（like/pass）会影响绝对值。
- 低并发档位要小心**单账号额度**：`swipe` 是 300/小时/用户，连接数少时某个连接可能吃满一个账号的额度
  而冒出 429（本次 20 并发首跑就撞到 44 个 429，换一批全新账号后为 0）。
- `POST /posts`（发动态 20/天/用户）没做档位：额度太低，做容量档位需要成百上千账号，
  本次只用它验证了链路与额度行为（单账号 85 次 = 20×201 后 65×429）。

## 6. 复现

```bash
# 服务器上（cwd = 仓库根）
cd chatapp
python manage.py seed_scale_users --count 20000
python manage.py perf_tokens --count 50 --start 19020 --out ../perf/results/b50.jsonl --allow-production
cd ..
python3 perf/run.py --scenario api_write --path /api/v1/discovery/swipe \
  --method POST --header 'Content-Type: application/json' \
  --body '{"target_user_id": {i}, "action": "like"}' \
  --i-start 3043 --headers-file perf/results/b50.jsonl --conns 50 --dur 30 \
  --out perf/results/write_swipe50.json

# 读对照（同一时段跑，才有可比性）
python3 perf/run.py --scenario api_read --path /api/v1/users/me \
  --headers-file perf/results/b50.jsonl --conns 20 --dur 15 --out perf/results/ref_users_me.json

# 清理
cd chatapp && python manage.py seed_scale_users --count 20000 --clean
rm -f ../perf/results/b50.jsonl
```

## 7. 后续动作（按重要性）

1. **重跑读基线**（`api_read/ws_*` 五档 + WS 三条）并把 `baseline.json` 的读点换成同一天的量；
   否则回归判定不准（计划 B 轨/C 轨都挂在这上面）。
2. **定位那 1/3**：逐容器停掉（prometheus → grafana/alertmanager → workbuddy2api）复测
   `app_config@20`，找出到底是观测栈、mysqld RSS（510MB，可调小 buffer pool 试试）还是 swap 造成的。
3. `GET /discovery/candidates` **p99 9.5 秒**单独查一次（它是发现页主路径，比写路径更可能被用户感知）。
4. 写路径的下一档优化：把每请求的 ORM 查询从 10 条往下压（`get_profile` 等已在批次内优化过一次），
   或接受 2C2G 的 40 rps 天花板并在容量口径里写明「写容量 ≈ 40 rps」。
5. B.2 余下场景：`POST /im/images`（multipart，脚本还不支持文件体）、混合 70/30 30 分钟、WS 重连风暴、0→1000 突发。
