# 可观测性:指标、看板与告警

> 目标:回答「系统现在好不好」——不靠登录服务器 `curl readyz`,而是看板 + 推送告警。
> 配套:[runbook.md](runbook.md)(告警处置)、[stress-test-2026-11-01.md](stress-test-2026-11-01.md)(容量基线)。

## 1. 架构

```
gunicorn :8000 /metrics ─┐
imserver :9101 /metrics ─┼─> Prometheus :9090 ─> Grafana :3000(仅回环)
node_exporter :9105 ─────┤         │
mysql_exporter :9104 ────┤         └─> Alertmanager :9093
redis_exporter :9121 ────┤                       │  POST /alert(JSON)
celery_exporter :9808 ───┘(systemd)              ▼
                                    alert-relay :9099(systemd,宿主机)
                                                 │  调 /opt/notify/bin/notify
                                                 ▼
                                     邮件(阿里云邮件推送,与 22:00 服务器日报同一条链路)
```

- 抓取全部走 **127.0.0.1**,不经过 nginx;`/metrics` 在 nginx 上被显式 `return 404`。
- Django 的 `/metrics` 需要 `METRICS_TOKEN`(nginx 反代后 `REMOTE_ADDR` 恒为 127.0.0.1,
  回环判断挡不住公网);imserver 的 `/metrics` 与 `/internal/*` 同口径,只认回环。
- **告警通道 2026-11-05 换过**(E-4 ①):原来规划「Alertmanager → 容器 relay → 企业微信群机器人」,
  但机器人地址一直没配,告警只落日志 = 没人看得到。用户决定**不再接群机器人**,改用每天 22:00
  服务器日报那条邮件链路(`/opt/notify`,阿里云邮件推送)。因为发信要读 `/opt/notify`、
  `/etc/notify/env` 与 `~/.local/state/notify`,`alert-relay` 从容器改成了**宿主机 systemd 服务**。
  `celery-exporter` 同理(镜像拉不动),也是 systemd。
- 资源预算(2C2G):Prometheus 160 + Grafana 96 + Alertmanager 32 + node_exporter 24
  + mysqld/redis exporter 各 32 = **376MB 容器上限(实测约 190MB)**;
  两个 systemd 服务各限 64/128MB(实测 relay ≈20MB、celery-exporter ≈55MB)。
  日志栈(Loki 128MB + Promtail 48MB)仍是可选的 `logs` profile。
  2G 机器经不起任何一项偷偷膨胀,所以**实测涨到上限一半以上就去 runbook §3 找它**。

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

### 2.1 告警邮件通道(2026-11-05,E-4 ①)

告警不再走群机器人,复用每天 22:00 服务器日报那条邮件链路。要装三样东西:

```bash
# 1) 告警专用 notify 配置(与日报共用发信账号/配额/去重库,只是主题前缀不同)
#    先把模板里的 <收件邮箱>/<发信地址> 换成日报那份的值(见 /root/.config/notify/config.ini)
install -m 600 deploy/observability/notify-alerts.ini.tmpl /etc/notify/alerts.ini

# 2) 中转脚本 + systemd 单元(不再用容器,理由见文件头注释)
install -m 755 deploy/observability/alert_relay.py /www/server/observability/alert_relay.py
install -m 644 deploy/observability/alert-relay.service /etc/systemd/system/chatapp-alert-relay.service
systemctl daemon-reload && systemctl enable --now chatapp-alert-relay
systemctl status chatapp-alert-relay --no-pager    # 期望 active (running)

# 3) 告警配置改指新 receiver 后重建 Alertmanager
cd /www/server/observability && docker compose up -d alertmanager
```

验证(不制造真实宕机)——往 Alertmanager 打一条合成告警,几十秒内应收到邮件:

```bash
curl -s -XPOST 127.0.0.1:9093/api/v2/alerts -H 'Content-Type: application/json' -d '[{
  "labels": {"alertname": "SyntheticProbe", "severity": "warning"},
  "annotations": {"summary": "链路自检", "description": "来自 runbook 的合成告警"}}]'
journalctl -u chatapp-alert-relay -n 20 --no-pager   # 或 tail /www/wwwlogs/alert-relay.log
/opt/notify/bin/notify log -n 5                      # notify 自己的发送记录
```

要点与边界:

- **去重与限流归 notify**:`--dedup-key` = Alertmanager 的 `groupKey + status`,同一组告警触发只发
  一封、恢复再发一封;`--dedup-window 60` 分钟兜住「同组反复进出」。配额是日报那份的
  **5 封/分钟、50 封/天**,告警风暴会撞上限(那时优先级判断交给人,不要调大配额掩盖问题)。
- **发信失败返回 500**,Alertmanager 按自己的指数退避重试;不要在这个脚本里再写一套重试。
- **邮件不等于手机推送**:邮件到手机最坏延迟取决于邮箱客户端;这是「不接群机器人」的既定代价。
- 探针(`probe-readyz.sh`)走同一条邮件链路,见 §2.2。

### 2.2 三个 exporter 与探针 30s(2026-11-05,E-4 ②④)

```bash
# 1) MySQL:用应用账号跑(exporter 只读)。口令文件 640 且属组 65534,容器内以 nobody 读。
cd /www/server/observability
U=$(grep '^DB_USER=' /www/wwwroot/chatapp/chatapp/.env | cut -d= -f2)
P=$(grep '^DB_PASSWORD=' /www/wwwroot/chatapp/chatapp/.env | cut -d= -f2)
printf '[client]\nuser=%s\npassword=%s\nhost=127.0.0.1\nport=3306\n' "$U" "$P" > mysqld_exporter.cnf
chown root:65534 mysqld_exporter.cnf && chmod 640 mysqld_exporter.cnf

# 2) 两个容器 exporter
docker compose up -d mysqld-exporter redis-exporter

# 3) Celery exporter 走 PyPI 包 + systemd(镜像拉不动,原因见文件头)
python3.11 -m venv /opt/celery-exporter-venv
/opt/celery-exporter-venv/bin/pip install prometheus-exporter-celery "redis>=6.1.0" packaging
install -m 644 deploy/observability/celery_exporter_run.py /www/server/observability/
install -m 644 deploy/observability/celery-exporter.service /etc/systemd/system/chatapp-celery-exporter.service
systemctl daemon-reload && systemctl enable --now chatapp-celery-exporter

# 4) Celery 事件开关:settings.py 里 CELERY_WORKER_SEND_TASK_EVENTS=True 之后必须重启 worker,
#    否则 exporter 只能给出队列长度,任务级指标全空。
supervisorctl -c /etc/supervisor/supervisord.conf restart "chatapp-celery:*"

# 5) 探针改 30s 粒度 + 邮件通知
install -m 755 imserver/deploy/probe-readyz.sh /www/server/imserver/probe-readyz.sh
# 宝塔计划任务仍是「每分钟」调用;脚本内部先查所有目标、失败隔 30s 再复测一次,
# 因此单次故障 30~35 秒内就能发信。目标清单默认 imserver readyz + Django health。
```

坑与注意事项:

1. **celery-exporter 没有 Docker 版本可选**:`danihodovic/celery-exporter` 不在 daocloud 的
   公共镜像白名单(`this image is not in the allowlist`),直连 Docker Hub 实测 ~18KB/s。
   改走 PyPI(阿里云镜像)+ systemd;它本身只是个 Flask + waitress 进程,行为一致。
2. **两个 Python 依赖坑**:包元数据写着 `redis<6`,但 celery 5.6 的 kombu 要求
   `redis-py>=6.1`(否则启动即 `VersionMismatch`);另外它没把 `packaging` 写进依赖。
   所以安装命令必须显式带上这两项(见上面第 3 步)。
3. **mysqld_exporter 用应用账号**:没有 `PROCESS` / `REPLICATION CLIENT`,所以关掉了
   `slave_status` 与 `info_schema.processlist` 两个 scraper(否则每次抓取都刷「Access denied」)。
   要开就得建监控账号并授权:`GRANT PROCESS, REPLICATION CLIENT ON *.* TO ...`。
4. 口令文件读不到时 exporter 报 `Error parsing host config ... permission denied` ——
   不是口令错,是权限(容器内 nobody 要能读,`chown root:65534` + `640`)。
5. **celery 的队列长度标签是 `queue_name`**,不是 `queue`(我们自己在 Django 侧抓的
   `celery_queue_depth` 用的是 `queue`)。写告警/看板时别混。
6. **探针请求必须带 `X-Forwarded-Proto: https`**:Django 配了 `SECURE_SSL_REDIRECT`,
   直连 `127.0.0.1:8000` 的 http 请求会被 **301**,探针会把「301」当成不健康(踩过一次)。

### 2.3 gunicorn 多 worker 的指标口径(2026-11-05 复查补的既有缺陷)

现网 gunicorn 是 `-w 2 --threads 4`。`prometheus_client` 的计数器默认**进程内**,
所以每个 worker 各记一份,而 Prometheus 每次抓取只落在其中一个 worker 上 ——
实测打 20 次 `/api/v1/health` 后,两个 worker 分别记到 **10 / 12**,抓取结果在两者之间跳,
`rate()` 还会把「另一个 worker 的数更小」当成计数器重置。业务指标更严重:一半事件根本抓不到。

修法是官方方案(已随 E-4 落地):

```bash
# 1) .env 里开多进程目录(tmpfs,不占磁盘)
echo 'PROMETHEUS_MULTIPROC_DIR=/dev/shm/chatapp-prometheus' >> /www/wwwroot/chatapp/chatapp/.env

# 2) supervisor 的 gunicorn 命令加 -c gunicorn.conf.py(仓库内 chatapp/gunicorn.conf.py)
#    宝塔:面板「进程守护」里改命令,或直接改两处配置文件后 reload:
#    /www/server/panel/plugin/supervisor/profile/chatapp-web.ini
#    /www/server/panel/plugin/supervisor/config.json   (面板 UI 读这份,两份要一起改)
#    command=/www/wwwroot/chatapp-venv/bin/gunicorn config.wsgi:application \
#            -c gunicorn.conf.py -b 127.0.0.1:8000 -w 2 --threads 4 --timeout 120

# 3) 重启后验证:连续打 N 次接口,再连抓两次 /metrics,计数应该一次到位、不再跳
```

- `chatapp/gunicorn.conf.py` 干两件生命周期的事:master 启动前清空残留的 `*.db`
  (被 `kill -9` 过的 worker 会留下文件,不清就一直参与合计),worker 退出时
  `mark_process_dead` 删掉自己的文件。
- 命令行里的 `-b / -w / --threads` 优先级高于配置文件,不会被覆盖。
- 合并失败(目录被删/权限变化)时 `render()` 会**退回本进程视图**并记一次
  `cache_errors_total{name="metrics_multiprocess"}` —— 抓取宁可少几个数,也不能返回 500。



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
| `client_errors_total{platform}` | counter | **前端上报的未捕获异常**(Web / App);服务端 5xx 看不见白屏与崩溃,这个计数是唯一入口 |
| `logins_total{result}` | counter | 登录成功 / 被拒(白名单、验证码、锁定、运营账号)。**2026-11-05 新增** |
| `swipes_total{action}` | counter | 滑卡 like / pass;按「实际生效的动作」计数,幂等重放不重复算 |
| `matches_total` | counter | 新增配对数(软删除的旧行被复用不算) |
| `im_calls_total{endpoint,result}` | counter | **Django 这一侧**调 imserver 内部 API 的次数与成败。imserver 的 `im_sends_total` 看不到「Django 根本没发出请求」 |
| `cache_hits_total` / `cache_misses_total` / `cache_errors_total{name}` | counter | 候选池缓存命中率,是「加缓存到底有没有用」的唯一证据 |
| `celery_task_{succeeded,failed,retried}_total{name}` / `celery_worker_up` / `celery_queue_length` | counter / gauge | celery-exporter;**空指标**说明 Django 没开 `CELERY_WORKER_SEND_TASK_EVENTS` 或 worker 没重启 |
| `mysql_up` / `mysql_global_status_threads_connected` / `mysql_global_status_queries` / `mysql_global_variables_max_connections` | gauge / counter | mysqld_exporter;连接上限现网 500 |
| `redis_up` / `redis_connected_clients` / `redis_memory_used_bytes` | gauge | redis_exporter |
| `node_*` | — | CPU / 内存 / 磁盘(磁盘告警 >85% 使用) |

> 业务指标一律**不加用户 id / 手机号 / 目标 id**:基数会随用户数线性膨胀。口径固定为
> 「每分钟发生了几次」,人数与留存属于产品分析,不在 Prometheus 里做。

## 4. 告警与处置

| 告警 | 阈值 | 先做什么 |
|---|---|---|
| `ApiHighErrorRate` | 5xx >1% 持续 2m | 看 route 标签定位接口 → `request_id` 查日志 |
| `ApiSlowP99` | p99 >500ms 持续 5m | 看「各路由 p99」面板 → MySQL 慢查询 / 连接数 |
| `ApiInflightSaturated` | inflight >20 持续 3m | 是否有慢查询或外部依赖卡住 |
| `ApiDown` | `up{job="api"}=0` 持续 30s | **最急的一条**:`supervisorctl status 'chatapp-web:*'`,supervisor 会拉起,但用户此时看到的是 502 |
| `ImDown` | `up{job="im"}=0` 1m | `curl :9101/internal/readyz`;503=DB/Redis,000=进程 |
| `ImDeadlockRetries` | 10m 内有增长 | 查是否冷启动并发建会话(见 stress 文档 P0-1) |
| `ImSendFailureRate` | >5% 持续 2m | 先看 imserver 日志 `send_failed` 的 error 字段 |
| `ImDbPoolWait` | >50ms 持续 5m | 池打满;查慢 SQL 或调 `IM_DB_POOL` |
| `CeleryQueueBacklog` | notify/bulk 积压 >1000 持续 10m | 先看 worker 是否存活,再看限速是否过低 |
| `CeleryWorkerDown` | 在线 worker <1 持续 5m | `supervisorctl status 'chatapp-celery:*'`;顺带确认事件开关 |
| `CeleryTaskFailures` | 10m 内失败 ≥3 | 按 `name` 定位任务;`im.tasks.*` 失败多半是 imserver 不可达或配对不存在(40302) |
| `MysqlDown` | `mysql_up=0` 持续 1m | `/etc/init.d/mysqld status`、`tail /www/wwwlogs/mysql_watchdog.log` |
| `MysqlConnectionsHigh` | 连接数 >100 持续 5m | 上限 500;先查连接泄漏与慢查询 |
| `RedisDown` | `redis_up=0` 持续 1m | 验证码/限流/缓存/broker 全在 Redis;挂了表现为「收不到码 + 队列不动」 |
| `ExporterDown` | `up{job=~"celery\|mysql\|redis"}=0` 持续 5m | 指标盲区本身也要告警,否则「没告警」会被误读成「没事」 |
| `DiskAlmostFull` | 可用 <15% | `media_cleanup --apply`、`media_disk_report` |
| `MemoryPressure` | 使用 >90% | 2G 机器会触发 OOM Killer;先杀压测/排查泄漏 |

全部告警经 Alertmanager → `alert-relay`(systemd)→ `/opt/notify` → 邮件,见 §2.1。
完整处置顺序见 [runbook.md](runbook.md) §3。


### 前端错误上报(2026-11-03)

白屏、JS 运行时异常、Flutter 崩溃**不会**出现在 `http_requests_total` 里 —— 用户不刷新就没人知道
(审查 N-7)。链路是自建的,零第三方成本:

```
Web: window.onerror / unhandledrejection / Vue errorHandler
App: FlutterError.onError / PlatformDispatcher.onError
        └─→ POST /api/v1/client-errors（匿名可调,120 次/小时/IP）
              ├─→ 单行 JSON 日志 logger=chatapp.client_error,**level=warning**
              │    （request_id / platform / client_route / client_stack / app_version）
              │    **同一 platform+message 60 秒采样**,且**不参与告警**
              └─→ client_errors_total{platform}  ← 告警只看这个
```

- **开关**:Web 构建期 `VITE_ERROR_REPORTING=1`(`web/.env.production` 已开,开发/测试为 `0`);
  App `--dart-define=ERROR_REPORTING=true`。**未开时监听根本不安装**,零开销。
- **查错顺序**:Grafana `client_errors_total` 突增 → Loki 查 `{logger="chatapp.client_error"}`
  按 `client_route` 分组 → 用该条的 `request_id`(或 `client_request_id`)对齐服务端那条请求日志。
- **日志级别是 `warning`,不是 `error`(2026-11-08,R4-E2)**:匿名接口能写 `error` 级日志,
  等于把「日志污染 → 触发告警」的开口直接交给互联网。级别只为在 Loki 里好筛,
  **告警一律不挂在这一行日志上** —— 前端一个渲染循环一秒能刷几十条,接进告警只会制造噪音。
  **若仓库外(服务器上的 `rules/*.yml`)还有按 `level=error` 或 `client_error` 匹配的规则,
  改成 `level=warning`,或者干脆删掉这条规则**;要监控白屏/崩溃,只看下面的指标。
- **日志采样:同一 `platform + message` 60 秒只落一条**(`cache.add` 控制,Redis 挂了则
  fail-open 照常写)。采样**只影响日志**,`client_errors_total{platform}` 仍每次请求都累加 ——
  否则突增告警的数值会随采样率一起失真。查「某个错误到底报了多少次」看指标,不看日志条数。
- **限流与配额**:客户端每页面/进程最多 20 条、同 message 去重;服务端按 IP 120 次/小时
  (`CLIENT_ERROR_RATE`),避免「渲染循环抛异常」把自己打成 DDoS。
- **`client_route` 只含 pathname**(2026-11-08,R4-E3):Web 侧上报前把 `location.search`
  剥掉(`web/src/api/clientErrors.ts`),分享码之类参数不会进日志;App 侧 `route` 由调用方传入,
  **同样只传路由路径、别拼 query**(`ErrorReporter.report(route: ...)`)。


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

测试覆盖:`config.tests.MetricsTests`(路由模板打标签、令牌、回环 404、抓取自身不计数)、
`config.tests.MetricsRenderTests`(多进程开关、合并失败降级)、
`config.tests.BusinessMetricTests`(登录/滑卡/配对/IM 调用的增量)、
`deploy/observability/test_alert_relay.py`(告警载荷渲染、去重键、HTTP 入口、发信失败收敛;CI 的 contract 轨会跑)。

## 8. 上线记录(2026-11-05,E-4)

| 步骤 | 结果 |
|---|---|
| 代码 | 服务器 `master` `74f920f1` → **`630cd3ba`**(PR #65/#66/#67) |
| 容器 | 6 个:prometheus / alertmanager / grafana / node-exporter / mysqld-exporter / redis-exporter(**新增 2 个**;旧的 alert-relay 容器已删除) |
| systemd | `chatapp-alert-relay`(≈10MB)、`chatapp-celery-exporter`(≈20MB) |
| 抓取 | 6 个 target 全 `up`(api / im / node / celery / mysql / redis) |
| 规则 | **17 条**告警加载,`promtool check rules` SUCCESS |
| 看板 | 12 块(新增业务漏斗、Celery、缓存命中率与 IM 失败率、MySQL/Redis 读数) |
| 告警链路 | 合成告警 `SyntheticProbe` → relay → 邮件到达(relay 日志 `email:directmail ok`);恢复后再发一封 |
| 探针 | 手动跑 `exit=0`(31ms);上线首小时的 301 假故障已修(见 §2.2 第 6 条) |
| 多进程指标 | `.env` 加 `PROMETHEUS_MULTIPROC_DIR` + supervisor 命令加 `-c gunicorn.conf.py`;实测连打 8 次后连续两次抓取同为 10 |
| 资源 | 容器合计 ≈150MB 实测(上限 376MB);systemd 两个服务 ≈30MB;整机 used 1400MB / available 470MB(swap 570MB,压测遗留) |

上线后复查发现并修掉的两个问题(都记在 backlog E-4 的完成note里):**gunicorn 多 worker 指标分裂**、
**探针把 Django 的 301 当不健康**。两条都是「看着绿的,其实不准」,只有真的去对数字才会发现。

