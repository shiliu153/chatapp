# 运维手册:告警处置与故障恢复

> 配套:`docs/reports/stress-test-2026-11-01.md`(自愈矩阵实测)、`docs/ops/imserver.md`(部署与探针)。
> 目标:任何一条告警都能在 1 分钟内定位到「看哪块板 → 做什么」。

## 1. 探针与告警通道

| 探针 | 频率 | 失败判定 | 通知 |
|---|---|---|---|
| `imserver /internal/readyz` | **30s**(脚本内一次复测) | 连续 2 次非 200 | 邮件(`/opt/notify`,与日报同链路) |
| `GET /api/v1/health` | **30s**(同上) | 同上 | 同上 |
| Prometheus 抓 `job=api` / `job=im` | 15s | `up=0` 持续 30s(`ApiDown`)/ 1m(`ImDown`) | Alertmanager → relay → 邮件 |
| MySQL 3306 探活 | 60s | 一次失败即拉起 | 看门狗脚本 + 邮件(实测 T0+25s 到达,见 §2.4) |
| 磁盘/内存 | 5min | 磁盘 >85%、可用内存 <100MB | 同上 |

> 2026-11-01 之前的探针是「每分钟一次、连续 2 轮才 ALERT」,实测 90 秒宕机只记 1 次失败、
> 没有告警。**2026-11-05(E-4 ②)** 改成:宝塔仍每分钟调用脚本,但脚本内部先查所有目标、
> 失败隔 30 秒再复测一次 —— 单次故障 30~35 秒内发信,和 Prometheus 那条通道互为兜底。
> **通知通道同时从「微信群机器人」改成邮件**(机器人一直没配 = 告警只落日志),详见
> [observability.md](observability.md) §2.1。

告警邮件里能看到什么、怎么确认通道没断:

```bash
systemctl status chatapp-alert-relay --no-pager     # active (running)
tail -20 /www/wwwlogs/alert-relay.log               # 每条告警的处理结果
/opt/notify/bin/notify log -n 10                     # notify 自己的发送记录(含去重跳过)
```

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

验证(会短暂中断 DB,低峰期做)。**2026-11-05 已按下面这条命令实跑过两次,数字与结论见 §2.4**,别再用「手敲 kill + sleep 90」的老办法,那样测不出检测延迟、也算不出 MTTR:

```bash
# 服务器上(先 DRY_RUN 确认前置检查与 dump 都过,再正式跑)
DRY_RUN=1 bash /www/server/ops/mysql-drill-e5.sh      # 只做前置检查 + 打 dump,不杀进程
CONFIRM=1 bash /www/server/ops/mysql-drill-e5.sh      # 真演练,约 2 分钟
```

脚本(`deploy/ops/mysql-drill-e5.sh`)会:打两份 dump 兜底 → 全表行数基线 → 1 秒粒度采样
(MySQL 探活 / Django `readyz` / imserver `readyz`)→ `kill -9` mysqld 与 mysqld_safe →
等看门狗(超过 120 秒它自己接手 `/etc/init.d/mysqld start`)→ 对行数、抓看门狗日志、
Alertmanager 告警与 `notify` 邮件记录,最后在 `$OUT_DIR/summary.txt` 落一份结论。
**期望**:看门狗日志出现 `restarted successfully`,并收到一条「MySQL 曾宕机,看门狗已拉起」的邮件。

### 2.3 注意

- 看门狗用 `flock` 防重入,恢复动作未结束时会跳过本轮。
- **锁 fd 必须在子进程里关掉(`9>&-`)** —— 2026-11-05 E-5 演练实测踩到的 P0:
  `/etc/init.d/mysqld start` 拉起的 `mysqld_safe` / `mysqld` 会**继承看门狗持有的锁文件描述符**,
  守护进程常驻 → flock 被永久持有 → 之后每分钟都 `skip: previous run still in progress`,
  **看门狗在第一次成功恢复后就把自己关掉了**(当时 12:24、12:25 两条 skip 就是它)。
  处置:`rm -f /run/lock/mysql-watchdog.lock` 换掉被继承的旧 inode,再装修复后的脚本
  (所有子进程带 `9>&-`)。**改这个脚本时别把 `9>&-` 删掉**,`deploy/ops/mysql-drill-e5.sh` 也同理(`8>&-`)。
- 拉起失败只告警一次(状态文件 `/var/lib/mysql-watchdog/down`),避免每分钟刷屏;
  恢复后自动清状态并补一条恢复通知。
- 脚本默认读 `/root/.my.im.cnf`(现网已有),可用 `MYSQL_CNF` 覆盖。

### 2.4 演练记录:MySQL 双杀(2026-11-05,E-5)

低峰窗口 12:22–12:27 连跑两次(第一次是验收,第二次是**修完锁 bug 后的回归验证**),`kill -9` 同时带走
`mysqld` 与 `mysqld_safe`,用 1 秒采样记录影响面。全部数字来自服务器上的
`/root/e5-drill-20261105-122238/` 与 `/root/e5-drill-20261105-122634/`(summary/samples/drill.log 三件套)。

| 轮次 | T0(杀) | 看门狗检测(T1) | 检测延迟 | 恢复(T2) | **MTTR(T2−T0)** | 拉起耗时(T2−T1) | 不可达样本 | 行数核对 |
|---|---|---|---|---|---|---|---|---|
| #1 验收 | 12:22:40 | 12:23:01 | **20s** | 12:23:05 | **24.2s** | 4.2s | 16/1s | 33 表一致 |
| #2 回归 | 12:26:36 | 12:27:01 | **24s** | 12:27:04 | **27.2s** | 2.9s | 20/1s | 33 表一致 |

- **影响面**:`Django /api/v1/readyz` 与 `imserver /internal/readyz` 在整个窗口内都是 `503`,恢复后同时回 `200`(+4s);
  `https://chat.shiliu153.cn/` 首页 200;`accounts_user` 30 / `feed_post` 8 前后一致,无数据损失。
- **告警到达**:看门狗邮件在 **T0+25.4s**(#1:12:23:06)与 **T0+28.4s**(#2:12:27:05)投递成功 —— 这是快通道。
  Prometheus 侧**两次都没有 `MysqlDown`**:它要求 `mysql_up==0` 持续 1 分钟,而本次中断只有 24–27 秒,
  **短于 `for` 的抖动本来就不该响**,不算漏报。真正响的是 `ApiHighErrorRate`(5 分钟速率窗口):
  12:25:02 触发(3.488%)、12:25:13 邮件到达,**比故障晚 2 分 33 秒** —— 依赖 5 分钟窗口的规则对 30 秒级
  故障天然迟钝,快通道仍然只有看门狗邮件那一条。
- **顺带修掉的 P0(这次演练唯一的“额外收获”)**:第一次恢复成功后看门狗**把自己锁死了**
  (fd 继承,见 §2.3),若不修,下次真宕机就没有任何东西能拉起 DB。修复:所有子进程 `9>&-`,
  并 `rm -f /run/lock/mysql-watchdog.lock` 清掉被继承的旧 inode;#2 跑完 12:28、12:29 两轮 cron
  均静默(无 skip、无锁残留),修复生效。
- **验收结论**:看门狗自动拉起 ✅、告警到达 ≤60s ✅(25.4s / 28.4s)、MTTR 24.2s / 27.2s ✅(≤30s);
  数字已按「检测延迟 + 拉起耗时」拆开记录,因为 cron 是整分钟对齐,检测延迟本身有 0–60s 的抖动。

## 3. 故障处置顺序

全栈同时打崩时(2026-11-01 实测 111s),按依赖顺序恢复,不要同时重启:

1. **MySQL** → `mysql -e 'SELECT 1'` 通过再进行下一步(看门狗会自动做,失败才人工)。
2. **imserver** → `curl -s -o /dev/null -w '%{http_code}' 127.0.0.1:9101/internal/readyz`,
   期望 200;若容器 crash loop,`docker logs --tail 50 imserver` 看是否 DB 未就绪。
3. **Django(gunicorn)** → `supervisorctl status chatapp-web`,期望 RUNNING;
   进程在但 502 时看 `supervisorctl tail chatapp-web`。
   **现网的实际命令**(`supervisorctl` 不在 PATH 里,而且进程名带组前缀,2026-11-05 踩过):

   ```bash
   S=/www/server/panel/pyenv/bin/supervisorctl; C=/etc/supervisor/supervisord.conf
   $S -c $C status                                  # 三个 program:chatapp-web / chatapp-celery / profile-web
   $S -c $C restart chatapp-web:chatapp-web_00      # 只写 chatapp-web 会报 "no such process"
   $S -c $C tail chatapp-web:chatapp-web_00
   ```

   改 `.env`(如 `CANDIDATE_CACHE_TTL`)后**必须重启它**才生效,重启窗口约 3 秒 502。
4. **nginx** → `nginx -t && systemctl reload nginx`。

## 4. 常见告警对照表

| 告警 | 先看 | 常见原因 | 处置 |
|---|---|---|---|
| `readyz` 连续失败 | `docker logs imserver` | MySQL 不可达 / 池连接全死 | 先修 DB;池有 idle ping,DB 恢复后自动重连 |
| `ApiDown`(抓不到 Django) | `supervisorctl status 'chatapp-web:*'` | 进程被 OOM 杀 / 端口占用 / 启动异常 | supervisor 会拉起;连挂两次就 `supervisorctl tail chatapp-web` 看启动日志 |
| `ImDown`(抓不到 imserver) | `curl 127.0.0.1:9101/internal/readyz` | 503=DB/Redis;000=进程没了 | 按 §3 的依赖顺序恢复 |
| `MysqlDown` / `RedisDown` | `mysql -e 'SELECT 1'`、`docker ps \| grep redis` | 进程挂了 / 磁盘满 / OOM | 看门狗会拉起 MySQL;Redis 重启后限流计数与缓存为空,属正常。**注意这条规则有 `for: 1m`,30 秒级的抖动(比如演练双杀)它不会响,别把「没告警」读成「没宕机」** —— 短故障的告警快通道是看门狗邮件(§2.4) |
| `ExporterDown` | `docker compose ps` + `systemctl status chatapp-celery-exporter` | 容器挂了 / 端口冲突 | 指标盲区优先修,不然下一次故障没人知道 |
| API 5xx >1% | gunicorn 日志 + `request_id` | DB 宕机、代码异常 | 用 `request_id` 在日志里定位单条请求;未预期异常现在返回 JSON 500 并带堆栈 |
| API p99 >500ms | MySQL 慢查询、连接数 | 慢 SQL、连接池打满 | `SHOW FULL PROCESSLIST`;必要时限流 |
| Celery 积压 / 失败 | `celery_queue_depth` 面板 + worker 日志 | worker 挂了 / 限速过低 / imserver 不可达 | 重启 worker;队列分级与限速见 [peak-shaving.md](../reports/peak-shaving.md) |
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

**恢复后必做**:`python manage.py im_sync_pairs`(回填配对到 imserver)、确认准入名单表(`accounts_phoneallowlist`)有数据或 `.env` 里仍有 `SMS_PHONE_WHITELIST` 种子(两者都空时**生产会全拒登录**,见 §6.4)、确认 `IM_MEDIA_SIGN_SECRET` 与 imserver 侧一致 —— 否则「库恢复了但发不出消息/发不了图」。

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

规则详见 `accounts.services.ensure_phone_allowed()`:库内**停用**优先于 `.env` 种子 → 库内**启用**放行 → `.env` 种子里有则放行 → 名单机制已生效(库或种子非空)则拒 → **库与种子都空 = 按 `SMS_ALLOWLIST_STRICT` 判定**:开发/测试放行、**生产(fail-closed)一律拒**,见 §6.4。

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
- 两边都空时按 `SMS_ALLOWLIST_STRICT` 判定:**开发/测试放行**(本地与 CI 要能跑),**生产 fail-closed 一律拒**(2026-11-08,R4-B1)。所以生产上线与恢复后都要确认至少一边非空(见 §5.3 与 §6.4),否则全站登录 `403 + 40301`。

首次上线/迁移到库时用命令把种子搬进库(幂等,**不会**把已停用的号重新启用):

```bash
# 服务器上,cwd=/www/wwwroot/chatapp/chatapp
python manage.py allowlist_seed_import --dry-run     # 先看会加哪些号(输出已脱敏)
python manage.py allowlist_seed_import               # 真导,写完立刻生效
```

导入后 `.env` 的种子**保留不删**:它是上面说的安全网,不是主数据源。

### 6.4 首次部署顺序(按这个顺序就不会被 `accounts.E001` 拦住)

名单为空这件事,现在**部署期就会红**(R4-B1):`SMS_DEV_MODE=1`、`DEBUG=0`、且
`SMS_PHONE_WHITELIST` 为空时,`python manage.py check` 报一条

```
accounts.E001: 生产开启了固定验证码(SMS_DEV_MODE=1),但没有任何准入名单种子
```

新机器/新库照下面四步走。顺序反了会直接卡住:**`check` 对每个 `manage.py` 命令都生效**
(除非显式 `--skip-checks`),所以「先配种子」这一步不能挪到 `migrate` 之后:

| 步骤 | 做什么 | 为什么是这个位置 |
|---|---|---|
| ① 配种子 | `.env` 写 `SMS_PHONE_WHITELIST=139xxx,138xxx`(至少一个号) | 先让它非空,`check` 才不会红;空名单 = 严格模式下谁都进不来 |
| ② `migrate` | `python manage.py migrate` | 建出 `accounts_phoneallowlist` 表,第 ③ 步才有地方导 |
| ③ 导入 | `python manage.py allowlist_seed_import --dry-run` → 去掉 `--dry-run` 再跑 | 把种子搬进库,之后运营在 `/ops/allowlist/` 维护;幂等,不会把已停用的号重新启用 |
| ④ 留种子 | `.env` 的 `SMS_PHONE_WHITELIST` **保留不删** | 它是安全网:万一名单表被清空,老号还能登(见 §6.3) |

> 应急:第 ① 步忘配、命令又被 `check` 拦住时,`python manage.py <命令> --skip-checks`
> 可以先跑通,但**跑完必须补上名单**,不要把它当常态。

两条口径要记住:

- **严格模式不会锁死运维**。库与种子都空 = 全站发码/校验一律 `403 + 40301`,但 `/ops/`
  走的是「IP 白名单 + 运营口令 + TOTP」,**不经短信** —— 所以 40301 期间仍然能进
  `/ops/allowlist/` 加号自救。名单把你关在门外的只是**普通用户入口**,不是后台。
- **`SMS_ALLOWLIST_STRICT` 留空 = 按 `DEBUG` 自动判定**:开发/测试放行、**生产即严格**;
  显式写 `"1"` 是同样效果,写 `"0"` 是**封闭测试逃生口**(任意手机号可用固定码登录)——
  只在你确实知道自己在开什么的时候用,生产别写 `0`。

### 6.5 踩坑

1. **别手改数据库再等生效** —— 快照缓存 TTL 60 秒(`SMS_ALLOWLIST_CACHE_TTL`),直连 MySQL `UPDATE` 最多要等一分钟。走 `/ops/allowlist/` 或 `allowlist_seed_import` 会显式清缓存,是立刻的。
2. **`.env` 改名单仍然要重启 web** —— 种子是在 `settings` 启动时读成 `frozenset` 的。这也是为什么主数据源搬进了数据库。
3. **名单表被清空后不是「不限制」**:`.env` 种子非空 → 只有种子里的号能登(fail-closed 到种子);种子也为空且生产严格 → **全站 `403 + 40301`**(2026-11-08 起 fail-closed,不是放行 —— 这一点与 2026-11-04 上线时的行为相反,别再按老口径判断)。发现名单表空了,先立刻 `allowlist_seed_import`(被 `accounts.E001` 拦住时加 `--skip-checks`),再排查是谁清的。
4. **`403`/`200` 的差异本身是个探测口子**(受 20 次/小时 IP 限流约束):别拿名单页当对外开放的功能宣传。
5. **停用不影响已登录的会话** —— 名单只管「能不能重新拿令牌」;已经在线的设备要继续用,得去 `/ops/users/` 封禁(`banned_heavy`)或用单设备登录顶掉。

## 7. 日志轮转(2026-11-04,D-3 选项 A 顺带)

**背景**:`LOG_FILE=/www/wwwlogs/chatapp/app.log`,每个请求一行 JSON。2026-11-04 压测实测
持续高压约 **1.4MB / 5 分钟**(450 rps 量级,30 分钟约 40MB),而**此前没有轮转** ——
长期高压会把 40GB 盘写满,写满后 gunicorn/MySQL 会一起出问题。

**安装(一次性)**:

```bash
cp deploy/ops/chatapp-logrotate.conf /etc/logrotate.d/chatapp
chmod 644 /etc/logrotate.d/chatapp
logrotate -d /etc/logrotate.d/chatapp    # 干跑:确认匹配到 /www/wwwlogs/chatapp/*.log
logrotate -f /etc/logrotate.d/chatapp    # 手动强制转一次,验证产物与进程继续写
ls -lh /www/wwwlogs/chatapp/             # 期望看到 app.log-YYYYMMDD(.gz)+ 新的 app.log
```

**参数**:每天转、留 14 份、超过 200MB 提前转、压缩、`copytruncate`(进程不重开文件)。

**为什么是 `copytruncate`**:gunicorn/celery 用 Python `FileHandler` 一直开着日志文件;
只 rename 不重开的话进程会继续写旧 inode,表现为「日志停了」。`copytruncate` 复制后原地截断,
进程无感;代价是复制与截断之间可能丢几行,访问日志可接受。

**注意**:cron 里的 logrotate(`/etc/cron.daily/logrotate`)每天只跑一次,**200MB 的提前轮转要等下一次 cron**;
如果哪天真的短时间灌满,临时 `logrotate -f` 手动转一次即可。

## 8. 事故复盘模板

每次 P0/P1 故障在 `docs/ops/incidents/YYYY-MM-DD-<slug>.md` 留一份,四段:

1. **时间线**(精确到秒,含发现方式);
2. **根因**(引用代码/配置行号,不写「疑似」);
3. **影响面**(多少用户、多少分钟、有无数据丢失);
4. **改进项**(每条带负责人与验收方式,进下一轮计划)。

## 9. 每日运营指标快照(2026-11-10,V-1)

每天 04:30 由计划任务算一份**昨天的运营数字**写进 `stats_dailymetric`,一天一行;
`/ops/metrics/`(V-2 看板)只读这张表。实时指标仍归 Prometheus,这张表解决的是
**历史趋势**(「上周 DAU 多少」这种问题 Prometheus 答不了)。

### 9.1 口径(写死,别各算一套)

「一天」= **Asia/Shanghai 自然日** `[00:00, 次日 00:00)`,查询时换算成左闭右开的
UTC 时刻区间(`stats/metrics.py::day_range`)。

| 字段 | 口径 | 采不到时 |
|---|---|---|
| `dau` | 当日活跃去重人数(Redis `activity:dau:{YYYYMMDD}` 集合基数) | `—` |
| `new_users` | `User.date_joined` 落在当日的账号数 | — |
| `profiles_completed` | 当日新注册的人里**当前** `Profile.status=complete` 的人数 | — |
| `swipes_like` / `swipes_pass` | `discovery.Swipe` 当日条数(按 `action` 分) | — |
| `matches` | `discovery.Match` 当日新增(含事后被解除的,按事件口径) | — |
| `messages` | IM 库 `im_message` 当日条数(`created_at` 是 epoch 秒) | `—` |
| `active_hours` | 24 个小时桶各自的人数(看板画横条) | `—` |
| `retention_d1` / `retention_d7` | **当日注册 cohort** ∩ 次日 / 第 7 日的活跃人数 | `—` |
| 配对率 | **不落库**,看板现算 `matches / swipes_like`(分母 0 显示 `—`) | `—` |

两条必须知道的限制:

1. **`profiles_completed` 是近似值** —— `Profile` 没有 `completed_at`,回填历史日期时算的是
   「这批人**现在**完善没完善」;
2. **DAU / 活跃时段 / 留存只有上线后 45 天内可回看** —— 日活集合(`users/activity.py`)带
   45 天 TTL,`presence` 只有 7 天的时间戳,事后补不出来。所以**首次上线那天起**才有数据,
   回填更早的日期这几个字段是空的,这是预期的。

另外:`dau` / `messages` / `active_hours` / 留存四个字段**允许为空**,空 ≠ 0 ——
「当天没采到」和「采到了 0 人」是两件事,看板渲染 `—`。

### 9.2 首次上线

```bash
cd /www/wwwroot/chatapp/chatapp
<解释器> manage.py migrate                       # 建 stats_dailymetric 表
<解释器> manage.py metrics_daily --backfill 30 --dry-run   # 先看数字对不对
<解释器> manage.py metrics_daily --backfill 30             # 再写库(回填日 dau/留存为空)
```

生产 `.env` 新增一行 `IM_MYSQL_DSN=mysql://user:pass@127.0.0.1:3306/chatapp_im`(取自
imserver 的同名变量,**不入库**)。该账号只需要 `chatapp_im` 的 **SELECT** 权限,别复用写账号;
留空也能跑 —— 只是消息量一列显示「无数据」。

### 9.3 cron(04:30,宝塔计划任务)

排在 03:20 备份 / 03:30 宝塔原生备份 / 03:40 `refresh_shuffle_keys` / 04:00–04:20 媒体维护之后:

```
30 4 * * * cd /www/wwwroot/chatapp/chatapp && <解释器> manage.py metrics_daily >> /www/wwwlogs/chatapp-metrics.log 2>&1
```

`<解释器>` 与本机其他 `manage.py` 维护任务用的那个保持一致(见 `crontab -l`)。

命令正常输出每天一行,末尾一行窗口汇总:

```
2026-11-09 dau=12 new=3 done=1 like=40 pass=25 match=8 msg=137 d1=- d7=-
窗口 1 天(2026-11-09 ~ 2026-11-09),有活跃数据 1 天
```

退出码:`0` 成功(**包括** IM 库读不到、消息量留空的情况);`1` 参数非法或写库异常。

**幂等**:同一天跑几次都只有一行(`update_or_create`),数据变了重跑会覆盖。
**留存靠「往后补」**:`--date D` 除算 D 之外,还会给 `D-1` 补 `retention_d1`、给 `D-7` 补
`retention_d7`(只 update 已有的行)—— 所以「每天只跑昨天」时,昨天的次日留存会在**后天**
那次运行时补上,这是正常的,不是漏算。

### 9.4 排障三行

| 现象 | 先查 |
|---|---|
| 命令输出里 `msg=-` | `.env` 的 `IM_MYSQL_DSN` 是否配了、该账号能不能连 `chatapp_im`(日志里有 `IM 库读取失败`) |
| 命令输出里 `dau=-` | Redis 里有没有 `activity:dau:*`(用 `redis-cli --scan --pattern 'activity:dau:*'`);注意 45 天 TTL 与「上线后才开始记」 |
| 看板整页空 / 全是 `—` | 表里有没有行:`metrics_daily` 是否在跑;先手动跑一次 `metrics_daily --backfill 30` 看输出 |

### 9.5 看板怎么用(2026-11-10,V-2)

`https://chat.shiliu153.cn/ops/metrics/` —— 运营台侧栏「运营看板」(在「日志」上面)。
和其它 `/ops/` 页面同一套门禁:**必须是 `is_staff` 账号 + 已过 TOTP**(生产
`OPS_OTP_REQUIRED=1`);未登录跳登录页,非运营账号 403。

**这一页是只读的**:只读 `stats_dailymetric` 快照表,不写任何表、不查 IM 库、不算实时指标
(实时归 Prometheus)。页面上每个数字都能对回上面 §9.1 的口径表。

页面三块:

| 区块 | 看什么 |
|---|---|
| 昨日概览(四个数字卡) | 昨天那一行的 DAU / 新注册,以及**近 7 日**(昨天往前共 7 个自然日)配对率 `Σ配对÷Σ喜欢` 与消息量合计。卡上小字是窗口起止日期 |
| 近 30 天趋势 | 最近 30 行的逐日数字:日期 / DAU / 新注册 / 完善 / 喜欢 / 跳过 / 配对 / 配对率 / 消息 / 次日留存 / 7 日留存(配对率是现算的,不落库) |
| 活跃时段 | 最近一行**真的采到**小时分布的快照的 24 个小时桶,纯 CSS 横条(长度 = 相对当日最高峰的比例) |

两条读数规则:

1. **`—` = 当日未采集到,不是 0**。`dau` / `messages` / `active_hours` / 两类留存当天没采到
   就是 `—`;采到了 0 会正常显示 `0`(分不清这两个数字的看板会把「没数据」误当「没人用」)。
2. **卡片上的「昨日」严格指昨天那一行**。如果 04:30 的 `metrics_daily` 没跑成,昨天那一行
   不存在,卡片就是 `—`,不会拿前天的数字冒充昨天 —— 这时先去查 §9.4 第三行。

**空表**(一天都没跑过)页面不会 500,只提示一句「还没有数据」;首次上线按 §9.2 跑一次
`metrics_daily --backfill 30` 就有 30 行了(回填日的 `dau` / 留存仍是 `—`,预期)。
