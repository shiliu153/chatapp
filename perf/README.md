# perf:可复现的容量测试

> 目标:换台机器、改个接口,也能在 5 分钟内跑出**可对比**的数字。
> 历史报告:[docs/ops/stress-test-2026-11-01.md](../docs/ops/stress-test-2026-11-01.md)、
> [docs/ops/imserver-throughput.md](../docs/ops/imserver-throughput.md)。

## 1. 铁律:压测器不要和被压服务同机

2026-11-01 实测过:在公网侧用 `httpx` 打 400 并发,RPS 反降到 72 —— 压出来的是本机出口带宽,
不是服务器容量。所以:

- HTTP 容量测试**在服务器上跑**,打 `127.0.0.1:8000`(绕过 nginx);
- 只有验证「公网表现」时才从本地打域名,并且明确标注「不代表容量」。

## 2. 跑一个场景

### 2.1 读接口(公开,不需要登录态)

```bash
# 服务器上(cwd = 仓库根目录)
python3 perf/run.py --scenario api_read  --conns 100 --dur 30 --out perf/results/api100.json
python3 perf/run.py --scenario api_read  --conns 400 --dur 30 --out perf/results/api400.json
python3 perf/run.py --scenario api_health --conns 100 --dur 20 --out perf/results/health100.json
```

WS 场景要在 imserver 测试容器里跑(需要 MySQL/Redis 与 `IM_JWT_SECRET`):

```bash
docker compose -f imserver/docker-compose.test.yml run --rm test \
  python3 /src/../perf/run.py --scenario ws_burst --conns 500 --count 1 --out /repo/perf/results/ws500.json
```

冷启动验收(造 500 对全新配对,验证 P0-1 死锁修复)用另一个脚本:

```bash
docker compose -f imserver/docker-compose.test.yml run --rm test \
  python3 /src/scripts/bench_cold_start.py --n 500
```

### 2.2 写接口(带鉴权:swipe / 发动态)

写路径要登录态,而**写接口的限流都按用户计**(滑卡 300/小时、发动态 20/天),
单账号跑几秒就撞 429 —— 那时压出来的是限额,不是容量。所以写场景一律多账号:

```bash
# ① 造数与签令牌(在服务器上,cwd = chatapp/)
python manage.py seed_scale_users --count 1000          # 199 号段测试号(幂等)
python manage.py perf_tokens --count 50 --out ../perf/results/headers.jsonl

# ② 压滑卡:一条连接一个账号,{i} 是全局自增的目标 id
cd .. && python3 perf/run.py --scenario api_write --path /api/v1/discovery/swipe \
  --method POST --header 'Content-Type: application/json' \
  --body '{"target_user_id": {i}, "action": "like"}' --i-start 20001 \
  --headers-file perf/results/headers.jsonl --conns 50 --dur 30 \
  --out perf/results/write_swipe50.json

# ③ 压发动态(POST /posts 收表单字段 text)
python3 perf/run.py --scenario api_write --path /api/v1/posts \
  --body 'text=perf+{i}' --header 'Content-Type: application/x-www-form-urlencoded' \
  --headers-file perf/results/headers.jsonl --conns 30 --dur 30 \
  --out perf/results/write_post30.json

# ④ 令牌文件里有活令牌,跑完立刻删
rm perf/results/headers.jsonl
```

需要多少账号(粗算,`单账号额度` 见 `chatapp/config/settings.py::DEFAULT_THROTTLE_RATES`):

```
账号数 ≈ 目标 RPS × 压测时长(秒) ÷ 单账号额度
例:30 秒压到 50 rps 滑卡 ≈ 1500 次 ÷ 300/小时 → 20 个以上(留余量取 50)
```

请求头的三层合并顺序是「内置默认 → `--header` → `--headers-file` 里该连接那一套」,
后者覆盖前者(`Authorization` 大小写不敏感也能盖掉)。几点必须知道:

- **令牌不进结果文件**:`params.headers` 只记头名与头集套数,头的值绝不落盘(结果会进 git);
- `X-Forwarded-For` 只在**直连 gunicorn** 时能分散 IP 维度限流;过 nginx 时它排在真实来源
  前面,DRF 取最后一跳,不吃这个值(所以别指望从本地打域名时绕过 IP 限流);
- access 默认 **30 分钟过期**,令牌要现场签;
- `{i}` 从 `--i-start` 开始**全局自增**,路径与请求体都支持。目标 id 必须真的存在,
  否则压出来一片 404/400 —— 这不是脚本坏了,结果里的 `codes` 会明说。

## 3. 出表与回归判定

```bash
python3 perf/report.py perf/results/*.json
python3 perf/report.py perf/results/*.json --baseline perf/baseline.json
python3 perf/report.py perf/results/*.json --baseline perf/baseline.json --fail-on-regression
```

回归阈值(任一即失败,用于发版前的 smoke):

- RPS 比基线低 **20%** 以上;
- p99 比基线高 **20%** 以上;
- 错误率超过基线 **1 个百分点**。

`baseline.json` 里是 2C2G 的实测参考值,换机器、改接口、改索引后都要重跑并更新它。

## 4. 结果 JSON 的结构

```json
{
  "schema": 1,
  "scenario": "api_write",
  "started_at": "2026-11-03T20:10:00+08:00",
  "machine": {"hostname": "...", "cpu": 2, "mem_total_mb": 1870},
  "params": {"target": "127.0.0.1:8000/api/v1/discovery/swipe", "method": "POST",
             "path": "/api/v1/discovery/swipe", "conns": 50, "duration_s": 30,
             "body_bytes": 43, "body_template": true,
             "headers": {"names": ["Authorization", "Content-Type"], "sets": 50}},
  "result": {"requests": 18030, "rps": 601, "error_rate": 0.0, "codes": {"200": 18030},
             "lat_ms": {"p50": 165, "p95": 276, "p99": 329}},
  "resources": {"load1_peak": 1.8, "mem_used_mb_peak": 690}
}
```

带 `machine` 是为了让两次结果**可比**:RPS 脱离机器规格没有意义。
`params.headers` 只留头名与头集套数 —— **头的值(令牌)永不落盘**。

## 5. 场景矩阵(逐步补齐)

| 场景 | 覆盖 | 状态 |
|---|---|---|
| `api_read` | 只读接口(候选池/配置/广场 feed) | 已支持(默认 app/config,可 `--path`) |
| `api_health` | 框架开销基线 | 已支持 |
| `api_write` | 写接口(swipe / 发动态 / 点赞…) | 已支持(需 `--path` + `--header`/`--headers-file` + `--body`) |
| `ws_burst` | WS 突发/冷会话 | 已支持(委托 bench_ws) |
| `ws_steady` | 稳态消息速率与 ack 延迟 | 已支持 |
| 混合 70 读 / 30 写、30 分钟内存曲线 | — | 待补(计划 B.2 余下部分) |
| WS 重连风暴(重启后 1000 客户端同时重连) | — | 待补(B.2) |
| 规模数据(10 万用户) | 数据量增长后的 p99 | 待补(B.3) |

> **写路径的基线数字还没进 `baseline.json`**:本机(Windows + 本地 MySQL)的数字与 2C2G
> 不可比,填进去只会污染回归判定。跑法已就绪(§2.2),需在 2C2G 上实测后补点。


## 6. 与旧脚本的关系

`docs/ops/stress/*.py` 是 2026-11-01 的一次性脚本,保留作为历史证据;
新测试一律用 `perf/run.py`(统一 JSON + 机器规格 + 基线对比)。

## 7. 脚本自身的测试

压测脚本出错最坏的情况是「数字看着正常,其实压的不是它」——比如头没发出去(全 401)、
`{i}` 没替换(压的是幂等路径)、令牌写进了结果文件。所以 `perf/run.py` 有一份纯标准库自测
(起一个最小回显服务器,把真正发出去的字节抓下来看):

```bash
cd <仓库根> && python -m unittest perf.test_run -v       # 24 条,秒级,不需要任何服务
```

CI(`.github/workflows/backend.yml`)会跑这份自测;`chatapp` 侧的令牌命令由
`manage.py test accounts.tests.PerfTokensTests` 覆盖。
