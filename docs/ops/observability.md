# 可观测性:指标、看板与告警

> 目标:回答「系统现在好不好」——不靠登录服务器 `curl readyz`,而是看板 + 推送告警。
> 配套:[runbook.md](runbook.md)(告警处置)、[stress-test-2026-11-01.md](stress-test-2026-11-01.md)(容量基线)。

## 1. 架构

```
gunicorn :8000 /metrics ─┐
imserver :9101 /metrics ─┼─> Prometheus :9090 ─> Grafana :3000(仅回环)
node_exporter :9105 ─────┘         │
                                   └─> Alertmanager :9093 ─> alert-relay :9099 ─> 企业微信机器人
```

- 抓取全部走 **127.0.0.1**,不经过 nginx;`/metrics` 在 nginx 上被显式 `return 404`。
- Django 的 `/metrics` 需要 `METRICS_TOKEN`(nginx 反代后 `REMOTE_ADDR` 恒为 127.0.0.1,
  回环判断挡不住公网);imserver 的 `/metrics` 与 `/internal/*` 同口径,只认回环。
- 资源预算(2C2G):Prometheus 160MB + Grafana 96MB + Alertmanager 32MB + relay 32MB + node_exporter 24MB,
  合计约 **350MB**;日志栈(Loki 128MB + Promtail 48MB)是可选的 `logs` profile,再加约 176MB。
  全部按容器 `mem_limit` 限制。

## 2. 部署

**已于 2026-11-03 上线**(`/www/server/observability`)。完整步骤与踩过的坑:

```bash
# 1) 生成抓取令牌(生产必须;不配则 /metrics 只对回环开放)
TOKEN=$(openssl rand -hex 24)
echo "METRICS_TOKEN=$TOKEN" >> /www/wwwroot/chatapp/chatapp/.env

# 2) 拷贝栈并写令牌
mkdir -p /www/server/observability
scp -r deploy/observability/* root@<SERVER_IP>:/www/server/observability/
cd /www/server/observability
printf '%s' "$TOKEN" > metrics_token          # 不要换行,Prometheus 会原样当 token
chown 65534:65534 metrics_token && chmod 640 metrics_token   # 容器内以 nobody 读
chmod -R a+rX grafana                        # 否则 Grafana 读不到 provisioning,看板不加载

# 3) 国内服务器拉不到 Docker Hub 时用镜像站
cp docker-compose.mirror.yml docker-compose.override.yml

# 4) 拉起
docker compose up -d

# 5) 重启 gunicorn 让 METRICS_TOKEN / LOG_FORMAT 生效
/www/server/panel/pyenv/bin/supervisorctl -c /etc/supervisor/supervisord.conf \
  restart "chatapp-web:*" "chatapp-celery:*"

# 6) 验证
curl -s -H "X-Metrics-Token: $TOKEN" http://127.0.0.1:8000/metrics | head -5
curl -s http://127.0.0.1:9101/metrics | head -5
curl -s "http://127.0.0.1:9090/api/v1/targets" | python3 -m json.tool | grep health
curl -s -o /dev/null -w '%{http_code}\n' https://<DOMAIN>/metrics   # 期望 404
```

**三个上线时踩到的坑**(都已在仓库里修好):

1. `/metrics` 被 `SecurityMiddleware` 301 到 https,Prometheus 跟随重定向后对 8000 做 TLS 握手失败
   → Django 侧加 `SECURE_REDIRECT_EXEMPT = [r"^metrics$"]`(`scrape_config` 不支持自定义 headers)。
2. Prometheus 容器以 `nobody` 读令牌 → `chown 65534:65534 && chmod 640`。
3. Grafana 读不到 provisioning 目录 → `chmod -R a+rX grafana`,否则看板列表为空。

Grafana 只监听回环,本机看板用 SSH 隧道:

```bash
ssh -L 3000:127.0.0.1:3000 root@<SERVER_IP>   # 然后浏览器打开 http://127.0.0.1:3000
```

首次登录 `admin/admin`,立即改密码;数据源与看板由 `grafana/provisioning` 自动加载。

## 3. 指标清单

| 指标 | 类型 | 含义 / 怎么用 |
|---|---|---|
| `http_requests_total{method,route,status}` | counter | 按**路由模板**聚合(不是真实路径,基数可控);算 QPS 与错误率 |
| `http_request_duration_seconds{method,route}` | histogram | p50/p95/p99;桶 5ms–5s |
| `http_inflight` | gauge | 在途请求;持续 >20 说明 8 个工作位排满 |
| `im_connections` | gauge | 在线 WS 连接数 |
| `im_sends_total{result}` | counter | 发送成功/失败;失败率是 IM 最直接的 SLO |
| `im_deadlock_retries_total` | counter | 1213/1205 重试次数;增长说明又出现锁冲突 |
| `im_db_pool_wait_seconds` / `im_db_pool_waits_total` | gauge / counter | 取连接平均等待;DB 瓶颈的早期信号 |
| `celery_queue_depth{queue}` | gauge | 各队列积压;抓取时从 broker 实时读 |
| `node_*` | — | CPU / 内存 / 磁盘(磁盘告警 >85% 使用) |

## 4. 告警与处置

| 告警 | 阈值 | 先做什么 |
|---|---|---|
| `ApiHighErrorRate` | 5xx >1% 持续 2m | 看 route 标签定位接口 → `request_id` 查日志 |
| `ApiSlowP99` | p99 >500ms 持续 5m | 看「各路由 p99」面板 → MySQL 慢查询 / 连接数 |
| `ApiInflightSaturated` | inflight >20 持续 3m | 是否有慢查询或外部依赖卡住 |
| `ImDown` | `up{job="im"}=0` 1m | `curl :9101/internal/readyz`;503=DB/Redis,000=进程 |
| `ImDeadlockRetries` | 10m 内有增长 | 查是否冷启动并发建会话(见 stress 文档 P0-1) |
| `ImSendFailureRate` | >5% 持续 2m | 先看 imserver 日志 `send_failed` 的 error 字段 |
| `ImDbPoolWait` | >50ms 持续 5m | 池打满;查慢 SQL 或调 `IM_DB_POOL` |
| `CeleryQueueBacklog` | notify/bulk 积压 >1000 持续 10m | 先看 worker 是否存活,再看限速是否过低 |
| `DiskAlmostFull` | 可用 <15% | `media_cleanup --apply`、`media_disk_report` |
| `MemoryPressure` | 使用 >90% | 2G 机器会触发 OOM Killer;先杀压测/排查泄漏 |

完整处置顺序见 [runbook.md](runbook.md) §3。

## 5. SLO(先定口径,再谈达标)

| 指标 | 目标 | 口径 |
|---|---|---|
| API 可用性 | 99.5%/月 | 非 5xx 请求占比(排除 4xx 客户端错误) |
| API 延迟 | p99 < 300ms @ 100 并发 | 2C2G 基线下 100 并发 p99 329ms,加缓存后应达标 |
| IM ack | p99 < 200ms @ 稳态 50 msg/s | 2026-10-22 实测 93ms,有余量 |
| IM 发送成功率 | >99.9% | `im_sends_total{result="failed"}` 占比 |

> 这些数字来自 `docs/ops/stress-test-2026-11-01.md` 与 `docs/ops/imserver-throughput.md`,
> 改完缓存/削峰后需要重跑基线并回填(见整改方案 B 轨)。

## 6. 日志(可选 profile: logs)

生产把日志切成单行 JSON,Loki 才能按 `request_id` / `user_id` / `route` 检索:

```bash
# 1) Django 侧:改 .env 后重启 gunicorn
LOG_FORMAT=json        # 默认 text;字段白名单见 config/logging.py
LOG_FILE=/www/wwwlogs/chatapp.log   # 同时落盘,promtail 才读得到

# 2) 启动日志栈(Loki + Promtail,约 176MB)
cd /www/server/observability
docker compose --profile logs up -d
```

`promtail.yml` 默认收 `/www/wwwlogs/*.log`;若 gunicorn 由 supervisor 写到别处,改
`__path__` 即可。日志保留 7 天(`loki.yml` 的 `retention_period`)。

Grafana → Explore → 选 Loki,常用查询:

```logql
{job="chatapp"} | json | request_id="<从错误响应里拿到的 id>"
{job="chatapp"} | json | status >= 500
{job="chatapp"} | json | duration_ms > 500
```

> 请求日志自带 `status` / `route` / `duration_ms`(慢请求自动升 WARNING);
> `sql_count` 只在 `DEBUG=1` 下采集,生产不开。

## 7. 本地开发

```bash
cd chatapp && python manage.py runserver 127.0.0.1:8000
curl -s http://127.0.0.1:8000/metrics | head        # 未配 METRICS_TOKEN 时回环可抓
```

测试覆盖:`config.tests.MetricsTests`(路由模板打标签、令牌、回环 404、抓取自身不计数)。
