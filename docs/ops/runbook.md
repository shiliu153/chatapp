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

**B. 宝塔 / mysqld_safe 形态(现网)**:每分钟 cron 兜底。**已于 2026-11-03 上线**。

```bash
# 0) 探活用的 mysql 客户端配置(root 无免密登录,用应用账号建 cnf)
cd /www/wwwroot/chatapp/chatapp
U=$(grep '^DB_USER=' .env | cut -d= -f2); P=$(grep '^DB_PASSWORD=' .env | cut -d= -f2)
printf '[client]\nuser=%s\npassword=%s\nhost=127.0.0.1\nport=3306\n' "$U" "$P" > /root/.my.im.cnf
chmod 600 /root/.my.im.cnf && mysql --defaults-extra-file=/root/.my.im.cnf -N -e 'SELECT 1'

# 1) 安装脚本与参数
mkdir -p /www/server/ops
install -m 755 deploy/ops/mysql-watchdog.sh /www/server/ops/mysql-watchdog.sh
printf 'MYSQL_CNF=/root/.my.im.cnf\nMYSQL_START_CMD="/etc/init.d/mysqld start"\n' \
  > /etc/default/mysql-watchdog

# 2) 每分钟跑一次
echo '* * * * * root set -a; . /etc/default/mysql-watchdog; set +a; /www/server/ops/mysql-watchdog.sh >> /www/wwwlogs/mysql_watchdog.log 2>&1' \
  > /etc/cron.d/mysql-watchdog

# 3) 手动跑一次:健康时应静默退出 0
set -a; . /etc/default/mysql-watchdog; set +a; /www/server/ops/mysql-watchdog.sh; echo $?
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

## 5. 备份与恢复

### 5.1 现在备什么、多久、放哪

| 项 | 内容 | 频率 | 位置 | 保留 |
|---|---|---|---|---|
| `chatapp` 库 | 全库 `mysqldump`(32 张表,约 128 KB) | 每天 03:20 | `/www/wwwroot/chatapp/backups/db/chatapp-db-<时间>.sql.gz` | 14 天 |
| `chatapp_im` 库 | 全库 `mysqldump`(7 张表,约 16 KB) | 每天 03:20 | 同上,`chatapp-im-db-<时间>.sql.gz` | 14 天 |
| 媒体目录 | `media/`(资料图/广场图/聊天图/语音,约 1.6 MB) | 每天 03:20 | `backups/media/chatapp-media-<时间>.tar.gz` | 14 天 |
| 配置快照 | `.env`、imserver `imserver.env`、nginx vhost、两条 supervisor ini、`cron.d/mysql-watchdog` | 每天 03:20 | `backups/config/chatapp-config-<时间>.tar.gz` | 14 天 |

每个 dump 都带同名 `.sha256`;权限 `600`,目录 `700`(`umask 077`)。

- **脚本(仓库是唯一事实来源)**:`deploy/ops/chatapp-backup.sh` → `install -m 755` 到 `/www/server/ops/`
- **cron**(root):
  ```
  20 3 * * * flock -xn /www/server/ops/chatapp-backup.lock \
    -c /www/server/ops/chatapp-backup.sh >> /www/wwwlogs/chatapp-backup.log 2>&1
  ```
- **日志**:`/www/wwwlogs/chatapp-backup.log`,成功一行摘要(`db=/media=/config=/磁盘剩余`),失败非零退出并写「失败: 原因」。
- **看是否还在跑**:`tail -3 /www/wwwlogs/chatapp-backup.log` 与 `ls -lt /www/wwwroot/chatapp/backups/db | head -3`。**超过 36 小时没有新文件就是坏了**。

> **RPO 24 小时 / RTO 约 10 分钟**(实测:dump 1 秒、恢复 7 秒、起服务数分钟)。

### 5.2 异地(零成本方案)

备份与数据库**同盘**(2C2G 单机,无法本地解决)。当前采用零成本异地:**每天把最新 dump 拉回个人电脑**。

```powershell
# 仓库内脚本,默认存到 %USERPROFILE%\chatapp-backups,保留 30 天,带 sha256 校验
pwsh -NoProfile -File deploy/ops/pull-backup.ps1

# 注册成每天 04:10 的计划任务(机器不开就跳过,不会补跑)
schtasks /create /tn "chatapp-pull-backup" /sc daily /st 04:10 ^
  /tr "pwsh -NoProfile -File D:\pycharmproject\chat_app\deploy\ops\pull-backup.ps1" /f
```

**这条链的诚实边界**:它防的是「服务器磁盘/整机没了」,**不防**「个人电脑也一起没了」。有对象存储预算后应改为上传 OSS/冷归档,并保留本条作为第二份。

### 5.3 从备份恢复(照这个顺序做)

前提:目标机器上 MySQL 8 已就绪;`backups/config/*.tar.gz` 里的 `.env` 已就位。

```bash
# 1) 建库(空库,字符集必须与生产一致,否则中文会乱码)
mysql -uroot -p -e "CREATE DATABASE chatapp CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
                    CREATE DATABASE chatapp_im CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# 2) 恢复两个库(先应用库,再 IM 库;顺序不影响,但应用库更关键)
gunzip -c chatapp-db-<时间>.sql.gz     | mysql -uroot -p chatapp
gunzip -c chatapp-im-db-<时间>.sql.gz  | mysql -uroot -p chatapp_im

# 3) 校验:行数必须与备份时一致(见 5.4 的对照表口径)
mysql -uroot -p -N -B chatapp -e "
  SELECT 'accounts_user',COUNT(*) FROM accounts_user
  UNION ALL SELECT 'users_profile',COUNT(*) FROM users_profile
  UNION ALL SELECT 'users_photo',COUNT(*) FROM users_photo
  UNION ALL SELECT 'discovery_match',COUNT(*) FROM discovery_match;"

# 4) 校验 schema 与当前代码是否一致(不一致说明备份比代码旧,先 migrate)
cd /www/wwwroot/chatapp/chatapp && python manage.py migrate --check

# 5) 起服务 + 冒烟
supervisorctl -c /etc/supervisor/supervisord.conf restart 'chatapp-web:*' 'chatapp-celery:*'
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1/api/v1/health
```

**恢复后必做**:`python manage.py im_sync_pairs`(回填配对到 imserver)、确认 `SMS_PHONE_WHITELIST` 仍在 `.env` 里、确认 `IM_MEDIA_SIGN_SECRET` 与 imserver 侧一致 —— 否则「库恢复了但发不出消息/发不了图」。

### 5.4 恢复演练记录

| 日期 | 场景 | 做法 | 结果 |
|---|---|---|---|
| 2026-11-03 | 生产备份 → **另一台机器**(本机 Docker `mysql:8.0`)恢复 | 拉最新 dump + `.sha256` 校验 → 建库 → 恢复两库 → `migrate --check` → 从恢复库挑已有账号走完整 `sms/send` + `sms/verify` 登录链路 | **通过**:行数与生产逐表一致(`accounts_user` 30 / `users_profile` 30 / `users_photo` 46 / `discovery_match` 3 / `discovery_swipe` 25 / `django_migrations` 55 / `feed_post` 8),`migrate --check` 退出 0,登录返回 `200` 且 `is_new_user=false`(**登进的是恢复出来的原账号**,不是新建号)。耗时:dump 1 秒、应用库恢复 6.5 秒、IM 库 0.4 秒 |

**这次演练踩到的坑(别再踩)**:

1. **`auth_user` 不存在** —— 本项目用自定义用户模型,表名是 **`accounts_user`**。写校验 SQL 时按 Django 默认表名猜会直接报 `Table 'chatapp.auth_user' doesn't exist`。
2. **`chatapp_im` 库不能拿应用账号备** —— 应用账号只有 `chatapp.*` 权限;IM 库的凭据在 imserver 的 `IM_MYSQL_DSN` 里(`mysql://imserver:<口令>@host:port/chatapp_im`),脚本按**最后一个 `@`** 切分来解析。
3. **只 `gzip -t` 不够** —— 截断的 dump 压缩包往往还是合法的 gzip。必须再断言末行是 `-- Dump completed`,脚本里就是这么做的。
4. **PowerShell 不支持 `<` 重定向** —— 在本机演练时用 `docker cp` 把 `.gz` 送进容器再 `gunzip`,不要写 `docker exec ... < file`。
5. **旧 `/root/backup.sh` 是假备份**:它只 dump `chatapp_im` 的 `im_message`/`im_user` 两张表,**应用库一次没备过**,而且没有 cron;最后一次产物停在 2026-10-28。这正是「有备份目录但等于没有」的典型 —— 判断备份是否有效只能靠**恢复演练**,不能看文件在不在。

## 6. 事故复盘模板

每次 P0/P1 故障在 `docs/ops/incidents/YYYY-MM-DD-<slug>.md` 留一份,四段:

1. **时间线**(精确到秒,含发现方式);
2. **根因**(引用代码/配置行号,不写「疑似」);
3. **影响面**(多少用户、多少分钟、有无数据丢失);
4. **改进项**(每条带负责人与验收方式,进下一轮计划)。
