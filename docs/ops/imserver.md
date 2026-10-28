# 自建 IM 运维手册

> 具体服务器地址、面板口令与密钥不入库;本文件只写可复制的步骤。
>
> 2026-10-22 起,生产形态改为 **Docker 容器**(`imserver:latest`,`network_mode: host`),
> 不再使用 systemd 直接跑二进制;systemd 方式保留在文末作为备选。

## 1. 首次部署(容器形态)

### 1.1 建库与账号

与 Django 同实例、独立库(`chatapp_im`),账号只授权该库:

```sql
CREATE DATABASE chatapp_im DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'imserver'@'localhost' IDENTIFIED BY '<强口令>';
CREATE USER 'imserver'@'127.0.0.1' IDENTIFIED BY '<强口令>';
GRANT ALL PRIVILEGES ON chatapp_im.* TO 'imserver'@'localhost';
GRANT ALL PRIVILEGES ON chatapp_im.* TO 'imserver'@'127.0.0.1';
```

> MySQL 8 建议显式 `IDENTIFIED WITH mysql_native_password`,避免旧客户端
> 在非 TLS 连接上过不了 `caching_sha2_password` 的首次认证。

### 1.2 构建镜像(本地)

服务器是 2C2G,且没有 Node/构建链,**镜像在本地构建后上传**,不要在服务器上编译:

```bash
# 本地仓库根目录
docker build -t imserver:<短 commit> imserver
docker save -o imserver-image.tar imserver:<短 commit>
tar -czf imserver-image.tar.gz imserver-image.tar   # 约 80 MB
scp imserver-image.tar.gz root@<SERVER_IP>:/tmp/
```

> 注意:`docker save` 出来的 tar 本身已是镜像格式,不要再套一层 tar 后直接
> `docker load`(会报 `repositories: no such file`)。要么直接传 `.tar`,
> 要么按上面压成 `.tar.gz` 后在服务器先解压。

### 1.3 服务器落盘

```bash
mkdir -p /www/server/imserver
cd /tmp && tar -xzf imserver-image.tar.gz && docker load -i imserver-image.tar
docker tag imserver:<短 commit> imserver:latest
```

`/www/server/imserver/` 下需要三个文件:

| 文件 | 内容 | 权限 |
|---|---|---|
| `imserver.env` | 服务配置与密钥(见 1.4) | 600 |
| `docker-compose.yml` | 仓库 `imserver/deploy/docker-compose.yml` | 644 |
| `.env` | `IMSERVER_IMAGE=imserver:<短 commit>` | 600 |

### 1.4 `imserver.env`

```ini
IM_LISTEN_WS=127.0.0.1:9100
IM_LISTEN_HTTP=127.0.0.1:9101
IM_MYSQL_DSN=mysql://imserver:<强口令>@127.0.0.1:3306/chatapp_im
IM_REDIS_URL=redis://127.0.0.1:6379/2
IM_JWT_SECRET=<64 位 hex>
IM_INTERNAL_SECRET=<64 位 hex>
IM_MIGRATIONS_DIR=/usr/local/share/imserver/migrations
IM_ALLOWED_ORIGINS=https://<DOMAIN>
# 可信代理:只有直连对端命中这些地址才采信 X-Real-IP(默认本机)
IM_TRUSTED_PROXIES=127.0.0.1,::1
# 监听非回环地址必须显式置 1(默认 0,写错成 0.0.0.0 会启动失败)
IM_ALLOW_PUBLIC_BIND=0
IM_IO_THREADS=2
IM_DB_THREADS=4
IM_DB_POOL=8
IM_MAX_CONN_PER_IP=20
IM_AUTH_RATE=1
IM_AUTH_BURST=60
IM_MAX_FRAME=8192
IM_TEXT_MAX=2000
# 聊天图片 URL 前缀:必须与 Django 的 MEDIA_BASE_URL + /media/chat/ 一致;必填,缺失启动失败
IM_MEDIA_PREFIX=https://<SERVER_IP>/media/chat/
```

- `IM_JWT_SECRET` 必须与 Django 的 `IM_SELF_SECRET` **完全一致**;
- `IM_INTERNAL_SECRET` 必须与 Django 的 `IM_SELF_INTERNAL_SECRET` **完全一致**;
- `IM_MEDIA_PREFIX` 必须与 Django 的 `MEDIA_BASE_URL` 拼上 `/media/chat/` **完全一致** ——
  服务端按这个前缀校验图片 URL,不一致时客户端发图会被 `42201` 拒掉;
- `IM_ALLOWED_ORIGINS` 只影响带 `Origin` 头的浏览器 WS;原生 App 不带 Origin。
  站点换域名/HTTPS 后要同步改。**不配也不是「全放行」**:没有白名单时按同源校验
  (`Origin` 的 host 必须等于 `Host` 头),跨站页面会被 403 拒掉。
- `IM_TRUSTED_PROXIES`(默认 `127.0.0.1,::1`)决定「谁有资格写 `X-Real-IP`」:
  只有直连对端命中这个列表(支持 CIDR)时才采信该头,否则一律用真实对端地址。
  这样即使有人绕过 nginx 直连 9100,也伪造不了单 IP 连接数与鉴权令牌桶的 key。
  nginx 不在同一台机器时,把它的出口 IP/网段加进来(例如 `10.0.0.0/8`)。
  **不要显式置空**:那会让所有连接都按对端地址计数,nginx 反代时全站挤在
  `127.0.0.1` 一个 key 上(启动日志会打 `trusted_proxies_empty` 警告)。
- `IM_ALLOW_PUBLIC_BIND`(默认 `0`):`IM_LISTEN_WS`/`IM_LISTEN_HTTP` 写成非回环地址
  时**必须显式置 1**,否则启动直接报错。9101 的内部接口只靠「回环 + HMAC」保护,
  这个开关是防止部署时手滑把管理接口暴露到公网的最后一道闸。

### 1.5 迁移与启动

```bash
cd /www/server/imserver
docker compose run --rm imserver --migrate   # 逐版执行,可重复
docker compose up -d
docker compose ps
```

容器 `restart: unless-stopped` + `network_mode: host`:端口只监听 `127.0.0.1`,
由宿主机 nginx 反代,不额外暴露公网端口。

### 1.6 Nginx

把 `imserver/deploy/nginx-im.conf` 的两个 `location` 粘进站点 `server{}`
(本项目是 `/www/server/panel/vhost/nginx/47.116.114.110.conf`),
`nginx -t && nginx -s reload`。

### 1.7 Django `.env`

```ini
IM_BACKEND=self                 # 灰度期配合 IM_SELF_GRAYLIST
IM_SELF_URL=http://127.0.0.1:9101
IM_SELF_WS_URL=ws://<SERVER_IP>/im/ws
IM_SELF_HTTP_URL=http://<SERVER_IP>/im/api
IM_SELF_SECRET=<与 IM_JWT_SECRET 一致>
IM_SELF_INTERNAL_SECRET=<与 IM_INTERNAL_SECRET 一致>
IM_SELF_TOKEN_TTL=86400
IM_SELF_GRAYLIST=7,8            # 只放隔离测试号;全量才写 all
```

改完重启 `chatapp-web` 与 `chatapp-celery`(env 只在进程启动时读)。

## 2. 健康检查

```bash
curl http://127.0.0.1:9101/internal/healthz
curl http://127.0.0.1:9101/internal/readyz
docker compose logs --tail=100 imserver
```

- `healthz` 只证明进程存活(免签名);
- `readyz` 检查 MySQL + Redis,失败返回 503;
- `internal/stats` 需要 HMAC,一般用脚本。

外网验证(确认 nginx 与容器都通):

```bash
curl -i http://<SERVER_IP>/im/api/conversations          # 401 + 40101 JSON 即正常
```

## 3. 升级

```bash
# 本地:构建新镜像并上传
docker build -t imserver:<新 commit> imserver
docker save -o imserver-image.tar imserver:<新 commit>
tar -czf imserver-image.tar.gz imserver-image.tar
scp imserver-image.tar.gz root@<SERVER_IP>:/tmp/

# 服务器
cd /tmp && tar -xzf imserver-image.tar.gz && docker load -i imserver-image.tar
docker tag imserver:<新 commit> imserver:latest
cd /www/server/imserver
sed -i 's/^IMSERVER_IMAGE=.*/IMSERVER_IMAGE=imserver:<新 commit>/' .env
docker compose run --rm imserver --migrate
docker compose up -d
```

迁移按 `im_schema_version` 逐版执行,重复执行安全。回滚镜像只需把 `.env`
里的 tag 改回旧版本并 `docker compose up -d`(迁移不回滚,代码需向前兼容)。

## 4. 回退到腾讯 IM(2026-10-26 已演练)

**顺序:先止血,再改配置,两个进程都要重启。** 实测踩到的两个坑写在命令后面。

```bash
# 1) 止血:先停 imserver(此时客户端连不上自建 WS,但 Django 仍正常)
cd /www/server/imserver && docker compose stop imserver

# 2) 改配置
cd /www/wwwroot/chatapp/chatapp && sed -i 's/^IM_BACKEND=self$/IM_BACKEND=tencent/' .env

# 3) 重启「两个」进程(.env 只在进程启动时读一次)
SC=/www/server/panel/pyenv/bin/supervisorctl
$SC -c /etc/supervisor/supervisord.conf restart 'chatapp-web:*'
$SC -c /etc/supervisor/supervisord.conf restart 'chatapp-celery:*'

# 4) 验证:backend 必须变成 tencent,且带 user_sig
curl -s -X POST http://<SERVER_IP>/api/v1/im/user_sig -H "Authorization: Bearer <token>"
# → {"backend":"tencent","user_sig":"...","sdkappid":...}

# 5) 让用户重启 App(下次登录拿腾讯引导包);期间自建侧消息腾讯看不到
```

回退后自建期间的消息仍在 `chatapp_im` 库中,但腾讯侧看不到;回退前需产品知情。

**坑 1:supervisor 的程序名带组前缀。** `supervisorctl restart chatapp-web` 会报
`ERROR (no such process)`,必须写 `chatapp-web:*`(或全名 `chatapp-web:chatapp-web_00`)。
写错时 `.env` 已经改了、进程却没重载,会留下一段「imserver 已停 + 后端仍按 self 跑」的空窗
(演练时约 2 分钟)。

**坑 2:只重启 gunicorn 不够。** Celery 也缓存了 `IM_BACKEND`,灰条/系统通知等异步副作用
仍会走旧后端;回退时必须一起重启,否则表现是「HTTP 已经切腾讯了,但系统消息发不出来」。

**停机期间的外部表现**(实测):`/im/api/*` 与 `/im/ws` 都返回 **502**(nginx 上游不可用),
不是 401/503 —— 排查时别误判成鉴权问题。

**恢复(演练验证过)**:`IM_BACKEND=self` → `docker compose start imserver` → 重启上面两个进程,
`readyz` 200、`user_sig` 回到 `backend=self`、`chatapp_im.im_message` 行数不变(数据没丢)。

## 5. 备份

- `chatapp_im` 随现有 MySQL 备份一起 `mysqldump`;
- Redis 只存在线态与封禁键,丢失可自愈;封禁以 Django 403 兜底;
- 容器日志走 json-file,已限制 `20m × 5`。

## 6. 常见问题

| 现象 | 排查 |
|---|---|
| 客户端连不上 WS | Nginx `/im/ws` 是否带 `Upgrade`/`Connection`;`proxy_read_timeout` ≥ 90s |
| 所有请求都像来自 127.0.0.1 | Nginx 是否设置 `X-Real-IP` |
| `readyz` 503 | MySQL 连接串/Redis 地址;`docker compose logs imserver` |
| 封禁后仍能重连 | `/internal/kick` 是否 `block=true`;Redis `im:block:<uid>` 是否存在 |
| 消息重复 | 客户端是否复用 `client_msg_id`;服务端唯一键是否生效 |
| `docker load` 报 `repositories: no such file` | 上传的是「套了一层的 tar」,先解压再 load |
| 容器起来但 nginx 502 | 容器是否用 `network_mode: host`;`curl 127.0.0.1:9101/internal/healthz` |

## 7. 代码同步(2026-10-22)

自建 IM 的 22 个提交与本次部署文档**已推送到 `origin/master`**(`f0b4b61`),
服务器也已对齐同一提交,`git bundle` 只是当时的临时通道,后续不再需要。

日常同步仍用服务器既有的「先备份、再 reset」流程(服务器历史与 `origin` 曾分叉,
普通 `git pull` 可能报分叉):

```bash
ssh root@<SERVER_IP> 'cd /www/wwwroot/chatapp && git fetch origin && git reset --hard origin/master'
# 代码有变时再重启 chatapp-web / chatapp-celery
```

> 纯文档提交(如 `f0b4b61`)不需要重启进程;改到 `.env`、任务代码或迁移时才需要。

## 8. 500 连接压测(2026-10-22)

工具:`imserver/scripts/bench_ws.py`(Python + `websockets`,只依赖标准库与 websockets)。

```bash
# 服务器上直连(逐连接伪造 X-Real-IP,模拟不同客户端)
IM_JWT_SECRET=$(grep '^IM_JWT_SECRET=' /www/server/imserver/imserver.env | cut -d= -f2) \
  /root/bench-venv/bin/python bench_ws.py --n 500 --interval 10 --duration 60

# 公网经 nginx(所有连接同一个出口 IP,需临时调大下面三个值)
#   IM_MAX_CONN_PER_IP=1000  IM_AUTH_RATE=1000  IM_AUTH_BURST=1000
python bench_ws.py --uri ws://<SERVER_IP>/im/ws --n 500 --interval 10 --duration 60
```

**为什么要伪造 `X-Real-IP`**:服务端默认单 IP 最多 20 条连接、鉴权 1 次/秒(burst 60)。
生产里 500 个用户来自 500 个 IP,所以同机压测要逐连接伪造;外部压测则临时调大三个配置项,
压完改回默认值并重启。

**实测结果**:

| 场景 | 连接 | 消息 | ack 延迟 | RSS |
|---|---|---|---|---|
| 500 连接 + 50 msg/s,公网经 nginx,60s | 500/500,0 错误 | 3000 | p50 52ms / p95 67ms / **p99 93ms** | 22 MB |
| 500 连接冷启动突发(每人 2 条) | 500/500,0 失败 | 1000 | p50 5.0s(吞吐上限) | 22 MB |

**压测发现并修复的两个问题**(第一批,`5caa454`):

1. **`im_user` 间隙锁**:每条消息对收发双方各做一次
   `INSERT ... ON DUPLICATE KEY UPDATE`,500 个相邻 uid 并发时锁等待可达 115ms。
   改为进程内用户存在性缓存 + 未命中先 `SELECT 1`(MVCC 读,不拿写锁)。
2. **冷启动死锁**:500 个新会话并发创建时 `im_conversation` 唯一键死锁,
   1000 条里失败 10 条(1%)。发送事务对 `1213`/`1205` 重试 3 次(2/4ms 退避)。

**吞吐优化(2026-10-22 第二批)**:

> 完整实验记录(基线、失败假设、分阶段数据、天花板计算):
> [imserver-throughput.md](imserver-throughput.md)

| 版本 | 1000 条耗时 | 吞吐 |
|---|---|---|
| 初版 | 9.4s | 106/s |
| 预编译缓存 + 合并 unread + 画像缓存 + `IM_DB_THREADS=32` | 4.7s | 215/s |

做法:
1. **按连接缓存 prepared statement**(`stmt.cpp`):每条写语句原本
   `prepare + execute + close` 三次往返,缓存后只剩 `execute` 一次;
2. 收发双方的 `im_conversation_state` 用一条多行 INSERT 写掉;
3. 消息发送不再预查 `client_msg_id`(靠唯一键 1062 走幂等分支);
4. 用户画像加进程内缓存,消息热路径不再 SELECT `im_user`;
5. 在线状态 Redis 写入从「每帧」节流到「每 30s」(TTL 90s,语义不变)。

> **吞吐天花板**:2C2G 上 MySQL 约 1500–2000 条简单 SQL/秒,而一条消息仍需
> ~7 条 SQL(`START`/黑名单/会话锁/插消息/更新会话/合并 unread/`COMMIT`),
> 所以上限约 200–250 msg/s。要到 1000 msg/s,只能:
> ① 升配到 4C8G+(最直接);② 把多条消息合并进一个事务(应用层批量提交);
> ③ 把 unread 计数改成异步/Redis 累加(牺牲强一致)。
> 单纯加 `IM_DB_THREADS` 在 2 核上收益很小(8→32 仅 +18%)。

## 9. 备选:systemd 直接跑二进制

仓库仍保留 `deploy/imserver.service`。若不用容器,需要宿主机具备
Boost ≥ 1.83、nlohmann-json、mysqlclient、hiredis 开发库,并且二进制与宿主机
glibc 匹配(在 Ubuntu 24.04 构建的二进制**不能**直接放到 Alibaba Cloud Linux 3 上跑)。

## 10. MySQL 连接池存活探测(2026-10-26 事故与修复)

### 10.1 现象

2026-10-26 做灰度手测时发现:WS 能连、鉴权能过、`/internal/healthz` 200,
但 `readyz` 是 **503**,发消息回 `50001`,拉黑/解封的 `/internal/blacklist` 回
**422「参数不合法」**(异常被 catch 包成了参数错误,极容易误判成请求格式问题)。

### 10.2 根因

池在启动时一次性建 `IM_DB_POOL`(64)条连接,`acquire()` 只借出/归还、**不校验存活**;
MySQL `wait_timeout=28800`(8 小时)把空闲连接全掐了。死连接被反复借出,于是每条 SQL
都报 `Lost connection to MySQL server during query`,直到重启容器才恢复。

时间线:容器 10-22 15:51(北京)启动 → 当晚约 23:51 连接全被 MySQL 掐掉 →
此后约 3 天,自建 IM 一条消息都写不进去(只有灰度测试号 7/8,无真实用户受影响)。

### 10.3 修复(`src/store/mysql_pool.cpp`)

| 位置 | 行为 |
|---|---|
| `MysqlPool::acquire()` | 连接空闲 ≥ `IM_DB_IDLE_PING_MS`(默认 5000)时先 `mysql_ping`;失败则 `clear_stmt_cache` + 关闭 + 重连(最多 3 次,50/100/150ms 退避) |
| `Lease::query()` | 遇到 2006/2013/2055(连接级错误)立即丢弃连接,槽位置空,下次 acquire 重连 |
| 重连失败 | 返回空连接(不抛):任何 SQL 立刻失败并走 50001 分支,不会把死连接塞回池,也不会让异常逃出 DB 线程池 |
| `WsSession::run_db()` | DB 线程池里的任务统一包一层 try/catch,异常降级成一条 50001,避免 `std::terminate` |

配置项(可选,不写就用默认):

```ini
IM_DB_IDLE_PING_MS=5000   # 0=每次 acquire 都 ping(测试用);负数=关闭探测(不推荐)
```

### 10.4 验证方法

```bash
# 1) 池能自愈:掐掉 imserver 的所有 MySQL 连接,readyz 应仍是 200
mysql -uroot -p -e "SELECT id FROM information_schema.PROCESSLIST WHERE user='imserver'" \
  | tail -n +2 | xargs -I{} mysql -uroot -p -e "KILL {}"
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9101/internal/readyz   # 200
docker logs imserver --since 1m | grep mysql_reconnect                          # 有重连日志

# 2) 单元/DB 测试(本地 Docker)
docker compose -f imserver/docker-compose.test.yml run --rm test bash -c \
  'cmake -S /src -B /src/build -G Ninja && cmake --build /src/build && \
   export IM_TEST_MYSQL_DSN="$IM_MYSQL_DSN" && ctest --test-dir /src/build -L db'
# 其中 StoreTest.PoolReconnectsAfterServerKill 就是「KILL 掉连接后池必须重连」
```

### 10.5 运维要求

### 10.5 探针(宝塔计划任务,2026-10-26 已上线)

这次 503 挂了 3 天没人发现,因为只看进程/端口。现在用宝塔计划任务每分钟跑一次
`imserver/deploy/probe-readyz.sh`(任务名 **imserver-readyz-探针**):

| 项 | 值 |
|---|---|
| 脚本 | `/www/server/imserver/probe-readyz.sh`(仓库 `imserver/deploy/probe-readyz.sh`) |
| 周期 | 每分钟(`*/1 * * * *`) |
| 判定 | 单轮内查两次(间隔 2s),都非 200 记一次;连续 **2 轮**失败才告警 |
| 告警 | 写 `/www/wwwlogs/imserver_probe.log` + stdout 打 `ALERT`(宝塔「任务日志」可见)+ 可选 webhook |
| 去重 | 同一事件只告警一次;恢复后计数清零,下次事故重新告警 |
| 日志 | `/www/wwwlogs/imserver_probe.log`(超 1MB 自动只留最后 500 行) |
| 接 webhook | 在 `/www/server/imserver/probe.env`(600)写 `IM_PROBE_WEBHOOK=<企业微信/钉钉群机器人地址>`,发 `{"msgtype":"text",...}` 文本消息;**别写进计划任务命令**(面板任务记录存 sqlite,UI 和备份都能看到) |

> 当前服务器还没有配任何消息通道(面板 `dingding.json`/`weixin.json` 都是空的),所以告警只落在
> `/www/wwwlogs/imserver_probe.log` 和宝塔「任务日志」里。要真推到手机,配一个群机器人地址写进
> `probe.env` 即可,脚本不用改。

> **为什么不能靠退出码告警**:宝塔生成的包装脚本(`/www/server/cron/<md5>`)无论任务本身
> 退出码是多少都以 `rm -f` 收尾、固定返回 0,面板收不到失败信号。所以告警必须在脚本里自己发。

实测(2026-10-26):正常路径退出 0、计数清零;把 `IM_PROBE_URL` 指到死端口模拟故障,
第 1 轮只记录、第 2 轮打 ALERT 并退出 1、第 3 轮不再重复告警——符合设计。

部署脚本本体:

```bash
scp imserver/deploy/probe-readyz.sh root@<SERVER_IP>:/www/server/imserver/probe-readyz.sh
ssh root@<SERVER_IP> 'chmod 755 /www/server/imserver/probe-readyz.sh'
# 手动跑一次,确认退出码 0
ssh root@<SERVER_IP> '/www/server/imserver/probe-readyz.sh; echo exit=$?'
```

**注意宝塔 API 的 IP 白名单**:`/www/server/panel/config/api.json` 里 `limit_addr` 为空时
任何 IP 都调不通(报 `IP校验失败`),需要在面板「设置 → API 接口」里加上调用方 IP
(本机用 `127.0.0.1`)。另:面板开了 SSL 时 API 地址是 `https://127.0.0.1:<端口>`,不是 http。

## 11. 灰度三项手测脚本

核对单里「单设备互踢 / 封禁拒连 / 拉黑拦截」三项原先只能双端手点,现在有可重复的脚本:

```bash
scp imserver/scripts/verify_graylist.py root@<SERVER_IP>:/root/
ssh root@<SERVER_IP> 'set -a; . /www/server/imserver/imserver.env; set +a; \
  /root/bench-venv/bin/python /root/verify_graylist.py --uid-a 7 --uid-b 8'
```

- 只碰两个隔离测试号的 IM 状态,结束自动还原封禁键与双向黑名单(幂等,可反复跑);
- 断言的是服务端契约:帧类型、错误码(40301/40302)、关闭码(4001/4003)、对端是否收到消息;
- 退出码 0 = 全过;`--only multi|ban|blacklist` 可单跑。

## 12. 聊天图片签名 URL 与 30 天清理(2026-10-26)

聊天图片不再是「公开永久 URL」:访问 `/media/chat/**` 必须带 `?e=<过期>&s=<签名>`,
签名由服务端按 `HMAC-SHA256(secret, path + "\n" + e)` 生成,`e` 按整点对齐 + 24h。

### 12.1 环境变量(两端必须一致)

| 变量 | Django `.env` | imserver `imserver.env` | 说明 |
|---|---|---|---|
| `IM_MEDIA_SIGN_SECRET` | 必填 | 必填 | `openssl rand -hex 32`;两边不一致的表现是**所有聊天图片 403** |
| `IM_MEDIA_SIGN_TTL` | 3600 | 3600 | 签名有效期(秒);按整点对齐,实际至少 1 小时 |
| `CHAT_IMAGE_RETENTION_DAYS` | 30 | — | 保留期;`0` = 只清孤儿与残留 |

### 12.2 nginx

把 `imserver/deploy/nginx-media-sign.conf` 的两段 `location` 粘进站点 `server{}`,
**放在 `location ^~ /media/` 之前**,然后 `nginx -t && nginx -s reload`。

- 生产 nginx 没有 `secure_link` 模块(实测只有 `--with-http_auth_request_module`),
  不要照抄网上的 `secure_link` 配置,`nginx -t` 会报 unknown directive;
- **alias 必须写成 `.../media/chat/`**(带 `chat` 后缀):nginx 会把 location 前缀
  `/media/chat/` 整段替换成 alias,写成 `.../media/` 会去找 `media/2026/10/x.jpg`
  —— 签名通过但 404(2026-10-26 部署实测踩到);
- 只改 `/media/chat/` 这一段,**别动**通用 `location ^~ /media/` 的 alias(用 sed 批量替换
  会把它也改成 `media/chat/`,用户头像和广场图立刻全 404);
- 验签子请求打到 `127.0.0.1:8000`,gunicorn 没起时聊天图片会整体 403(其它图片不受影响)。

### 12.3 验证

```bash
# 1) 无签名 → 403
curl -s -o /dev/null -w '%{http_code}\n' http://<SERVER_IP>/media/chat/2026/10/<文件>
# 2) 用上传接口拿一个带签名的 URL,原样请求 → 200
curl -s -X POST http://<SERVER_IP>/api/v1/im/images -H "Authorization: Bearer <access>" \
  -F "file=@a.jpg" | python3 -c 'import json,sys; print(json.load(sys.stdin)["url"])'
# 3) 把 e 改成过去的时间 → 403
# 4) 双端各发一张图,推送、历史、会话列表都能显示
```

### 12.4 清理(宝塔计划任务,每天 04:00)

```bash
cd /www/wwwroot/chatapp/chatapp && /www/wwwroot/chatapp-venv/bin/python manage.py im_media_cleanup --apply
```

- **默认 dry-run**:第一次上线先手动跑一次不带 `--apply`,看汇总再决定;
- 三类动作:保留期(30 天,删文件 + 行改 `expired`)、孤儿文件(无数据库行且 mtime > 24h)、
  删除残留(行已 `deleted` 但文件还在);
- 用量视图:`manage.py im_media_stats`(各状态条数/字节、磁盘占用与剩余、Top 5 发送者);
- 清理后的图片在聊天里显示加载失败占位,消息本身保留。

### 12.5 存储配额、候选池与磁盘报表(M7,2026-10-28)

本批新增三个命令与两组配置,部署时按顺序做:

```bash
# 1) 迁移:users.0005(Profile.shuffle_key、Photo.bytes)、feed.0003(PostImage.bytes)
python manage.py migrate
# 2) 回填存量照片/动态图的字节数(配额统计依赖它,幂等,可先 --dry-run)
python manage.py media_bytes_backfill
```

宝塔计划任务(与 12.4 的清理并列):

| 时间 | 命令 | 作用 |
|---|---|---|
| 每天 03:40 | `manage.py refresh_shuffle_keys` | 轮换候选池随机键(避免同一批人长期排前面) |
| 每天 04:00 | `manage.py im_media_cleanup --apply` | 聊天图/语音保留期与孤儿清理(已有) |
| 每天 04:10 | `manage.py media_cleanup --apply` | 资料图/广场图的孤儿文件清理 |
| 每天 04:20 | `manage.py media_disk_report --fail-over` | 磁盘报表;超 `MEDIA_DISK_WARN_MB` 退出码 1 |

- 配额:`USER_STORAGE_QUOTA_MB`(默认 200)是**单账号**四类媒体之和,超限上传返回
  **413 + `41301`**;`0` 关闭配额。删除照片或聊天媒体过期后额度自动回收(按库内行统计)。
- 候选池:`CANDIDATE_POOL_SIZE`(默认 200)决定每次从索引里取多少人再抽样;
  新用户注册即带随机 `shuffle_key`,不需要手工初始化。
- 磁盘报表:`media_disk_report` 会分别打印 `photos/` `posts/` `chat/` 目录占用、
  库内四类字节数、分区剩余与告警状态;`--warn-mb` 可临时覆盖告警线。

## 13. 语音消息(2026-10-27)

### 13.1 服务器依赖:ffmpeg

语音上传由 Django 同步转码为 **m4a/AAC 单声道 16kHz 32kbps**,因此服务器必须能执行
`ffmpeg` 与 `ffprobe`:

```bash
# 宝塔:软件商店搜 ffmpeg 安装;或
apt-get update && apt-get install -y ffmpeg
ffmpeg -version && ffprobe -version
```

- 缺失时 `POST /api/v1/im/voices` 返回 **503 + `50302`**,文本与图片不受影响;
- 不需要给 imserver 加任何环境变量(沿用 `IM_MEDIA_PREFIX` / `IM_MEDIA_SIGN_SECRET`);
- 转码发生在 gunicorn worker 内,60 秒音频约 0.2–0.5 秒;上传限流 60 次/小时。

### 13.2 部署顺序

1. 装 ffmpeg 并验证(见上);
2. `python manage.py migrate`(新增 `im_chatvoice` 表);
3. 重建并重启 imserver 镜像(本轮协议新增 `kind=4`,旧镜像会拒收语音);
4. nginx 不用改:`/media/chat/` 的验签与 `/im/api/` 反代已覆盖 `/media/chat/voices/`;
5. 重启 ops,导航里出现「聊天语音」。

### 13.3 验证

```bash
# 1) 能力位:自建分支返回的账号应能发语音(Web 端麦克风按钮出现)
# 2) 上传一段 m4a:拿到签名 URL,duration_ms 是服务端实测值
curl -s -X POST http://<SERVER_IP>/api/v1/im/voices -H "Authorization: Bearer <access>" \
  -F "file=@voice.m4a" -F "duration_ms=12500"
# 3) Web 录一段 → App 播放(验证 webm→m4a 转码与 iOS 播放)
# 4) App 录一段 → Web 播放
# 5) 上滑取消、<1 秒提示、60 秒自动停
# 6) ops「聊天语音」试听后删除 → 聊天里显示占位
```

### 13.4 清理

`im_media_cleanup` 已覆盖语音:默认 30 天(`CHAT_VOICE_RETENTION_DAYS`),
可用 `--voice-retention-days` 单独覆盖;孤儿扫描会把 `ChatVoice.file` 并入 known 集合。

### 13.5 上线记录(2026-10-27)

- **ffmpeg**:服务器是 Alibaba Cloud Linux 3,`dnf` 源里没有 ffmpeg、EPEL 也装不上;
  `johnvansickle` 源在国内只有 ~11KB/s,改用 GitHub 加速镜像下载 BtbN 静态包(约 150MB,
  `gh-proxy.com` 实测 1.8MB/s),只把 `ffmpeg`/`ffprobe` 两个二进制装到 `/usr/local/bin`
  (不要覆盖系统库,也不要装 rpmfusion,避免污染生产依赖):
  ```bash
  curl -sL -o /tmp/ffmpeg.tar.xz \
    "https://gh-proxy.com/https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz"
  tar -xJf /tmp/ffmpeg.tar.xz -C /tmp/ffmpeg-gh --strip-components=1
  install -m 755 /tmp/ffmpeg-gh/bin/ffmpeg /usr/local/bin/ffmpeg
  install -m 755 /tmp/ffmpeg-gh/bin/ffprobe /usr/local/bin/ffprobe
  ```
- **镜像**:本地 `docker build -t imserver:<sha>` 后 `docker save` + `scp` + `docker load`
  (2C2G 上直接编译太慢);`/www/server/imserver/.env` 的 `IMSERVER_IMAGE` **必须同步改**,
  否则 `docker compose up -d` 仍会拉起旧镜像(本次先踩了一次,容器还是 `a2332dd`)。
- **验证结果**:上传 201(`duration_ms` 为 ffprobe 实测)、签名 URL 200、无签名 403;
  WS 以 u7 发 `kind=voice` 收到 ack,再用 u8 读历史得到 `kind=voice` + 读时签名 URL;
  `readyz=200`;清理 dry-run 汇总含「语音保留期」;imserver 近 10 分钟无 error。
- **版本配置**:`.env` 显式写入 `MIN_APP_VERSION=1.0.0`/`LATEST_APP_VERSION=1.0.0`/
  `APP_DOWNLOAD_URL=http://47.116.114.110/chatapp-1.0.0.apk`(APK 放在 Web 根目录);
  `/api/v1/app/config` 已返回这三个值。
- **仍未完成**:`SMS_DEV_MODE=0` 需要先接真实短信商(当前代码只有开发模式,置 0 会让
  所有人收不到验证码);全量切换 `IM_SELF_GRAYLIST=all` 待产品确认后再执行。

---

## 14. 安全加固(2026-10-28)

### 14.1 新增迁移

| 版本 | 文件 | 内容 |
|---|---|---|
| 3 | `003_session_version.sql` | `im_user.session_version BIGINT NOT NULL DEFAULT 0` |
| 4 | `004_pair.sql` | `im_pair(user_a,user_b,created_at)` 主键 `(user_a,user_b)` |

`imserver --migrate` 会自动应用;旧镜像不认识新列/新表,但不会因此报错,回退镜像时
可以保留表结构(不要手工 drop,避免再次上线又要重放)。

### 14.2 新增环境变量

```dotenv
# 单账号每分钟发送上限(跨连接共享,Redis 计数);<=0 关闭
IM_SEND_PER_MINUTE=120
# 聊天媒体签名有效期;生产必须配 IM_MEDIA_SIGN_SECRET(与 Django 完全一致)
IM_MEDIA_SIGN_TTL=3600
```

### 14.3 上线顺序(必须按这个顺序)

1. 部署 Django 新版本并 `python manage.py migrate`(会加 `moderation.0002`、`accounts.0003`);
2. 构建/加载 imserver 新镜像,**先显式跑迁移**(entrypoint 不会自动迁移):
   ```bash
   cd /www/server/imserver
   docker compose run --rm imserver --migrate
   docker compose up -d
   ```
3. **立刻**执行 `python manage.py im_sync_pairs`(把现有配对写入 `im_pair`,并补齐缺失的 `im_user` 行);
   不跑这一步,所有已配对老用户会收到 40302「无法发送」;
4. 观察日志:正常配对用户不应出现 40302;旧设备重连应出现 40101(被顶下线);
5. 再按 `docs/security/2026-10-27-api-security-audit.md` §10 逐项复核。

### 14.4 回退

- 回退镜像到旧版本即可(旧代码不读 `session_version`、不查 `im_pair`);
- 若只想临时关闭配对校验:没有单独开关,需回退镜像;不建议用「清空 im_pair」绕过
  (那等于把 H4 重新打开)。

### 14.5 排查

| 现象 | 先查 |
|---|---|
| 正常配对用户发送 40302 | `im_pair` 是否有该对;`im_sync_pairs` 是否跑过 |
| 所有设备重连 40101 | `im_user.session_version` 与 token `sv` 是否一致;Django 登录任务是否成功 |
| 发图/发语音 42201 | `IM_MEDIA_PREFIX` 与 Django `MEDIA_BASE_URL + /media/chat/` 是否一致 |
| 图片 403 | `IM_MEDIA_SIGN_SECRET` 两侧是否一致、`IM_MEDIA_SIGN_TTL` 是否过期 |



