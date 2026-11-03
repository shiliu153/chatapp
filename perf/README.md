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
  "scenario": "api_read",
  "started_at": "2026-11-02T18:40:00+08:00",
  "machine": {"hostname": "...", "cpu": 2, "mem_total_mb": 1870},
  "params": {"target": "127.0.0.1:8000/api/v1/app/config", "conns": 100, "duration_s": 30},
  "result": {"requests": 18030, "rps": 601, "error_rate": 0.0, "codes": {"200": 18030},
             "lat_ms": {"p50": 165, "p95": 276, "p99": 329}},
  "resources": {"load1_peak": 1.8, "mem_used_mb_peak": 690}
}
```

带 `machine` 是为了让两次结果**可比**:RPS 脱离机器规格没有意义。

## 5. 场景矩阵(逐步补齐)

| 场景 | 覆盖 | 状态 |
|---|---|---|
| `api_read` | 只读接口(候选池/配置/广场 feed) | 已支持(默认 app/config,可 `--path`) |
| `api_health` | 框架开销基线 | 已支持 |
| `ws_burst` | WS 突发/冷会话 | 已支持(委托 bench_ws) |
| `ws_steady` | 稳态消息速率与 ack 延迟 | 已支持 |
| 写场景(swipe/post) | 需要登录态与造数 | 待补(依赖 C 轨的造数脚本) |
| 规模数据(10 万用户) | 数据量增长后的 p99 | 待补(B.3) |

## 6. 与旧脚本的关系

`docs/ops/stress/*.py` 是 2026-11-01 的一次性脚本,保留作为历史证据;
新测试一律用 `perf/run.py`(统一 JSON + 机器规格 + 基线对比)。
