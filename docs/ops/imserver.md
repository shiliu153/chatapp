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
# 内部管理接口(/internal/*)允许的来源网段;容器部署时 Django 的源地址不是回环
IM_INTERNAL_ALLOW=127.0.0.1,::1
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
# 聊天文字敏感词表(批次 Q);默认就是镜像里打包的那份,留空/文件不存在 = 不启用
# IM_SENSITIVE_WORDS_FILE=/usr/local/share/imserver/data/sensitive_words.txt
# 聊天图片 URL 前缀:必须与 Django 的 MEDIA_BASE_URL + /media/chat/ 一致;必填,缺失启动失败
IM_MEDIA_PREFIX=https://<SERVER_IP>/media/chat/
# 离线新消息推送事件(C-1):空 = 关闭;配了才会在「目标不在线」时回调 Django
# IM_PUSH_URL=http://127.0.0.1:8000/internal/push/new-message
# IM_PUSH_TIMEOUT_MS=2000
# IM_PUSH_QUEUE=256
```

- `IM_JWT_SECRET` 必须与 Django 的 `IM_SELF_SECRET` **完全一致**;
- `IM_INTERNAL_SECRET` 必须与 Django 的 `IM_SELF_INTERNAL_SECRET` **完全一致**;
- **`IM_REDIS_URL` 支持口令(2026-11-05,E-6②)**:写成 `redis://:口令@host:6379/2`
  (Redis 6 ACL 也可以 `redis://用户名:口令@host:6379/2`);口令里的 `@`、`:`、`/` 用百分号编码
  (`@` → `%40`)。配了口令后 imserver 启动时会先 `AUTH`,失败直接启动失败并打印
  `redis AUTH failed`——**不会静默降级**。给 Redis 开 `requirepass` 时,Django 侧
  `REDIS_URL` 也要同样带口令(两侧都改,只改一边会一半接口 500);
- `IM_MEDIA_PREFIX` 必须与 Django 的 `MEDIA_BASE_URL` 拼上 `/media/chat/` **完全一致** ——
  服务端按这个前缀校验图片 URL,不一致时客户端发图会被 `42201` 拒掉;
- **`IM_PUSH_URL`(C-1 推送)**:配了才会在「消息落库 + 目标不在线」时回调 Django 的
  `/internal/push/new-message`(HMAC 用同一个 `IM_INTERNAL_SECRET`);**空 = 关闭**。
  推送在独立线程入队发送,**不阻塞发送路径**,队列满丢事件并记 `im_push_total{result="dropped"}`;
  口径与排障见 [push.md](push.md)。
- `IM_ALLOWED_ORIGINS` 只影响带 `Origin` 头的浏览器 WS;原生 App 不带 Origin。
  站点换域名/HTTPS 后要同步改。**不配也不是「全放行」**:没有白名单时按同源校验
  (`Origin` 的 host 必须等于 `Host` 头),跨站页面会被 403 拒掉。
- `IM_TRUSTED_PROXIES`(默认 `127.0.0.1,::1`)决定「谁有资格写 `X-Real-IP`」:
  只有直连对端命中这个列表(支持 CIDR)时才采信该头,否则一律用真实对端地址。
  这样即使有人绕过 nginx 直连 9100,也伪造不了单 IP 连接数与鉴权令牌桶的 key。
  nginx 不在同一台机器时,把它的出口 IP/网段加进来(例如 `10.0.0.0/8`)。
  **不要显式置空**:那会让所有连接都按对端地址计数,nginx 反代时全站挤在
  `127.0.0.1` 一个 key 上(启动日志会打 `trusted_proxies_empty` 警告)。
- `IM_INTERNAL_ALLOW`(默认 `127.0.0.1,::1`)决定「谁可以调 `/internal/*`」,支持
  IP 与 CIDR,非法条目**启动即失败**。Django 在容器里时源地址是 `172.28.0.x` 而不是
  回环,只写回环会让 `user_sig` 503、配对/封禁/踢人全部静默失败(H-1)。容器部署写
  compose 子网(如 `172.28.0.0/16`);**来源网段只是第一道闸,HMAC 校验照旧**。
- `IM_ALLOW_PUBLIC_BIND`(默认 `0`):`IM_LISTEN_WS`/`IM_LISTEN_HTTP` 写成非回环地址
  时**必须显式置 1**,否则启动直接报错。9101 的内部接口靠「来源网段 + HMAC」保护,
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
# 自建 IM 是唯一后端(腾讯分支已于 2026-11-08 删除,不再有 IM_BACKEND / IM_SELF_GRAYLIST)
IM_SELF_URL=http://127.0.0.1:9101
IM_SELF_WS_URL=ws://<SERVER_IP>/im/ws
IM_SELF_HTTP_URL=http://<SERVER_IP>/im/api
IM_SELF_SECRET=<与 IM_JWT_SECRET 一致>
IM_SELF_INTERNAL_SECRET=<与 IM_INTERNAL_SECRET 一致>
IM_SELF_TOKEN_TTL=86400
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

## 4. IM 出问题时的回退(回退镜像 / 回退后端 SHA)

> **腾讯云 IM 分支已于 2026-11-08 删除(backlog D-4)**:不再存在「切回腾讯」这条路,
> 也**不要**再去找 `IM_BACKEND` / `IM_SELF_GRAYLIST` 这两个环境变量(它们已从代码里删掉,
> 写了也不会生效)。回退只有两条:回退 **imserver 镜像 tag**,或回退 **后端 SHA**。

```bash
# A. imserver 出问题(崩溃/协议不兼容/发版后异常):回退镜像 tag
cd /www/server/imserver
# 把 .env 里的镜像 tag 改回上一个已知good版本(迁移不回滚,代码必须向前兼容)
docker compose up -d imserver
curl -s -o /dev/null -w 'readyz=%{http_code}\n' http://127.0.0.1:9101/internal/readyz

# B. Django 侧出问题(IM 副作用任务/凭证签发):回退后端 SHA
cd /www/wwwroot/chatapp && git fetch origin && git reset --hard <上一个 master SHA>
SC=/www/server/panel/pyenv/bin/supervisorctl
$SC restart chatapp-web:chatapp-web_00
$SC restart chatapp-celery:chatapp-celery_00

# C. 验证:凭证接口必须返回 backend=self + token,WS 必须 101
curl -s -X POST http://<SERVER_IP>/api/v1/im/user_sig -H "Authorization: Bearer <token>"
# → {"backend":"self","token":"...","ws_url":"...","http_url":"...","im_user_id":"u21","expire":86400}
```

**顺序:先止血(停/回退 imserver),再看要不要回退后端。** 两个进程(web + celery)都要重启:
`.env` 只在进程启动时读一次,只重启 gunicorn 会让异步副作用仍按旧配置跑。

**坑 1:supervisor 的程序名带组前缀。** `supervisorctl restart chatapp-web` 会报
`ERROR (no such process)`,必须写 `chatapp-web:*`(或全名 `chatapp-web:chatapp-web_00`)。

**坑 2:停机期间的外部表现**(2026-10-26 实测):`/im/api/*` 与 `/im/ws` 都返回 **502**
(nginx 上游不可用),不是 401/503 —— 排查时别误判成鉴权问题。

**数据影响**:`chatapp_im` 库里的消息不受镜像回退影响(迁移不回滚,只要求代码向前兼容);
回退后端 SHA 也不会丢数据,但**新版本写入的新字段/新会话状态**可能被旧代码忽略,回退前先确认。
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
IM_DB_CONNECT_WAIT_MS=60000  # 启动时连不上 MySQL 的最长重试窗口(每 2s 一次);0=立即失败
```

`IM_DB_CONNECT_WAIT_MS` 解决的是**启动期**问题:DB 未就绪时进程不再直接退出,
避免 Docker 指数退避把重启间隔拉到 60s、DB 恢复后还要再等一个退避周期(2026-11-01 实测多等 47s)。

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
| 周期 | 每分钟调用一次;**脚本内部失败隔 30s 复测一次**(2026-11-05 改,见下) |
| 目标 | 默认两个:`im=http://127.0.0.1:9101/internal/readyz`、`api=http://127.0.0.1:8000/api/v1/health`(`IM_PROBE_TARGETS` 可改) |
| 判定 | 首轮全健康即退出;有失败则 30s 后复测,两次都失败才算 1 次,计数到 2 发告警 |
| 告警 | 写 `/www/wwwlogs/imserver_probe.log` + 发**邮件**(`/opt/notify`,与 22:00 日报同链路) |
| 去重 | 同一事件只告警一次;恢复时清零并记一行 `RECOVERED` |
| 日志 | `/www/wwwlogs/imserver_probe.log`(超 1MB 自动只留最后 500 行) |
| 环境文件 | `/www/server/imserver/probe.env`(600):`IM_PROBE_NOTIFY_CONFIG` / `IM_PROBE_TARGETS` 等;**别写进计划任务命令**(面板任务记录存 sqlite,UI 和备份都能看到) |

> 2026-11-05(E-4 ②)两处改动:① 粒度从「每分钟 2 次、连续 2 轮(≈2 分钟)才告警」降到
> **30 秒复测**,单次故障 30~35 秒内发信 —— 旧判定实测漏报过一次 90 秒宕机;
> ② 通知通道从「群机器人(一直没配,告警只落日志)」改成**邮件**,复用服务器日报的
> `/opt/notify` 链路(用户 2026-11-05 决定不接机器人)。`IM_PROBE_WEBHOOK` 已废弃。
> 与 Prometheus 那条通道(`ApiDown`:抓取 15s + `for: 30s`)互为兜底。

> **为什么不能靠退出码告警**:宝塔生成的包装脚本(`/www/server/cron/<md5>`)无论任务本身
> 退出码是多少都以 `rm -f` 收尾、固定返回 0,面板收不到失败信号。所以告警必须在脚本里自己发。

实测(2026-10-26,旧判定):正常路径退出 0、计数清零;把 `IM_PROBE_URL` 指到死端口模拟故障,
第 1 轮只记录、第 2 轮打 ALERT 并退出 1、第 3 轮不再重复告警。
2026-11-05 改成 30s 复测后,同一次模拟故障在 **~30 秒**后就会发信(不再需要等两分钟)。

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
  所有人收不到验证码)。IM 侧已全量走自建(灰度开关于 2026-11-08 随腾讯分支一起删除)。

---

## 14. 安全加固(2026-10-28)

### 14.1 新增迁移

| 版本 | 文件 | 内容 |
|---|---|---|
| 3 | `003_session_version.sql` | `im_user.session_version BIGINT NOT NULL DEFAULT 0` |
| 4 | `004_pair.sql` | `im_pair(user_a,user_b,created_at)` 主键 `(user_a,user_b)` |
| 5 | `005_device_session.sql` | `im_device_session(user_id,client_type,version)` 主键 `(user_id,client_type)`;并从 `im_user.session_version` 回填每个用户的两行(`app` / `web`,版本同旧值) |

> **第 5 条是多端在线(K-1/K-2,2026-11-08)的迁移**:会话版本从 `im_user.session_version`
> 一列下沉到 `im_device_session`,按 `(uid, client_type)` 各存一份。`im_user.session_version`
> 保留但**不再参与鉴权**(旧镜像还在读它,回退时靠它兜底)。多端同步的两个新下行帧见本文件 §18。

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
| 某端重连 40101 | 会话版本在 `im_device_session`,按 `(uid, client_type)` 各存一行:token 的 `sv` 要与**本端**那一行的 `version` 一致(`ct` 缺省按 `app` 算);该端从没登录过 = 没有那一行 = 一律拒;Django 登录任务是否成功 |
| **所有**端重连 40101 | 先确认迁移 `005_device_session.sql` 跑过(没跑就没有任何会话行);再看 Django 是否两边都没同步成功 |
| 发图/发语音 42201 | `IM_MEDIA_PREFIX` 与 Django `MEDIA_BASE_URL + /media/chat/` 是否一致 |
| 图片 403 | `IM_MEDIA_SIGN_SECRET` 两侧是否一致、`IM_MEDIA_SIGN_TTL` 是否过期 |

## 15. 已读回执(2026-11-04)

已读态的**唯一事实来源**是 `im_conversation_state.read_seq`(每个 owner 一行,语义是「**我**读到哪」)。
`unread`(我没读的条数)与 `read_seq`(我读到哪)是两条独立链路,别混。

> `docs/api/` 里不写这些:WS 帧与 `/im/api/*` 都是 imserver 的内部契约,不归 `/api/v1` 门禁管,
> 归属本文件。

### 15.1 上行 `read` 帧(客户端 → 服务端,2026-10 起就有)

```json
{"v":1,"type":"read","id":"read-1720000000000","data":{"peer":"u9","seq":0}}
```

- `seq = 0` = 「读到该会话最新」,服务端取 `im_conversation.last_seq`;
- 落库是 `GREATEST(read_seq, ?)`,**单调不回退**(乱序到达的旧帧不会把已读推回去);
- 会话不存在时回 `ack{ok:false}`(没有会话就没有已读可记)。

### 15.2 下行 `read` 帧(服务端 → 被读的一方,2026-11-04 新增)

```json
{"v":1,"type":"read","data":{"peer":"u7","seq":123}}
```

- 触发:任何 `read` 帧落库成功后,若对端在线就推一帧;
- `peer` = **读消息的人**(即收帧者的对端),`seq` = 他读到的位置(回读实库后的真实值);
- **没有 `id` 字段**:服务端主动推,不要求 ack,客户端也不要回;
- 对端离线时不排队,靠 §15.3 补拉。

### 15.3 `GET /im/api/conversations` 新增字段 `peer_read_seq`

每个 item 多一个整数 `peer_read_seq`(0 = 对端从没读过):

```json
{"peer":{"id":"u9","nickname":"…","avatar":"…"},"unread":0,"last_seq":42,
 "peer_read_seq":17,"updated_at":1720000000000}
```

实现是 `list` 的 SQL 多一个 `LEFT JOIN im_conversation_state ps`(同一 `conv_id`、owner 换成对端,
走 `(owner_id,conv_id)` 唯一键,等值查找,不会因为多这个 JOIN 扫全表)。

客户端口径:`seq <= peer_read_seq` 的**我方**消息 = 已读;打开会话/重连后拿这个字段补一次。

### 15.4 `read` 帧限流

每次 `read` 都会给对端推一帧,所以每连接有令牌桶 **2/s、突发 30**(`WsSession::read_bucket_`),
超限**静默丢弃**(`read` 幂等,下一次打开会话还会再发;回错误帧只会让客户端白重试)。
实测:连发 40 帧约 29 个成功、其余静默丢。

### 15.5 验证

```bash
# unit + DB 测试
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test.sh
# WS 集成(含已读回执四条)
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_ws.sh
# HTTP 集成(含 test_history.py 里的实时帧 + peer_read_seq 断言)
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh
```

`tests/integration/test_read.py` 覆盖:下行帧 / 旧值不回退 / 离线补拉 / 限流。

### 15.6 排查

| 现象 | 先查 |
|---|---|
| 一直不显示「已读」 | 对端是否真的打开过会话;`GET /im/api/conversations` 里 `peer_read_seq` 是否为 0 |
| 已读显示后又消失 | 客户端是否把「只增不减」做丢了(收到更小的 `seq` 必须忽略) |
| 对端收不到实时帧 | 对端 WS 是否在线;`im_conversation_state` 里读者那行是否存在 |
| 大量 `read` 无响应 | 撞上 2/s 限流(静默丢弃,不是错误) |

## 16. 聊天记录搜索 `GET /im/api/search`(2026-10-27 交付,2026-11-05 补文档)

聊天记录搜索**不经过 Django**,由 imserver 直接提供;App(`app/lib/features/chat/search_page.dart`)
与 Web(`web/src/features/chat/SearchPage.vue`)共用这一个接口,入口由 IM 能力位
`capabilities.search` 控制(自建后端恒为 true)。交付记录见 `docs/milestones.md`(2026-10-27)。

> 为什么写在这里:`/im/api/*` 与 WS 帧一样是 imserver 的内部契约,`docs/api/` 的分册门禁
> (`ApiDocsCoverageTests`、`test_schema_contract.py`)只比对 `/api/v1`,写进去也不会被校验;
> `docs/api/im.md` 只负责 Django 侧的「发凭证 + 传媒体」三个接口(同 §15 开头的说明)。

### 16.1 鉴权与地址

- 基址 = `POST /api/v1/im/user_sig` 返回的 `http_url`(生产 `https://<域名>/im/api`);
- 请求头 `Authorization: Bearer <IM token>`:用的是 `user_sig` 发的 JWT,**不是** Django 的 access token;
- 返回 401 的情况:没带或前缀不对、JWT 过期/签名错、会话版本 `sv` 与
  `im_device_session` 里 `(uid, ct)` 那一行的 `version` 不一致(被别的设备顶下线;
  `ct` 缺省按 `app` 算)、账号在 IM 侧被拉黑(`im:block:*`)。

### 16.2 请求参数

| 参数名称 | 必填 | 类型 | 描述 |
|---|---|---|---|
| q | 是 | String | 关键词。服务端先 `trim`;为空或超过 **150 字节**(UTF-8,约 50 个汉字)返回 422 |
| limit | 否 | Integer | 每页条数,默认 **20**,范围 1~50(超出被截断) |
| before_id | 否 | Integer | 游标:只返回 `msg_id` **严格小于**该值的更旧消息;首页不传 |

```bash
# 凭证从 POST /api/v1/im/user_sig 拿(见 docs/api/im.md 6.1),这里用它的 token 与 http_url
curl -G 'https://<域名>/im/api/search' \
  --data-urlencode 'q=火锅' \
  --data 'limit=20' \
  -H 'Authorization: Bearer <user_sig 里的 token>'
```

### 16.3 响应

```json
{
  "items": [
    {
      "msg_id": "900123",
      "seq": 42,
      "from": "u9",
      "to": "u7",
      "ts": 1720000000000,
      "revoked": false,
      "kind": "text",
      "text": "火锅店在楼下",
      "from_profile": {"nickname": "小九", "avatar": "https://…"},
      "peer": {"id": "u9", "nickname": "小九", "avatar": "https://…"}
    }
  ],
  "has_more": true
}
```

| 参数名称 | 类型 | 描述 |
|---|---|---|
| items | Array | 命中的消息,新 → 旧 |
| items[].msg_id | String | 消息 id;翻页时把本页最后一条原样传给 `before_id` |
| items[].seq | Integer | 会话内序号(与该会话历史接口一致) |
| items[].from / items[].to | String | IM 账号 `u{user_id}` |
| items[].ts | Integer | 发送时间,毫秒时间戳 |
| items[].kind | String | 搜索只返回 `text` |
| items[].text | String | 消息正文;命中片段不做高亮,客户端自己标 |
| items[].revoked | Boolean | 恒为 false(已撤回的不进结果) |
| items[].from_profile | Object | 发送者昵称/头像(用户行存在时才有) |
| items[].peer | Object | **会话对端**(相对当前账号)的 id/昵称/头像,点结果跳转用 |
| has_more | Boolean | 还有更旧的结果(服务端多取一条判定,不是用 `len(items)==limit` 猜) |

字段口径与 `GET /im/api/messages` 的历史消息对象一致(只多一个 `peer`),客户端复用同一个
消息模型即可,不要为搜索另建一套。

### 16.4 搜索口径(排序与过滤)

- **只搜文本**(`kind=1`):图片、语音、系统灰条、贴纸不参与;
- 已撤回的消息不可见(`revoked_at IS NOT NULL` 排除);
- **我删掉的会话**整段不可见(`im_conversation_state.deleted=1`);
- 我拉黑的对端消息不出现(`im_blacklist` 反连接);
- 关键词按 `LIKE '%关键词%'` 匹配,用户输入里的 `%`、`_`、`!` 会被转义
  (`imserver/src/util/like.h`,转义符选 `!`),搜「100%」不会变成通配;
- 排序 **新 → 旧**(`msg_id DESC`),翻页只认 `before_id`;
- 搜索范围仅限**已有会话**:从没聊过的人不会出现。

### 16.5 限流

每账号令牌桶 **1 次/秒、突发 20**(约 60 次/分钟),超限返回 `429 + 42901`。
App/Web 都有 300ms 防抖,正常输入不会撞到;多个标签页同时搜才可能触发。

### 16.6 错误码

| 错误码 | HTTP | 描述 | 处理建议 |
|---|---|---|---|
| 40101 | 401 | 未登录 / 令牌过期 / 被顶下线 / 被拉黑 | 重新 `POST /api/v1/im/user_sig` 换 token 并重连 |
| 42201 | 422 | 关键词为空或超长 | 客户端先 `trim` 并限制长度 |
| 42901 | 429 | 搜索过于频繁 | 退避后再搜,不要立即重试 |
| 40401 | 404 | 路径不对 | 检查 `http_url` 与 `/search` 的拼接 |

> imserver 的错误体是 `{"code": …, "message": …}`(**没有** `request_id`),
> 与 Django `/api/v1` 的统一错误信封不同;客户端不要假设两者结构一致。

### 16.7 验证

```bash
# HTTP 集成(含中文命中/排序/游标分页/对端资料/撤回不可见/空关键词/未认证/限流)
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh
```

断言在 `imserver/tests/integration/test_search.py`;unit 侧 `like_test.cpp` 覆盖 `%`/`_`/`!` 转义。

### 16.8 排查

| 现象 | 先查 |
|---|---|
| 明明有这条消息却搜不到 | 是不是图片/语音;是否已撤回;会话是否被自己删除;是否拉黑了对方 |
| 401 | `user_sig` 的 token 是否过期;是否在别的设备登录把 `sv` 顶掉 |
| 422 | `q` 是否为空;URL 解码后是否超过 150 字节 |
| 429 | 是否绕过了 300ms 防抖;是否多个标签页同时搜 |
| 翻页重复或漏条 | 是否把上一页最后一条的 `msg_id` 原样传给 `before_id`(严格小于) |
| 搜「100%」命中一切 | 客户端是否在本地又拼了一次 `%`(服务端已转义,前端不要预处理) |

## 17. 自定义消息 `kind=2 custom`(灰条 / 贴纸,2026-11-07)

`custom` 是 imserver 里唯一的「非文本非媒体」消息类型,库里存成 `kind=2`,
`body` 是客户端/服务端给的 JSON 原样。两类用法:

| 用法 | `custom.type` | 谁发 | 形态 |
|---|---|---|---|
| 系统灰条(配对/封禁/举报处理/评论回复提醒) | `match_notice` / `ban_notice` / `report_handled` / `post_commented` / `post_replied` | **只有服务端**:Django 经 HMAC 内部接口 `POST /internal/send` | 居中灰条,不进搜索、不推离线推送 |
| 聊天贴纸(批次 J) | `sticker` | **客户端**(App / Web) | `{"type":"sticker","id":"sticker_01"}`,资源在客户端本地 |

### 17.1 闸门结论:持久化与补拉都是「是」(2026-11-07 核实)

J-1 闸门要回答两件事,结论都是通过(代码 + 运行时实证):

| 问题 | 结论 | 证据 |
|---|---|---|
| `kind=2` 的 content 是否落库 | **是** | `store/message_repo.cpp::insert` 把 `kind` 与 `body` 一起写 `im_message`;`kind` 是 `TINYINT`(`migrations/001_init.sql`),无枚举约束。单测 `MessageServiceTest.StoresCustomAsKindTwo` |
| `GET /im/api/messages` 与离线补拉是否带回 `custom` | **是** | `net/http_api.cpp::message_json` 对 `kind==2` 输出 `{"kind":"custom","custom":<body>}`;历史接口、会话列表 `last_message` 都走它。集成测试 `tests/integration/test_sticker.py`(对端离线时发贴纸 → 再拉历史) |

**但计划里「imserver 零改动」的前提不成立**:上行 `send` 帧原本只认
`text` / `image` / `voice`(见下),`custom` 只能由服务端内部产生。所以贴纸走
`kind=2` 需要 imserver **放开上行白名单**(本批唯一一处服务端改动,约 20 行),
不需要新增消息类型、不需要迁移。

### 17.2 上行 `send` 帧(客户端 → 服务端)

```json
{
  "v": 1,
  "type": "send",
  "id": "local-1720000000000",
  "data": {
    "client_msg_id": "local-1720000000000",
    "to": "u2",
    "kind": "custom",
    "custom": {"type": "sticker", "id": "sticker_01"}
  }
}
```

**白名单规则**(`net/ws_server.cpp::handle_send` + `is_sticker_id`):

- `kind` 只认 `text` / `image` / `voice` / `custom`;
- `kind=custom` 时 `custom.type` 必须等于 `sticker`,否则 `42201 暂不支持该消息类型`;
- `custom.id` 必须形如 `sticker_` + **两位数字**(`sticker_01` … `sticker_99`),
  否则 `42201 贴纸 id 不合法`;
- 落库时**只保留 `{"type","id"}` 两个键**,客户端夹带的其它字段一律丢弃。

> 为什么必须白名单:不校验就等于让任何账号能给对端发一条
> `{"type":"match_notice","desc":"你们已互相喜欢"}` 的**假系统灰条**。
> 灰条是服务端身份的象征,客户端不能有这条通道。

### 17.3 下行帧与历史

下行实时帧、`GET /im/api/messages` 历史、会话列表 `last_message` **三者同构**:

```json
{
  "v": 1,
  "type": "message",
  "data": {
    "msg_id": "900127",
    "seq": 45,
    "from": "u2",
    "to": "u9",
    "kind": "custom",
    "ts": 1720000000003,
    "revoked": false,
    "custom": {"type": "sticker", "id": "sticker_01"},
    "from_profile": {"nickname": "小九", "avatar": "…"}
  }
}
```

- 贴纸**只传 id**,图片是打包进两端的静态资源(`app/assets/stickers/` 与
  `web/public/stickers/`,逐字节一致,`scripts/check_stickers.py` 把关);
- 客户端按 id 取本地资源,**未知 id 降级成「[贴纸]」文本**(老版本收到新贴纸);
- 贴纸不参与搜索(`/im/api/search` 只看 `kind=1`);
- 贴纸**不触发离线推送**(`PushNotifier` 对 `kind=2` 与 `from=0` 一律跳过;
  本项目推送通道本来就固定 `off`);
- 撤回对贴纸同样生效(2 分钟窗口),撤回后历史里只剩 `revoked=true`。

### 17.4 验证

```bash
# unit(含跨栈帧 fixture 契约:message_sticker / send_sticker)
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test.sh

# HTTP/WS 集成(贴纸落库 + 历史带回 + 伪造灰条被拒 + id 形状校验)
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh
```

贴纸相关的断言在 `imserver/tests/integration/test_sticker.py`;跨栈帧契约在
`imserver/tests/fixtures/ws/*.json`,三端各有一份契约测试(App / Web / imserver)。

### 17.5 排查

| 现象 | 先查 |
|---|---|
| 发贴纸返回 `42201 暂不支持该消息类型` | imserver 镜像是否已升级到含本批改动的版本(旧镜像不认上行 `custom`) |
| 发贴纸返回 `42201 贴纸 id 不合法` | id 是不是 `sticker_NN` 形状(两位数字);客户端有没有自己拼 id |
| 贴纸在历史里变成「[贴纸]」文本 | 该客户端版本不认识这个 id(资源没打包进去,或 id 比客户端新) |
| 贴纸显示成空白灰条 | 更老的客户端(1.0.9 及以前)把未知 `custom` 当 `ban_notice` 渲染 —— 不会白屏,升级后正常 |
| 贴纸消息在聊天记录搜索里搜不到 | 预期行为:搜索只看 `kind=1` 文本 |

## 18. 多端同步帧 `self_read` / `conversation_deleted`(2026-11-08,批次 K-3)

一个账号可以同时在线 **1 个 App + 1 个网页**(见 [docs/superpowers/specs/2026-11-08-multi-device-session-design.md](../superpowers/archive/specs/2026-11-08-multi-device-session-design.md))。
多端之后有两类状态是「**我自己**在另一端做的事」,必须同步给我的其他端,但对端不该知道。
这两类各有一个专属下行帧,**收帧人都是「我自己的其他端」,不含发起的那条连接**。

### 18.1 `self_read`:我在另一台设备上读到哪

```json
{"v": 1, "type": "self_read", "data": {"peer": "u12", "seq": 42}}
```

- 触发:`handle_read` 落库并**回读** `read_seq` 之后,与发给对端的下行 `read` 帧**同时**发出;
- `peer` 是**会话对端**(`u12`),`seq` 是回读实库后的真实位置(不是请求里带的 seq);
- 收帧端动作:把自己这边与 `peer` 的会话**未读清零**,`read_seq` 只增不减;
- **`peerReadSeq` 一律不动** —— 那一栏是「**对方**读我」,与这一帧无关。

> ⚠️ **不能复用下行 `read` 帧**。`read` 的语义是「**对端**读到 seq」,发给自己的另一台设备
> 会被读成「对方已读」:表现为对方的红点莫名消失、自己的未读不动,是**假已读**。

### 18.2 `conversation_deleted`:我在另一台设备上删了会话

```json
{"v": 1, "type": "conversation_deleted", "data": {"peer": "u12"}}
```

- 触发:`handle_delete` 的 `conversation_delete` 软删成功(`ack ok=true`)之后发出;
- 收帧端动作:把该会话从列表移除(正打开着就退回列表),不必再拉全量;
- **只发给本人的其他端,绝不发给对方**:删会话是单方行为,对方不该知道,更不该因此丢记录。
  `im_conversation_state` 是按 `owner_id` 一行,删的只是**我**这一份。

### 18.3 为什么要两个新帧(而不是复用一个)

| 帧 | 收帧人 | 语义 | 客户端落点 |
|---|---|---|---|
| 下行 `read` | **对端** | 对端读到 seq(把我方气泡标「已读」) | `peerReadSeq` |
| `self_read` | **我自己的其他端** | 我在另一端读到 seq(清我这边未读) | 未读清零,`peerReadSeq` 不动 |
| `conversation_deleted` | **我自己的其他端** | 我在另一端删了会话 | 从列表移除 |

跨栈契约的样例在 `imserver/tests/fixtures/ws/server_to_client.json`(三端各有一份契约测试)。

### 18.4 验证

```bash
# 单元(含跨栈帧契约:self_read / conversation_deleted 与真实序列化逐字段比对)
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test.sh

# 集成(两端并存下的扇出、对端收不到、单端不产生下行、seq 不回退)
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh
```

集成断言在 `imserver/tests/integration/test_self_read.py`。

### 18.5 排查

| 现象 | 先查 |
|---|---|
| 一端读完,另一端红点不消失 | 客户端版本是否含 K-3(旧客户端不认 `self_read`);imserver 镜像是否已升级 |
| 自己读完,对方气泡却显示「已读」 | 有实现把 `self_read` 当成了 `read` 处理 —— 这是假已读,必须修客户端 |
| 另一端删了会话,这一端还在列表里 | 同上:客户端没处理 `conversation_deleted`;先确认 imserver 日志里有 `conversation_delete` 的 ack |
| 对方收到了 `conversation_deleted` | 不该发生:`send_to_other_clients` 只发给本人;**误用 `send_to`(扇出全 uid)才会串到对端** |
| `self_read` 的 seq 比实际已读小 | 客户端拿请求里的 seq 当结果;必须是回读实库后的值(`GREATEST` 语义) |

## 19. 会话置顶 / 免打扰 `POST /im/api/conversations/flags`(2026-11-09,批次 N)

会话列表的两个「个人偏好」:**置顶**(排在列表最前)与**免打扰**(客户端静音图标 + 未读只显示灰点)。
两者都只写 `im_conversation_state` 里**自己那一行**,是**单方**行为 —— 置顶/免打扰不通知对端、
不影响对端看到的任何东西。

> 为什么写在这里:`/im/api/*` 是 imserver 的内部契约,不归 `docs/api/` 的 `/api/v1` 门禁管
> (同 §15 / §16 开头的说明)。`docs/api/im.md` 只有指路一行。

### 19.1 为什么不加 WS 帧

加一个 WS 帧要**三端 fixture 同改**(`imserver/tests/fixtures/ws/*.json` + imserver + App + Web,
三份 CI 各红一次,成本 ×3),而置顶/免打扰是**一天点不了几次的低频写操作**。
所以协议面**一个字都没动**:`imserver/tests/fixtures/ws/*.json` 保持原样,写走 HTTP,
读走既有的 `GET /im/api/conversations`(每项多两个字段)。

代价(已知、可接受):**多端不同步** —— 在 App 上置顶,网页端要等下次拉会话列表才看到。
真需要实时同步时再按 §18 的方式加帧,那时三端一起改。

### 19.2 存储与迁移

迁移 `007_conversation_flags.sql`(版本号 **7**):

```sql
ALTER TABLE im_conversation_state
  ADD COLUMN pinned_at BIGINT NOT NULL DEFAULT 0,   -- 置顶时刻(毫秒),0 = 未置顶
  ADD COLUMN muted TINYINT NOT NULL DEFAULT 0;      -- 免打扰 0/1
```

- 存的是**置顶时间**而不是 bool:排序要按「置顶时间倒序」(后置顶的更靠前),bool 排不出来。
- **不新增索引**:个人项目会话数 < 100,排序表达式可接受;`idx_owner_updated` 本来就不覆盖这个排序
  (它按 `updated_at`,列表一直按 `last_msg_at` 排),所以既没让它失效,也没新拖慢别的查询。
- `muted` / `pinned_at` **不改 `updated_at`** —— 那是「会话活动时间」,标志位变化不是活动。

### 19.3 鉴权与地址

与 `/im/api/conversations|messages|search` **完全同口径**:

- 基址 = `POST /api/v1/im/user_sig` 返回的 `http_url`,路径 `/conversations/flags`,**只接受 POST**;
- `Authorization: Bearer <IM token>`(不是 Django 的 access token);
- 令牌里的 `sv` 与 `im_device_session` 的 `(uid, ct)` 行不一致(被同类端顶下线)、账号被 IM 拉黑 → `401` + `40101`。

### 19.4 请求

| 参数名称 | 必填 | 类型 | 描述 |
|---|---|---|---|
| peer | 是 | String | 会话对端的 IM 账号,形如 `u9`(与 WS 帧、`/im/api/messages?peer=` 同口径) |
| pinned | 否 | Boolean | 置顶开关;**缺省 = 这一项不改**(与 `false` 不同) |
| muted | 否 | Boolean | 免打扰开关;缺省 = 这一项不改 |

```bash
# 凭证从 POST /api/v1/im/user_sig 拿(见 docs/api/im.md 6.1)
curl -X POST 'https://<域名>/im/api/conversations/flags' \
  -H 'Authorization: Bearer <user_sig 里的 token>' \
  -H 'Content-Type: application/json' \
  -d '{"peer":"u9","pinned":true,"muted":false}'
```

只改一个开关就只传一个(另一个保持原值,不会被当成 `false`):

```bash
curl -X POST 'https://<域名>/im/api/conversations/flags' \
  -H 'Authorization: Bearer <token>' -H 'Content-Type: application/json' \
  -d '{"peer":"u9","muted":true}'
```

### 19.5 响应

`200` + **回读实库后的真实值**(不是回显请求参数):

```json
{"pinned": true, "muted": false}
```

语义:

- `pinned` 由假变真时把 `pinned_at` 写成当前毫秒;**已经置顶再置顶一次不重写时间**(幂等,
  否则连点两次会把会话顶到置顶组最前);取消置顶写 0。
- `muted` 直接写 0/1。
- 重复设置同值仍回 `200`,状态不变。

### 19.6 会话列表的两个新字段

`GET /im/api/conversations` 每项多两个字段(`pinned` / `muted`,都是布尔):

```json
{"peer":{"id":"u9","nickname":"…","avatar":"…"},"unread":0,"last_seq":42,
 "peer_read_seq":17,"pinned":true,"muted":true,"updated_at":1720000000000}
```

**排序口径**(服务端已排好,客户端照顺序渲染即可):

```sql
ORDER BY (s.pinned_at>0) DESC, s.pinned_at DESC, c.last_msg_at DESC
```

即:置顶组在前,置顶组内**按置顶时间倒序**(后置顶的更靠前),两组内部都仍按最近消息排。
`pinned_at` 不下发 —— 客户端只需要知道「排在哪一组」,不需要自己再排一次(自己再排反而会与
服务端顺序打架)。

免打扰的**语义只在客户端**:会话行显示静音图标,未读只显示灰点不显示数字。
服务端**不改 `unread` 统计**,也不抑制任何推送(本项目不做离线推送,没有可抑制的通道)。

### 19.7 限流

每账号令牌桶 **1 次/秒、突发 20**(约 60 次/分钟,`HttpApi::flags_table_`),超限 `429 + 42901`。
单列一张表而不是复用读接口的桶:这是写路径,不该和「刷列表」抢同一桶令牌。

### 19.8 错误码

| 错误码 | HTTP | 描述 | 处理建议 |
|---|---|---|---|
| 40101 | 401 | 未登录 / 令牌过期 / 被同类端顶下线 / 被 IM 拉黑 | 重新 `POST /api/v1/im/user_sig` 换 token |
| 42201 | 400 | body 不是合法 JSON 对象 / `peer` 格式错 / `pinned`、`muted` 不是布尔 | 客户端修正请求;`peer` 必须是 `u<数字>` |
| 40401 | 404 | 会话不存在(未配对 / 从没聊过 / 路径拼错) | 会话不存在时不要给用户「置顶」入口;检查 `http_url` 拼接 |
| 40501 | 405 | 用了 GET 等非 POST 方法 | 用 POST |
| 42901 | 429 | 操作过于频繁 | 退避后再试,别连点 |
| 50001 | 500 | 内部错误 | 看 imserver 日志 |

> 注意 `42201` 在这里配的是 **HTTP 400**(不是 422):参数类错误给 400、业务码仍是 42201,
> 与 `/internal/send` 的写法一致。imserver 的错误体是 `{"code","message"}`,**没有** `request_id`。

### 19.9 部署顺序(硬约束)

**迁移 `007` 必须先于新镜像生效**:

```bash
cd /www/server/imserver
docker compose run --rm imserver --migrate   # 1–6 skipped,7 applied
docker compose up -d                          # 再换新镜像
```

原因:新代码的 `SELECT` 读 `pinned_at` / `muted` 两列,**旧表没有这两列会直接报「列不存在」**,
会话列表整页 500。反过来的顺序(先换镜像)不是「降级」而是「故障」。
回滚镜像时迁移**不回滚**(多出来的两列旧代码不读,向前兼容)。

### 19.10 验证

```bash
# unit + DB 测试(flags 写入/回读/幂等/未配对/置顶组排序)
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test.sh

# HTTP 集成(401 / 42201 / 40401 / 顺序 / muted 回显 / 幂等 / 单方)
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh
```

断言在 `imserver/tests/integration/test_flags.py` 与 `message_service_test.cpp` 的
`ConversationFlagsTest.*`;`scripts/verify.sh imserver` 一次跑完 unit + db + 集成 + e2e。

### 19.11 排查

| 现象 | 先查 |
|---|---|
| 置顶了但列表顺序没变 | `im_conversation_state.pinned_at` 是否为 0(写入失败);客户端是否自己又按时间排了一遍 |
| `404 + 40401` | 双方是否已配对;**是否真的聊过**(只有配对没有消息 = 没有会话) |
| `400 + 42201` | `peer` 是否写成 `9`(少了 `u`)或 `u9 ` (带空格);开关是否传了 `"true"` 字符串 |
| 连点置顶反而跳到最前 | 这是设计:`pinned_at` 只在「由未置顶 → 置顶」时写,重复置顶不改时间;若真跳了,说明客户端先发了 `false` 再发 `true` |
| 换台设备看不到置顶 | 已知限制:`/im/api/*` 无实时同步,重拉一次 `GET /im/api/conversations` 即可(见 §19.1) |
| 会话列表整页 500 且日志有 `Unknown column 'pinned_at'` | 部署顺序反了:先跑 `--migrate`(见 §19.9) |

## 20. 聊天文字敏感词(2026-11-09,批次 Q)

聊天的**文字**消息在 imserver 的发送路径上过一遍本地词表,命中就**拒发**。
设计见 `docs/superpowers/specs/2026-11-09-batch-m-q-design.md` §7。

> 为什么在 imserver 而不是 Django:聊天消息由客户端 WS **直连 imserver** 落库,不经过 Django;
> 昵称 / 简介 / 动态 / 评论那套 Django 侧校验够不到聊天正文。所以这一条链路**一个字都没改**,
> 只在 imserver 的 `send` 处理里加了一次文本判断。

### 20.1 词表文件

| 项 | 值 |
|---|---|
| 路径 | `/usr/local/share/imserver/data/sensitive_words.txt`(随镜像打包,见 `imserver/Dockerfile`) |
| 覆盖 | 环境变量 `IM_SENSITIVE_WORDS_FILE`(可指到宿主机挂载的文件,例如 `/data/sensitive_words.txt`) |
| 格式 | UTF-8,**一行一词**;`#` 开头为注释;空行忽略;行尾空白与 CRLF 自动去掉 |
| 大小写 | **ASCII 不敏感**(`FUCK` / `Fuck` / `fuck` 命中同一条);中文按字节精确匹配 |
| 匹配口径 | 子串匹配(词出现在句子任意位置都算),词表里写多长就匹配多长 —— 短词易误伤,宁可写长 |

仓库里的那份(`imserver/data/sensitive_words.txt`)是**示例词表**(26 条暴力 / 毒品 / 诈骗 / 引流类),
文件头写明「主人按需增删」。算法是 Aho-Corasick(AC 自动机,启动时构建一次,
单条消息匹配 O(n),4KB 文本也不到 10µs),词表扩到几千条也不影响发送吞吐。

### 20.2 命中行为

- **只作用于 `kind=text`**:`image` / `voice` / `custom`(贴纸、灰条)**一律不查**
  —— 图片语音已有 `/ops/` 人工抽审,灰条只能由服务端 `/internal/send` 发出。
- 命中 → WS 回 `{"type":"error","data":{"code":42201,"message":"消息包含违规内容"}}`,
  **不落库、不推送、不计未读、不占 seq**(下一条正常消息的 seq 还是接着来)。
- **只拦发送**:`GET /im/api/messages` 的历史照常回放;服务端经 `/internal/send` 发的
  文本(灰条、`python manage.py im_send`)也不过这道闸。
- **文件不存在 / 读不到 / 为空 = 不启用**:启动日志打 `sensitive_words_disabled`(warning),
  聊天不受影响 —— **刻意不 fail-closed**,词库配错不该把整个聊天挂掉。
  日志里 `reason` 分三种:`missing`(路径没这个文件)、`unreadable`(文件在但没读权限,
  常见于容器以非 root 跑而文件是 0600)、`empty`(只有注释/空行)。
  正常加载时打 `sensitive_words_loaded`(`words=<词条数>`)。

### 20.3 指标

`GET :9101/metrics`(只允许回环,与 `/internal/*` 同口径):

```
im_sensitive_blocked_total 3      # 因命中敏感词被拒的发送次数
```

- 长期为 0 且词表非空 → 先看启动日志有没有 `sensitive_words_loaded`;
- 突然变高 → 有人在刷违规词,日志里有 `sensitive_blocked`(`uid` / `to` / `bytes`,
  **不记文本本身**,别把违规内容再抄进日志)。

### 20.4 怎么改词表 / 怎么关掉

```bash
# 1) 改词表:编辑宿主机上的文件(或换一份),然后重启 imserver 容器
vim /www/server/imserver/data/sensitive_words.txt   # 一行一词
docker compose -f /www/server/imserver/docker-compose.yml up -d   # 词表只在启动时读一次

# 2) 想彻底关掉这个功能(两种都行,等价):
#    a. 把词表清空(只留注释/空行也算空)
: > /www/server/imserver/data/sensitive_words.txt && docker compose up -d
#    b. 或者指到一个空文件/不存在的路径
#       IM_SENSITIVE_WORDS_FILE=/data/empty.txt
```

- **改词表必须重启容器**:词表是启动时构建进 AC 自动机的(不重启就是旧词表)。
- 想在不重启的前提下改行为是做不到的,也没必要 —— 这不是热更新场景。
- 部署时若用宿主机文件覆盖,记得把目录挂进容器(compose 的 `volumes:`),
  并保证 `IM_SENSITIVE_WORDS_FILE` 指向**容器内**的路径。

### 20.5 验证

```bash
# unit:AC 中文命中 / 英文大小写 / 词边界 / 4KB 长文本 / 空词表 / 注释与空行 / 真实词表可加载
# db :store / message_service(本次未改,回归用)
# 集成:test_sensitive.py(命中 42201 且不落库不推送 / 不占 seq / 正常文本照发 / 贴纸不受影响 / 内部发的不拦 / 指标)
scripts/verify.sh imserver
```

集成测试用的是**另一份**词表(`imserver/tests/fixtures/sensitive_words_test.txt`,
由 `docker-compose.test.yml` 的 `IM_SENSITIVE_WORDS_FILE` 指过去),
这样主人增删 `imserver/data/sensitive_words.txt` 不会把测试打红。

### 20.6 排查

| 现象 | 先查 |
|---|---|
| 正常聊天被拦 | 词表里是不是有太短的词(如单独的「贷款」「兼职」);日志 `sensitive_blocked` 的 `bytes` 能看出是短消息还是长消息 |
| 什么都不拦(疑似没生效) | 启动日志有 `sensitive_words_loaded` 吗?`IM_SENSITIVE_WORDS_FILE` 指向的路径在**容器里**存在吗? |
| 改了词表没变化 | 没重启容器(词表只在启动时构建) |
| 启动日志刷 `sensitive_words_disabled` | 看 `reason`:`missing` = 路径不对/没挂载;`unreadable` = 权限(文件要 `a+r`,镜像里已 `chmod a+rX`);`empty` = 只有注释。三种都属于「功能关闭」的正常提示,不是错误 |
| 贴纸被拦? | 不会:过滤只走 `kind=text`;贴纸被拒是另外的 `42201`(id 形状 / `type` 不是 `sticker`),见 §17 |
