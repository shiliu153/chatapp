# docs/reports/ — 一次性测量报告

这里放**某一次测量**的原始记录:环境、复现命令、原始数字、口径坑。
它们**只增不改**(发现算错就追加「勘误」段,不改历史数字),引用时**必须带日期**。

> **完整清单见 [`docs/README.md`](../README.md)**(由 `scripts/docs_index.py` 扫描生成,
> 禁止手改)。下面这张表是**精选入口**(测了什么 / 结论一句话),不承诺穷举。

> **这里不是口径页。** 「现在该按哪个数字判回归」的唯一 owner 是
> [capacity-and-reliability.md](../ops/capacity-and-reliability.md) 的数字总表;
> 本文目录下的每份报告只是它某一行的**证据**。两者冲突时以口径页为准,
> 并把口径页的日期与本节报告日期对齐后复核。

## 1. 目录

| 报告 | 日期 | 测的是什么 | 结论一句话 |
|---|---|---|---|
| [stress-test-2026-11-01.md](stress-test-2026-11-01.md) | 2026-11-01 | 高并发压测 + 「打崩自愈」演练(2C2G 线上) | **应用层能自愈,数据库层不能**;压出一个线上未暴露的冷启动死锁 |
| [imserver-throughput.md](imserver-throughput.md) | 2026-10-22 | 自建 IM 吞吐优化(1000 条突发) | 106 → **215 msg/s**,2C2G 天花板 200–250;再往上要升配或应用层批量提交 |
| [scale-report.md](scale-report.md) | 2026-11-03 | 10 万用户量级的查询表现(合成数据) | 广场列表 offset 0 **3354ms → 77ms**;剩余瓶颈是 `COUNT` 与 `OFFSET` 跳读 |
| [write-baseline-2026-11-03.md](write-baseline-2026-11-03.md) | 2026-11-03 | 写路径容量基线(`POST /discovery/swipe`) | 2C2G 饱和 **~40 rps**,加并发只涨延迟不涨吞吐(0 个 5xx) |
| [peak-shaving.md](peak-shaving.md) | 2026-11-03 | 配对通知的队列分级与限速 | 500 对同时匹配:p50 **227.9ms → 24.1ms**,p99 271 → 178.6ms |
| [read-baseline-2026-11-04.md](read-baseline-2026-11-04.md) | 2026-11-04 | 读基线重跑 + `candidates` p99 归因 + 场景矩阵补齐 | `GET /app/config` @100 并发 = **476 rps**;判回归**只用 100 并发档**(20 档噪声 ±15–30%) |
| [cache-win-2026-11-05.md](cache-win-2026-11-05.md) | 2026-11-05 | 候选池缓存开/关同负载对比 | 命中率 **97.8%** 成立;「DB QPS −60%」**不成立**(语句数只省 12%) |

## 2. 报告怎么写

1. **顶部三行元信息**:标题带日期 · 环境(机器规格) · 关联(口径页 / 前置报告)。
2. **结论先行**:第一段就给结论,不要让人翻到 §8 才知道测出了什么。
3. **可复现**:给出压测命令、造数命令、判读口径(并发档 / 时长 / 重复次数)。
4. **写清「不成立」的部分**:被证伪的原口径比新数字更重要 —— 它防止下一个人重新踩。
5. **机器可读的基线**进 `perf/baseline.json`(带 `measured_at`),本目录只放人读的长文。

## 3. 与 `perf/` 的分工

| 放哪 | 放什么 |
|---|---|
| `perf/` | **现在还在用**的压测器(`run.py` / `report.py`)、场景定义、`baseline.json` 基线值 |
| `perf/README.md` | 怎么跑、怎么判回归、判读口径 |
| `docs/reports/`(本文目录) | 跑完之后**不再改**的一次性记录:环境、原始数字、口径坑 |
| [capacity-and-reliability.md](../ops/capacity-and-reliability.md) | 从报告里提炼出的**口径**(唯一 owner) |

## 4. 历史脚本

2026-11-01 那批一次性压测脚本(`chaos_watch.sh` / `fullstack.sh` / `http_load.py` /
`oom_alloc.py` / `oom_mysql.sh` / `recover_mysql.sh` / `srv_load.py`)原本躺在**文档目录的
`stress/` 子目录**下,2026-11-14 治理第 2 节搬到了 [`scripts/stress/`](../../scripts/stress/),
**作为历史证据保留**;新压测一律用 `perf/run.py`。
