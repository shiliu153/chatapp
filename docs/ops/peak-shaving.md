# 削峰:配对通知的队列分级与限速(2026-11-03)

> 场景:一次活动/推荐位让 500 对同时匹配 → 1000 条灰条通知瞬间入队。
> 问题不在「会不会丢」,而在「瞬间灌进去会不会把 imserver 的 DB 连接池打满、把所有人的
> ack 延迟一起拖慢」。

## 1. 改造内容

| 层 | 做法 | 文件 |
|---|---|---|
| 队列分级 | `critical`(封禁/踢人/聊天权限)、`default`、`notify`(配对/评论/举报)、`bulk`(资料同步/导入) | `config/settings.py::CELERY_TASK_ROUTES` |
| 消费限速 | `notify` 类任务 `rate_limit=IM_NOTICE_RATE_PER_SEC`(默认 50/s);`critical` 不限速 | `im/tasks.py::_notice_rate_limit` |
| 可观测 | `celery_queue_depth{queue}` 指标 + 积压告警 | `config/metrics.py`、`deploy/observability/alerts.yml` |

为什么 `critical` 不能限速:封禁要立刻踢人下线,如果和配对通知排在同一条限速队列里,
「封禁生效」会被 1000 条灰条堵在后面 —— 这是安全边界,不是性能优化。

## 2. 实测:同一批 500 条通知,两种投递方式

环境:imserver 测试容器(2 核笔记本 Docker)、MySQL 8、20 线程、每条请求独立连接。
脚本:`imserver/scripts/bench_notice_burst.py`。

| 模式 | 条数 | 总耗时 | 吞吐 | p50 | p95 | p99 | 失败 |
|---|---|---|---|---|---|---|---|
| 不限速(burst) | 500 | 5.78s | 86.5/s | **227.9ms** | 260.4ms | 271.0ms | 0 |
| 限速 50/s(paced) | 500 | 10.97s | 45.6/s | **24.1ms** | 54.9ms | 178.6ms | 0 |
| 不限速(burst,3×) | 1500 | 17.88s | 83.9/s | 233.8ms | 282.8ms | 310.7ms | 0 |

**读法**:

- 两种方式**都没有失败**——imserver 不会被打挂,所以这不是「稳定性」问题,是**延迟**问题;
- 不限速时 p50 是 228ms,限速后 24ms,**差 9 倍**。原因:20 个并发请求把 imserver 的
  8 条 DB 连接池占满,请求在池上排队(`im_db_pool_wait_seconds` 会同步上涨);
- 代价是总耗时从 5.8s 拉到 11s。通知不是实时聊天,晚 5 秒到达完全可以接受;
  而**在线用户的聊天 ack** 被通知洪水拖慢,是不可接受的。

## 3. 部署

```bash
# 建议两个 worker:一个只吃 critical,一个吃其余队列(2C2G 上各 1 并发)
celery -A config worker -Q critical -c 1 -l info --pool=solo
celery -A config worker -Q default,notify,bulk -c 2 -l info --pool=solo
```

> Windows 开发机只能 `--pool=solo`;Linux 上可用默认 prefork。**两个 worker 必须指定
> 不同队列**,否则 `critical` 又会被通知堵住。

调整速率:

```ini
IM_NOTICE_RATE_PER_SEC=50   # 0 = 不限速(不推荐)
```

## 4. 怎么确认生效

1. `GET /metrics` 看 `celery_queue_depth{queue="notify"}`:突发后应快速上升再线性下降,
   而不是长时间堆在高位;
2. `im_db_pool_wait_seconds` 在突发期间应保持低位(限速生效的直接证据);
3. 告警 `CeleryQueueBacklog`(`notify`/`bulk` 积压 > 1000 持续 10 分钟)触发时,
   先看是不是 worker 挂了,再考虑临时提高 `IM_NOTICE_RATE_PER_SEC`。

## 5. 局限

- 实测在笔记本容器上,**绝对值不可搬到 2C2G**;可迁移的是「限速把 p50 从 200ms 级
  压到 20ms 级」这个相对结论;
- 限速是 worker 侧的令牌桶(Celery `rate_limit`),**每个 worker 进程各有一份**;
  开两个 notify worker 时实际速率是 2× 配置值。要全局精确限速需要把令牌桶放到 Redis,
  当前规模不值得。
- 没做「队列满则拒绝入队」的背压:通知类任务丢了就真的丢了,延迟入队比丢弃安全。
  真正需要背压的是用户主动触发的写接口,那里已有 429 + `Retry-After`。
