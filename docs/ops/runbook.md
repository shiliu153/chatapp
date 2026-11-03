# 运维手册:告警处置与故障恢复

> 配套:`docs/ops/stress-test-2026-11-01.md`(自愈矩阵实测)、`docs/ops/imserver.md`(部署与探针)。
> 目标:任何一条告警都能在 1 分钟内定位到「看哪块板 → 做什么」。

## 1. 探针与告警通道

| 探针 | 频率 | 失败判定 | 通知 |
|---|---|---|---|
| `imserver /internal/readyz` | 30s | 连续 2 次非 200 | 企业微信机器人(`PROBE_WEBHOOK`) |
| `GET /api/v1/health` | 30s | 同上 | 同上 |
| MySQL 3306 探活 | 60s | 一次失败即拉起 | 看门狗脚本 + 机器人 |
| 磁盘/内存 | 5min | 磁盘 >85%、可用内存 <100MB | 同上 |

> 2026-11-01 之前的探针是「每分钟一次、连续 2 轮才 ALERT」,实测 90 秒宕机只记 1 次失败、
> 没有告警。改成 30s 一次后,单次故障也能在 60 秒内触达。

## 2. MySQL 看门狗(P0-2)

### 2.1 为什么需要

现网 `mysqld` 由 `mysqld_safe` 托管,systemd unit 是 sysv 生成的、`Restart=no`。
2026-11-01 实测:同时 `kill -9 mysqld` 与 `mysqld_safe` 后**没有任何东西拉起**,
数据库永久宕机,只能人工 `/etc/init.d/mysqld start`。

### 2.2 安装(二选一,可同时做)

**A. 有真正的 systemd unit 时**(`systemctl list-unit-files mysqld.service` 有输出):

```bash
mkdir -p /etc/systemd/system/mysqld.service.d
cp deploy/ops/mysql-restart-always.conf /etc/systemd/system/mysqld.service.d/
systemctl daemon-reload
systemctl show mysqld -p Restart   # 应输出 Restart=always
```

**B. 宝塔 / mysqld_safe 形态(现网)**:每分钟 cron 兜底。

```bash
install -m 755 deploy/ops/mysql-watchdog.sh /www/server/ops/mysql-watchdog.sh
# probe.env 里已有的机器人地址直接复用
grep -q PROBE_WEBHOOK /www/server/ops/probe.env && \
  echo 'PROBE_WEBHOOK=<机器人地址>' >> /etc/default/mysql-watchdog
echo '* * * * * root set -a; . /etc/default/mysql-watchdog; set +a; /www/server/ops/mysql-watchdog.sh >> /www/wwwlogs/mysql_watchdog.log 2>&1' \
  > /etc/cron.d/mysql-watchdog
```

验证(会短暂中断 DB,低峰期做):

```bash
kill -9 $(pgrep -x mysqld) $(pgrep -f "^/bin/sh /www/server/mysql/bin/mysqld_safe")
sleep 90
mysql -e 'SELECT 1' && tail -5 /www/wwwlogs/mysql_watchdog.log
# 期望:日志出现 "restarted successfully",机器人收到一条「曾宕机,已拉起」
```

### 2.3 注意

- 看门狗用 `flock` 防重入,恢复动作未结束时会跳过本轮。
- 拉起失败只告警一次(状态文件 `/var/lib/mysql-watchdog/down`),避免每分钟刷屏;
  恢复后自动清状态并补一条恢复通知。
- 脚本默认读 `/root/.my.im.cnf`(现网已有),可用 `MYSQL_CNF` 覆盖。

## 3. 故障处置顺序

全栈同时打崩时(2026-11-01 实测 111s),按依赖顺序恢复,不要同时重启:

1. **MySQL** → `mysql -e 'SELECT 1'` 通过再进行下一步(看门狗会自动做,失败才人工)。
2. **imserver** → `curl -s -o /dev/null -w '%{http_code}' 127.0.0.1:9101/internal/readyz`,
   期望 200;若容器 crash loop,`docker logs --tail 50 imserver` 看是否 DB 未就绪。
3. **Django(gunicorn)** → `supervisorctl status chatapp-web`,期望 RUNNING;
   进程在但 502 时看 `supervisorctl tail chatapp-web`。
4. **nginx** → `nginx -t && systemctl reload nginx`。

## 4. 常见告警对照表

| 告警 | 先看 | 常见原因 | 处置 |
|---|---|---|---|
| `readyz` 连续失败 | `docker logs imserver` | MySQL 不可达 / 池连接全死 | 先修 DB;池有 idle ping,DB 恢复后自动重连 |
| API 5xx >1% | gunicorn 日志 + `request_id` | DB 宕机、代码异常 | 用 `request_id` 在日志里定位单条请求;未预期异常现在返回 JSON 500 并带堆栈 |
| API p99 >500ms | MySQL 慢查询、连接数 | 慢 SQL、连接池打满 | `SHOW FULL PROCESSLIST`;必要时限流 |
| Celery 积压 | `celery_queue_depth` 面板 + worker 日志 | worker 挂了 / 限速过低 | 重启 worker;队列分级与限速见 [peak-shaving.md](peak-shaving.md) |
| 磁盘 >85% | `du -sh /www/wwwroot/*` | 聊天图片/语音堆积 | `python manage.py media_cleanup --apply`;检查 30 天清理任务 |
| 内存不足 | `free -m`、`ps aux --sort=-rss` | 压测进程、日志未轮转 | 杀掉压测进程;检查 logrotate |

## 5. 事故复盘模板

每次 P0/P1 故障在 `docs/ops/incidents/YYYY-MM-DD-<slug>.md` 留一份,四段:

1. **时间线**(精确到秒,含发现方式);
2. **根因**(引用代码/配置行号,不写「疑似」);
3. **影响面**(多少用户、多少分钟、有无数据丢失);
4. **改进项**(每条带负责人与验收方式,进下一轮计划)。
