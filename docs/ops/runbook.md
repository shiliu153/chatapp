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

**两套独立备份并存**(2026-11-03 核实):

| 项 | 内容 | 频率 | 位置 | 保留 |
|---|---|---|---|---|
| `chatapp` 库 | 全库 `mysqldump`(32 张表,约 128 KB) | 每天 03:20 | `/www/wwwroot/chatapp/backups/db/chatapp-db-<时间>.sql.gz` | 14 天 |
| `chatapp_im` 库 | 全库 `mysqldump`(7 张表,约 16 KB) | 每天 03:20 | 同上,`chatapp-im-db-<时间>.sql.gz` | 14 天 |
| 媒体目录 | `media/`(资料图/广场图/聊天图/语音,约 1.6 MB) | 每天 03:20 | `backups/media/chatapp-media-<时间>.tar.gz` | 14 天 |
| 配置快照 | `.env`、imserver `imserver.env`、nginx vhost、两条 supervisor ini、`cron.d/mysql-watchdog` | 每天 03:20 | `backups/config/chatapp-config-<时间>.tar.gz` | 14 天 |
| **宝塔原生备份**(独立第二份) | 只备 `chatapp` 库 | 每天 03:30 | `/www/backup/database/mysql/crontab_backup/chatapp/chatapp_<日期>_<时间>_mysql_data.sql.gz` | 7 份 |

每个 dump 都带同名 `.sha256`;文件 `640 root:backup`,目录 `750 root:backup`(`umask 077` 起手再放行 `backup` 组)。

> **为什么要两套**:宝塔那套只备应用库、且是面板托管(改配置不经过仓库);自建这套多备 IM 库 + 媒体 + 配置、且有完整性断言。**两套互相独立**,任何一套挂了另一套还在,日报里也分别核验。

- **脚本(仓库是唯一事实来源)**:`deploy/ops/chatapp-backup.sh` → `install -m 755` 到 `/www/server/ops/`
- **cron**(root):
  ```
  20 3 * * * flock -xn /www/server/ops/chatapp-backup.lock \
    -c /www/server/ops/chatapp-backup.sh >> /www/wwwlogs/chatapp-backup.log 2>&1
  ```
- **日志**:`/www/wwwlogs/chatapp-backup.log`,成功一行摘要(`db=/media=/config=/磁盘剩余`),失败非零退出并写「失败: 原因」。
- **看是否还在跑**:`tail -3 /www/wwwlogs/chatapp-backup.log` 与 `ls -lt /www/wwwroot/chatapp/backups/db | head -3`。**超过 36 小时没有新文件就是坏了**;每天 22:00 的服务器日报也会把两套备份分别核验。

> **RPO 24 小时 / RTO 约 10 分钟**(实测:dump 1 秒、恢复 7 秒、起服务数分钟)。

### 5.2 异地:树莓派(192.168.101.3)

**拓扑决定方向**:生产服务器在公网,树莓派在家里内网。服务器**主动连不到**内网,所以必须是**树莓派主动往外拉**。

```
生产服务器(47.116.114.110)         家庭内网
  03:20 生成备份  ──┐
                    │  ← 树莓派 04:10 主动拉(ssh 只读账号 backup)
                    └──────────────→  树莓派 192.168.101.3
                                        ~/chatapp-backups/  保留 14 天
                                        └→ 回写一行状态到服务器
                                           /var/lib/chatapp-backup/offsite-status.txt
                                              ↑ 22:00 日报读它
```

| 项 | 值 |
|---|---|
| 树莓派账号 | `moonlinux`(该机有 sudo 但要口令;**这条链不需要 root**,密钥/目录/日志都在家目录) |
| 服务器侧账号 | `backup`(专用、只读:能读 `backups/`,能写 `/var/lib/chatapp-backup/offsite-status.txt`,**没有 sudo**) |
| 密钥 | 树莓派 `~/.ssh/id_ed25519_backup` → 服务器 `/home/backup/.ssh/authorized_keys` |
| 脚本 | 仓库 `deploy/ops/pull-backup-pi.sh` → 树莓派 `~/bin/chatapp-pull-backup.sh` |
| 本地目录 | 树莓派 `~/chatapp-backups/`(db / media / config,保留 14 天,约 5 MB/天) |
| 日志 | 树莓派 `~/chatapp-backups/pull-backup.log` |
| cron(树莓派) | `10 4 * * * flock -xn ~/chatapp-backups/.pull.lock -c ~/bin/chatapp-pull-backup.sh >> ~/chatapp-backups/pull-backup.log 2>&1` |

**为什么要单独建 `backup` 账号**:树莓派上放的是能登录服务器的密钥。若直接用 root 的密钥,树莓派一旦被拿下就等于服务器 root;用只读账号,最坏情况是「备份被别人读走」,而不是「生产被接管」。

**判断它还在跑**:

```bash
# 服务器上
cat /var/lib/chatapp-backup/offsite-status.txt
# 树莓派上
tail -3 ~/chatapp-backups/pull-backup.log && ls -lt ~/chatapp-backups/db | head -3
```

**这条链的诚实边界**:

- 树莓派**关机就不拉**。日报口径:36 小时内算正常;36~72 小时只提示(「可能关机」);**超过 72 小时才进硬故障** —— 否则一次关机就天天误报。
- 树莓派 SD 卡当时只剩 5.1 GB(已用 82%)。备份目前约 5 MB/天 × 14 天 ≈ 70 MB,够用;**如果媒体涨到几百 MB 要重新算**,并考虑在服务器装 `rsync` 做真增量(现在服务器没装,用的是 `tar over ssh` 只传新文件)。
- 它防的是「服务器磁盘/整机没了」,**不防**「服务器和树莓派同时没了」。有对象存储预算后应再补一份 OSS 冷归档。

### 5.3 从备份恢复(照这个顺序做)

前提:目标机器上 MySQL 8 已就绪;`backups/config/*.tar.gz` 里的 `.env` 已就位。

> 服务器整机没了时,先从树莓派把最近一份取回来:
> `scp moonlinux@192.168.101.3:~/chatapp-backups/db/chatapp-db-<时间>.sql.gz .`
> (以及同目录的 `.sha256`,先 `sha256sum -c` 校验再恢复)

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

**恢复后必做**:`python manage.py im_sync_pairs`(回填配对到 imserver)、确认准入名单表(`accounts_phoneallowlist`)有数据或 `.env` 里仍有 `SMS_PHONE_WHITELIST` 种子(两者都空 = 不限制登录,见 §6)、确认 `IM_MEDIA_SIGN_SECRET` 与 imserver 侧一致 —— 否则「库恢复了但发不出消息/发不了图」。

### 5.4 恢复演练记录

| 日期 | 场景 | 做法 | 结果 |
|---|---|---|---|
| 2026-11-03 | 生产备份 → **另一台机器**(本机 Docker `mysql:8.0`)恢复 | 拉最新 dump + `.sha256` 校验 → 建库 → 恢复两库 → `migrate --check` → 从恢复库挑已有账号走完整 `sms/send` + `sms/verify` 登录链路 | **通过**:行数与生产逐表一致(`accounts_user` 30 / `users_profile` 30 / `users_photo` 46 / `discovery_match` 3 / `discovery_swipe` 25 / `django_migrations` 55 / `feed_post` 8),`migrate --check` 退出 0,登录返回 `200` 且 `is_new_user=false`(**登进的是恢复出来的原账号**,不是新建号)。耗时:dump 1 秒、应用库恢复 6.5 秒、IM 库 0.4 秒 |

**这次演练踩到的坑(别再踩)**:

1. **`auth_user` 不存在** —— 本项目用自定义用户模型,表名是 **`accounts_user`**。写校验 SQL 时按 Django 默认表名猜会直接报 `Table 'chatapp.auth_user' doesn't exist`。
2. **`chatapp_im` 库不能拿应用账号备** —— 应用账号只有 `chatapp.*` 权限;IM 库的凭据在 imserver 的 `IM_MYSQL_DSN` 里(`mysql://imserver:<口令>@host:port/chatapp_im`),脚本按**最后一个 `@`** 切分来解析。
3. **只 `gzip -t` 不够** —— 截断的 dump 压缩包往往还是合法的 gzip。必须再断言末行是 `-- Dump completed`,脚本里就是这么做的。
4. **PowerShell 不支持 `<` 重定向** —— 在本机演练时用 `docker cp` 把 `.gz` 送进容器再 `gunzip`,不要写 `docker exec ... < file`。
5. **`/root/backup.sh` 是个半成品,但「应用库没备份」的判断是错的(2026-11-03 自我更正)**:`/root/backup.sh` 确实只 dump `chatapp_im` 的 `im_message`/`im_user` 两张表、也确实没进 cron(最后产物停在 2026-10-28)。但当时据此断言「应用库一次没备过」是**错的** —— 宝塔面板里一直有一个每天 03:30 的「备份数据库」任务(`/www/server/panel/script/backup.py database chatapp 7`),产物在 `/www/backup/database/mysql/crontab_backup/chatapp/`,每天都在更新。**教训:判断「有没有备份」不能只看 `crontab -l` 和一个脚本文件,面板托管的计划任务在 `/www/server/cron/<hash>` 里、由 `crontab` 的匿名条目驱动,`grep manage.py` 是搜不到的。**
6. **备份文件得让拉取账号读得到**:`umask 077` 出来的 `600 root:root` 树莓派读不了。脚本改成 `640 root:backup` + 目录 `750 root:backup`(组不存在时自动退回 `600/700`),否则「备份有了但异地永远拉不走」。
7. **状态行里不能有空格**:异地回写的 `ts=2026-11-03 22:33:00` 被日报按空白切词,`ts` 只剩日期,解析直接失败。改成 ISO 的 `ts=2026-11-03T22:33:00`。
8. **服务器上没装 `rsync`**:别照抄「rsync 增量同步」的方案,现在是 `tar -cf - | tar -xf -` 只传本地缺的文件;媒体真涨到几百 MB 再考虑装。
9. **树莓派的 `moonlinux` 有 sudo 但要口令**:非交互脚本里 `sudo` 会直接失败。这条链刻意全程不用 root(密钥、备份目录、日志都在家目录),别再改回 root。

## 6. 准入名单的日常运维(B-1c)

### 6.1 这份名单是什么

**本项目不接入短信商**(2026-11-03 决定),验证码固定为 `123456`,所以「哪些手机号能登录」完全由准入名单决定。名单不是过渡方案,是**长期准入机制**:

- 名单内 = 自己人。**一个号码进了名单,就等于这个账号可以被接管**(名单内彼此之间用固定码就能互相登录),也等于这个人能接管**其他**名单内的号;
- 加人 = 扩大可被接管的账号集合,所以加之前先问清楚「是谁、为什么」,并写进备注栏;
- 名单外一律 `403 + 40301`,发码入口就拦掉(不落码、不占 60 秒重发间隔)。

规则详见 `accounts.services.ensure_phone_allowed()`:库内**停用**优先于 `.env` 种子 → 库内**启用**放行 → `.env` 种子里有则放行 → 名单机制已生效(库或种子非空)则拒 → **库与种子都空 = 不限制**(开发/测试默认)。

### 6.2 日常动作(都在 `/ops/allowlist/`,不用 SSH)

`/ops/` 本身已有三道门:`StaffSecurityMiddleware`(IP 白名单)、运营账号口令、TOTP。名单页在里面,所以**加号必须在能进后台的环境里做**。

| 动作 | 怎么做 | 生效时机 |
|---|---|---|
| 加一个号 | `/ops/allowlist/` → 「加一个号」填手机号 + 备注 → 提交 | **立刻**(写库后清快照缓存),下一次发码就 `200` |
| 停用一个号 | 列表里点「停用」 | **立刻**,下一次发码/登录就 `403 + 40301` |
| 恢复一个号 | 列表里点「启用」,或在「加一个号」里重新提交该号码(等同重新启用) | 立刻 |
| 改备注 | 重新提交该号码并填新备注 | 立刻 |
| 查「这个号有没有账号」 | 列表「已注册账号」列:`已有账号` / `待首次登录` | 即时 |

**只停用、不删除**:记录保留 `加入人` 与 `加入时间`,事后能回答「谁在什么时候把这个号放进来的」—— 名单本身就是安全边界,这条审计不能丢。

### 6.3 `.env` 的 `SMS_PHONE_WHITELIST` 现在只是「种子」

- 库里**没有**某个号码时,仍按 `.env` 种子放行 —— 这是冷启动/首次导入前的过渡,也是**唯一的安全网**:万一有人清空了名单表,老号还能登;
- 库里**显式停用**的号码优先被拒 —— 否则「停用」停不掉还留在 `.env` 里的老号;
- 两边都空 = **不限制**,等于没有防护。生产上线与恢复后都要确认至少一边非空(见 §5.3 恢复后必做)。

首次上线/迁移到库时用命令把种子搬进库(幂等,**不会**把已停用的号重新启用):

```bash
# 服务器上,cwd=/www/wwwroot/chatapp/chatapp
python manage.py allowlist_seed_import --dry-run     # 先看会加哪些号(输出已脱敏)
python manage.py allowlist_seed_import               # 真导,写完立刻生效
```

导入后 `.env` 的种子**保留不删**:它是上面说的安全网,不是主数据源。

### 6.4 踩坑

1. **别手改数据库再等生效** —— 快照缓存 TTL 60 秒(`SMS_ALLOWLIST_CACHE_TTL`),直连 MySQL `UPDATE` 最多要等一分钟。走 `/ops/allowlist/` 或 `allowlist_seed_import` 会显式清缓存,是立刻的。
2. **`.env` 改名单仍然要重启 web** —— 种子是在 `settings` 启动时读成 `frozenset` 的。这也是为什么主数据源搬进了数据库。
3. **名单表被清空 = 回到「不限制」** —— 不是「谁都登不上」。发现名单表空了,先立刻 `allowlist_seed_import`,再排查是谁清的。
4. **`403`/`200` 的差异本身是个探测口子**(受 20 次/小时 IP 限流约束):别拿名单页当对外开放的功能宣传。
5. **停用不影响已登录的会话** —— 名单只管「能不能重新拿令牌」;已经在线的设备要继续用,得去 `/ops/users/` 封禁(`banned_heavy`)或用单设备登录顶掉。

## 7. 事故复盘模板

每次 P0/P1 故障在 `docs/ops/incidents/YYYY-MM-DD-<slug>.md` 留一份,四段:

1. **时间线**(精确到秒,含发现方式);
2. **根因**(引用代码/配置行号,不写「疑似」);
3. **影响面**(多少用户、多少分钟、有无数据丢失);
4. **改进项**(每条带负责人与验收方式,进下一轮计划)。
