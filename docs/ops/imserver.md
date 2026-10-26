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
IM_ALLOWED_ORIGINS=http://<SERVER_IP>
IM_IO_THREADS=2
IM_DB_THREADS=4
IM_DB_POOL=8
IM_MAX_CONN_PER_IP=20
IM_AUTH_RATE=1
IM_AUTH_BURST=60
IM_MAX_FRAME=8192
IM_TEXT_MAX=2000
```

- `IM_JWT_SECRET` 必须与 Django 的 `IM_SELF_SECRET` **完全一致**;
- `IM_INTERNAL_SECRET` 必须与 Django 的 `IM_SELF_INTERNAL_SECRET` **完全一致**;
- `IM_ALLOWED_ORIGINS` 只影响带 `Origin` 头的浏览器 WS;原生 App 不带 Origin。
  站点换域名/HTTPS 后要同步改。

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

