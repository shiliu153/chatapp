# 自建 IM：C++ 服务端替换腾讯云 IM（设计）

日期：2026-10-20 · 状态：设计待评审
上游：现网聊天完全依赖腾讯云 IM（Flutter/Web 双端 SDK + Django REST 管理端），
        成本、数据主权与「已读回执需旗舰版」等限制促使自建。
下游：实施计划 `docs/superpowers/plans/2026-10-20-self-hosted-im.md`（待编写）。

## 1. 背景与定位

现网 IM 链路由四部分组成：

1. Flutter `app/lib/im/`：`ImClient` 抽象 + `TencentImClient` 实现；
2. Web `web/src/im/`：同构的 `ImClient` 抽象 + 腾讯 Web SDK；
3. Django `chatapp/im/`：`client.py` 调腾讯 REST（建号/资料/黑名单/系统通知）、
   `views.py` 签发 userSig、`tasks.py` 承载 Celery 副作用；
4. 腾讯云侧：消息存储、漫游、推送通道、单设备踢下线。

**目标：** 用自研 C++ 服务端替换第 4 部分，保留第 1–3 部分的接口形状，
使 App/Web/Django 可以在一个开关下双跑：先用隔离测试号灰度，真实用户一次性全量。

**非目标（本期不做）：**

- 群聊、聊天室、消息搜索、多端同步（产品规则是单设备在线）；
- 给对方已读回执（腾讯旗舰版能力，现网已挂起，保持一致）；
- 离线推送（极光推送是独立轨，不并入本期）；
- 图片消息（依赖腾讯上传插件，二期补齐，且是**全量上线门槛**，见 §13）；
- 历史消息迁移工具（上线前评估腾讯导出能力，见 §13）。

## 2. 已定关键决策（用户确认）

| 决策点 | 结论 | 落选理由 |
|---|---|---|
| 定位 | **生产替换**现有交友 App 的腾讯 IM | 独立练手项目无法复用现有双端抽象与业务约束 |
| MVP 边界 | **文本闭环优先**：登录/单聊文本/离线补拉/会话列表/未读/已读/撤回/系统通知/拉黑 | 图片要新增上传与存储，推迟到二期；纯消息通道会让现有 UI 返工 |
| 切换方式 | **双跑开关 + 隔离测试号灰度；真实用户一次性全量**，回退只改环境变量 | 跨后端会话不通：A 在自建、B 在腾讯时双方消息都收不到；按真实用户灰度会造成“配对了却聊不了” |
| 服务端架构 | **C++ 单体 + MySQL/Redis**，WS 与 HTTP 同进程 | 网关回调 Django 落库会撞 53 req/s 上限；自研存储对 500 在线规模是过度设计 |
| 构建环境 | **Ubuntu 24.04 容器/WSL 编译**，产物为 Linux 单二进制 | MinGW 链接 MySQL 客户端坑多，且 Asio 在 Windows 走 IOCP，行为与线上不一致 |

## 3. 总体架构

```
Flutter / Web
   │  wss://host/im/ws        实时帧（收发/已读/撤回/踢下线）
   │  https://host/im/api/*   历史消息、会话列表
   ▼
Nginx ──/api/v1/──▶ gunicorn :8000 (Django)
   └──/im/───────▶ imserver 127.0.0.1:9100
                      ├─ MySQL 8  库 chatapp_im（im_* 表，独立账号）
                      └─ Redis 7  DB2（在线表/封禁标记/限流）

Django ──HMAC 内部调用──▶ http://127.0.0.1:9100/internal/*
Celery ──同上──▶ 系统通知 / 资料同步 / 踢人 / 删号
```

职责边界：

- **imserver**：连接、鉴权、消息顺序号、落库、推送、历史查询、在线状态；
- **Django**：签发 IM token、按灰度决定后端、业务副作用（配对/封禁/举报/评论提醒）；
- **MySQL**：消息唯一真相；**Redis**：可丢的在线态与限流，丢了只影响在线标记。

## 4. 数据模型

库 `chatapp_im`，字符集 `utf8mb4`，所有时间字段为**毫秒 Unix 时间戳**（`BIGINT`）。

### 4.1 `im_user`

| 列 | 类型 | 说明 |
|---|---|---|
| `user_id` | BIGINT UNSIGNED PK | 与 Django `User.id` 一致；`0` 固定为「系统通知」 |
| `nickname` | VARCHAR(64) | 资料同步缓存 |
| `avatar_url` | VARCHAR(512) | 绝对 URL，可为空串 |
| `updated_at` | BIGINT | 毫秒 |

### 4.2 `im_conversation`

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | BIGINT UNSIGNED AUTO_INCREMENT PK | |
| `user_a` / `user_b` | BIGINT UNSIGNED | 约定 `user_a < user_b`，`UNIQUE(user_a,user_b)` |
| `last_seq` | BIGINT UNSIGNED | 该会话已分配的最大序号 |
| `last_msg_id` | BIGINT UNSIGNED NULL | 最后一条消息 |
| `last_msg_at` | BIGINT | 毫秒，会话列表排序键 |
| `created_at` | BIGINT | 毫秒 |

### 4.3 `im_conversation_state`

| 列 | 类型 | 说明 |
|---|---|---|
| `owner_id` | BIGINT UNSIGNED | 会话归属用户 |
| `conv_id` | BIGINT UNSIGNED | |
| `unread` | INT UNSIGNED | 未读数 |
| `read_seq` | BIGINT UNSIGNED | 已读到的序号 |
| `deleted` | TINYINT | 1 = 用户删除了会话（新消息自动复活） |
| `updated_at` | BIGINT | 毫秒 |

主键 `(owner_id, conv_id)`，索引 `(owner_id, updated_at)`。

### 4.4 `im_message`

| 列 | 类型 | 说明 |
|---|---|---|
| `msg_id` | BIGINT UNSIGNED AUTO_INCREMENT PK | 对外字符串化 |
| `conv_id` | BIGINT UNSIGNED | |
| `seq` | BIGINT UNSIGNED | 会话内严格递增，`UNIQUE(conv_id,seq)` |
| `from_id` / `to_id` | BIGINT UNSIGNED | `from_id=0` 表示系统通知 |
| `kind` | TINYINT | 1=text，2=custom |
| `body` | TEXT | JSON：text 为 `{"text":"..."}`；custom 为 `{"type":"...","desc":"...","data":{...}}` |
| `client_msg_id` | VARCHAR(64) | 客户端幂等键；`UNIQUE(from_id,client_msg_id)` |
| `created_at` | BIGINT | 毫秒 |
| `revoked_at` | BIGINT NULL | 非空即已撤回 |

索引 `(conv_id, msg_id)` 支撑历史分页。

### 4.5 `im_blacklist`

`(owner_id, peer_id)` 联合主键，`created_at` 毫秒。发送时双向校验。

### 4.6 序号分配（唯一写路径）

发送事务内：

1. `SELECT id,last_seq FROM im_conversation WHERE user_a=? AND user_b=? FOR UPDATE`；
2. 行不存在则 `INSERT ... (last_seq=0)`，撞唯一键后重查；
3. `seq = last_seq + 1`，插消息，更新 `last_seq/last_msg_id/last_msg_at`；
4. `INSERT ... ON DUPLICATE KEY UPDATE` 写双方 `im_conversation_state`
   （接收方 `unread=unread+1`；发送方 `unread` 不变；双方 `deleted=0`，即发消息会
   复活自己删掉的会话）。

同一会话的并发发送被行锁串行化，保证 `seq` 连续无空洞。`from_id=0` 的系统通知
只写接收方 state，不写发送方。

`im_user` 在迁移时插入 `(0,'系统通知','')`；服务端鉴权成功时对缺失用户
`INSERT IGNORE` 兜底，保证 Django 建号失败也不会阻断登录（昵称后续由资料同步补齐）。

## 5. 协议

### 5.1 信封

```json
{"v":1,"type":"send","id":"c-7f3a...","data":{"to":"u9","kind":"text","text":"在吗"}}
```

- `v` 固定 1；`type` 见下表；`id` 仅请求类帧使用，响应原样带回；
- 单帧上限 8 KB；文本上限 2000 字符（按 UTF-8 字符数计），去首尾空白后不得为空；
- `msg_id`、`client_msg_id` 一律字符串；`client_msg_id` 1–64 字符，限
  `[A-Za-z0-9_-]`；`seq`、`ts`、`uid` 为数字。

### 5.2 帧表

| 方向 | type | data | 说明 |
|---|---|---|---|
| C→S | `auth` | `{token}` | 连接后 5 秒内必须发，否则断开 |
| C→S | `send` | `{client_msg_id,to,kind:"text",text}` | 只允许 text |
| C→S | `read` | `{peer,seq?}` | 只改自己的未读；`seq` 缺省取会话 `last_seq` |
| C→S | `revoke` | `{msg_id}` | 仅发送者、120 秒内 |
| C→S | `conversation_delete` | `{peer}` | 只删自己这侧 |
| C→S | `ping` | `{}` | 25 秒一次 |
| S→C | `auth_ok` | `{uid,server_time,heartbeat_sec}` | 鉴权成功 |
| S→C | `ack` | `{ok:true}` 或 `{msg_id,seq,ts}` | 按请求类型返回；`send` 带消息三元组 |
| S→C | `message` | 见 5.3 | 新消息推送 |
| S→C | `revoked` | `{msg_id,seq,peer,ts}` | 撤回推送（双方都收） |
| S→C | `kicked` | `{reason}` | `multi_device` / `banned` / `deleted` |
| S→C | `pong` | `{server_time}` | 心跳响应 |
| S→C | `error` | `{code,message,id?}` | 见 5.4 |

### 5.3 `message` 载荷

```json
{"msg_id":"123457","seq":43,"from":"u9","to":"u2","kind":"text",
 "text":"在","ts":1760000000456,"revoked":false,
 "from_profile":{"nickname":"小九","avatar":"https://.../a.jpg"}}
```

custom 消息把 `text` 换成：

```json
{"kind":"custom","custom":{"type":"match_notice","desc":"你们已互相喜欢,开始聊天吧","data":{}}}
```

`custom.type` 取值与现网一致：`match_notice` / `ban_notice` / `ban_lifted` /
`report_handled` / `post_commented` / `post_replied`。`from_profile` 用于 Web 首次
收到新会话消息时显示昵称头像，Flutter 忽略多余字段。

### 5.4 错误码

沿用「5 位 = 前 3 位 HTTP + 2 位序号」：

| code | 含义 | 客户端处理 |
|---|---|---|
| 40001 | 首帧不是 auth / 5 秒超时 | 断开，重连 |
| 40101 | token 无效/过期 | 发 `ImSigExpired`，由 `ImManager` 重拉 token |
| 40301 | 账号被封禁 | 发 `ImKickedOffline(banned)`，停止重连 |
| 40302 | 被对方拉黑或已拉黑对方 | 消息标失败，提示「无法发送」 |
| 40401 | 接收方不存在 | 消息标失败 |
| 41001 | 撤回越权/超时/已撤回 | 页面提示，不改本地状态 |
| 42201 | 内容为空/超长/kind 不支持 | 消息标失败 |
| 42202 | 当前后端不支持该消息类型（如图片） | 提示「暂不支持图片」 |
| 42901 | 发送过快 | 消息标失败，可重试 |
| 50001 | 内部错误 | 消息标失败，可重试 |

WS 关闭码：`4001` 被踢、`4002` 鉴权失败、`4003` 封禁、`4004` 慢消费者、
`1000` 正常关闭。`4001/4002/4003` 停止重连并处理对应事件；`4004` 退避重连；
`1000` 不重连。

## 6. 服务端设计

### 6.1 目录

```
imserver/
├─ CMakeLists.txt
├─ migrations/001_init.sql
├─ deploy/{imserver.service, nginx-im.conf, imserver.env.example}
├─ src/
│  ├─ main.cpp                 配置 → 迁移 → 连接池 → WS/HTTP → 信号退出
│  ├─ config.{h,cpp}           env 读取与校验，缺失即启动失败
│  ├─ net/ws_server.{h,cpp}    Beast WebSocket：握手、读循环、写队列、strand
│  ├─ net/http_api.{h,cpp}     Beast HTTP：/im/api/* 与 /internal/*
│  ├─ auth/token.{h,cpp}       HS256 校验（纯函数）
│  ├─ service/
│  │  ├─ session_registry       uid → 连接、在线 Redis、踢人
│  │  ├─ message_service        send/ack/revoke/history
│  │  └─ conversation_service   列表、未读、已读、删除
│  ├─ store/                    mysql_pool、message_repo、conversation_repo、
│  │                            user_repo、blacklist_repo、redis_client
│  └─ util/                     json、log、time、uuid、ratelimit
└─ tests/                      gtest：协议编解码、token、seq、幂等、权限
```

分层铁律：`net/` 不写 SQL，`service/` 不碰 socket；service 只依赖 repo 接口，
单测用内存假实现。

### 6.2 并发模型

- `io_context` 2 线程（2 核机器），每连接一个 strand；
- 同步 DB 调用放独立 4 线程池，结果 `post` 回连接 strand；
- MySQL 连接池 8，取不到连接等待 500 ms 后返回 `50001`；
- 每连接出站队列上限 64 帧或 128 KB（先到为准），超限关闭 `4004`。

### 6.3 HTTP 接口

| 方法/路径 | 说明 |
|---|---|
| `GET /im/api/conversations?limit=100` | 会话列表，按 `last_msg_at DESC`；过滤 `deleted=1`；含 peer 资料、最后一条消息、未读、`last_seq`；`limit` 默认 100、上限 200，MVP 不做翻页 |
| `GET /im/api/messages?peer=u9&before_seq=&limit=50` | 历史；取 `seq < before_seq` 的最近 `limit` 条后**升序**返回；`limit` 上限 100；`peer=system_notice` 映射到 `uid=0` |

`GET /im/api/conversations` 响应：

```json
{"items":[{"peer":{"id":"u9","nickname":"小九","avatar":"https://.../a.jpg"},
  "last_message":{"msg_id":"123457","seq":43,"from":"u9","to":"u2","kind":"text",
                  "text":"在","ts":1760000000456,"revoked":false},
  "unread":2,"last_seq":43,"updated_at":1760000000456}],
 "has_more":false}
```

`GET /im/api/messages` 响应：

```json
{"items":[{"msg_id":"123457","seq":43,"from":"u9","to":"u2","kind":"text",
           "text":"在","ts":1760000000456,"revoked":false,
           "from_profile":{"nickname":"小九","avatar":"https://.../a.jpg"}}],
 "has_more":true}
```

两个接口均需 `Authorization: Bearer <IM token>`；`peer` 必须是
`u<数字>` 或 `system_notice`，否则 `42201`。`msg_id` 一律为字符串（避免 JS
大整数精度问题）。HTTP 错误统一 `{"code":<5 位码>,"message":"<中文>"}`，
鉴权失败 401 + `40101`，封禁 403 + `40301`。

### 6.4 内部管理 API

前缀 `/internal`，仅监听 `127.0.0.1`，HMAC 头（`path` 含 query string）：

```
X-IM-Timestamp: <unix 秒>
X-IM-Signature: hex(HMAC-SHA256(internal_secret, ts + "\n" + METHOD + "\n" + path + "\n" + body))
```

时间偏差 > 60 秒拒绝；来源 IP 不是 `127.0.0.1` 拒绝。

| 路径 | 载荷 | 行为 |
|---|---|---|
| `GET /internal/healthz` | — | 进程存活（不查库） |
| `GET /internal/readyz` | — | MySQL + Redis 可用 |
| `POST /internal/accounts/ensure` | `{uid,nickname}` | 不存在则插入，存在不动资料 |
| `POST /internal/profile` | `{uid,nickname?,avatar?}` | 只更新传入字段 |
| `POST /internal/send` | `{from,to,kind:"text"\|"custom",text?,custom?}` | 落库并推送，`from=0` 为系统通知 |
| `POST /internal/blacklist` | `{owner,peer,action:"add"\|"remove"}` | 写/删 `im_blacklist` |
| `POST /internal/kick` | `{uid,block}` | 关连接；`block=true` 置 Redis 封禁键（TTL 24h） |
| `POST /internal/unblock` | `{uid}` | 清封禁键，不关连接 |
| `POST /internal/delete_account` | `{uid}` | 关连接 + 置封禁 + 硬删该用户全部 IM 数据 |
| `GET /internal/stats` | — | 在线数、消息计数、ack 延迟分位、队列丢弃数 |

## 7. Django 对接与灰度

### 7.1 配置项（`chatapp/.env`）

| 键 | 示例 | 说明 |
|---|---|---|
| `IM_BACKEND` | `tencent` / `self` | 总开关；回退只改它 |
| `IM_SELF_URL` | `http://127.0.0.1:9100` | 内部 API 基址 |
| `IM_SELF_WS_URL` | `wss://<host>/im/ws` | 客户端 WS 地址 |
| `IM_SELF_HTTP_URL` | `https://<host>/im/api` | 客户端历史接口基址 |
| `IM_SELF_SECRET` | 32+ 字节随机串 | IM token 的 HS256 密钥 |
| `IM_SELF_INTERNAL_SECRET` | 32+ 字节随机串 | 内部 API 的 HMAC 密钥（与 token 密钥分开） |
| `IM_SELF_TOKEN_TTL` | `86400` | IM token 有效期（秒） |
| `IM_SELF_GRAYLIST` | `all` 或 `1,2,3` | 空 = 不灰度；`all` = 全量 |

`IM_BACKEND=self` 时，上述地址与两个密钥缺失则 Django 启动直接报错（fail fast），
不允许带着半套配置上线。

### 7.2 文件改动

| 文件 | 改动 |
|---|---|
| `im/tencent_client.py` | 现有 `client.py` 原样迁入 |
| `im/self_client.py` | 内部 API 客户端：HMAC、5 秒超时、**永不抛异常只返回 False** |
| `im/token.py` | HS256 签发/校验；claims `sub`（`u9`）、`uid`、`iat`、`exp`、`jti` |
| `im/client.py` | 门面：按 `IM_BACKEND` 分发；函数名不变，仅 `kick_user` 增加可选 `block` 参数 |
| `im/tasks.py` | 仅 `ban_notice` 一处改为 `kick_user(..., block=True)`；其余零改动 |
| `im/views.py` | `user_sig` 分支返回 `backend/token/ws_url/http_url`；保留「先踢旧会话再发签名」顺序 |

`im/tasks.py` 的 `send_ban_lifted` 在 self 后端会额外触发 `/internal/unblock`
（由门面内部完成，任务代码不改）；否则解封后旧 token 仍会被封禁键挡住。

`SYSTEM_NOTICE_IDENTIFIER="system_notice"` 在服务端映射为 `uid=0`，跨栈契约不变。

`user_sig` 的 self 分支先调 `accounts/ensure`（带昵称）；失败只记日志、不阻断签发，
服务端鉴权时 `INSERT IGNORE` 兜底，昵称等下一次资料同步补齐。

### 7.3 灰度判定与边界

```python
def use_self_im(user) -> bool:
    if settings.IM_BACKEND != "self":
        return False
    gray = settings.IM_SELF_GRAYLIST.strip()
    return gray == "all" or str(user.id) in {x.strip() for x in gray.split(",") if x.strip()}
```

**灰度名单只能放隔离测试号**（专用账号，只与测试号互聊），不能放真实用户：
自建与腾讯两套消息存储不互通，一对配对里只要有一端在腾讯，双方就收不到消息。
真实用户在切换日一次性全量（`IM_SELF_GRAYLIST=all`）。

客户端**每次登录**都重新问后端，所以改灰度/回退只影响下一次登录（App 重启或重新
登录）。已建立的 WS 连接不会自动迁移；如需立刻止血，停掉 imserver（聊天暂不可用）
并让用户重启 App，重启后会拿到腾讯引导包。运维手册写明这两步。

## 8. 客户端改造

### 8.1 引导包

`POST /api/v1/im/user_sig` 响应（旧字段保留，新增字段可忽略）：

```json
{"backend":"self","im_user_id":"u9","token":"<JWT>",
 "ws_url":"wss://host/im/ws","http_url":"https://host/im/api","expire":86400}
```

腾讯路径返回 `backend:"tencent"` 与原 `user_sig/sdkappid/expire`。

### 8.2 Flutter

- 新增依赖 `web_socket_channel`；
- `ImBootstrap` 模型 + `UserSig` 扩展字段；
- `RoutingImClient implements ImClient`：`init(bootstrap)` 时选实现，`events` 透传；
- `SelfImClient`：
  - 首帧 `auth`，25 秒心跳，指数退避重连（1→2→4→8→16→30 秒 + ±20% 抖动）；
  - `sendText` 等 `ack`，10 秒超时抛 `ImException`；
  - **重发必须复用 `client_msg_id`**：`resend(message)` 用 `message.msgId`
    （`local-<micros>`）作为 `client_msg_id`，服务端靠唯一键去重；
  - 历史/会话列表用独立 Dio（IM token，不经过 JWT 刷新拦截器）；
  - 能力位 `ImClient.capabilities.image`：腾讯 `true`、自建 `false`，聊天页据此
    隐藏图片按钮（避免用户点出必然失败的气泡）；
  - 传输层抽 `SelfImTransport`，测试注入假 WS。
- 事件映射：`message`→`ImNewMessage` + `ImConversationsChanged`；
  `revoked`→`ImMessageRevoked`；`kicked`/close 4001→`ImKickedOffline`；
  `error 40101` 或 HTTP 401→`ImSigExpired`；HTTP 403→`ImKickedOffline(banned)`。

### 8.3 Web

- `web/src/im/self/{client,map,transport}.ts`，原生 `WebSocket`；
- `getImClient()` 返回 `RoutingImClient`；`init(bootstrap)` 替换 `init(sdkAppId)`；
- `sendImage` 在 self 后端抛 `ImException(42202,"当前聊天服务暂不支持图片")`；
  聊天页按 `capabilities.image` 隐藏图片按钮，抛错分支只作兜底（二期补图片后移除）；
- 自建 `kicked.reason="multi_device"` 在 Web 侧按 `multiAccount` 处理（清凭证强退），
  不能按腾讯的「同端多实例」语义放过，否则被顶设备会继续用旧会话；
- vitest 注入假 WebSocket 覆盖 ack/重连/去重。

### 8.4 兼容性

- 旧版本 App 不认识 `backend`，仍会用不存在的 `user_sig` 登录腾讯 → 聊天不可用。
  因此全量切换前必须上线**最小版本拦截**（§13.4），把旧版本挡在门外并引导升级；
  灰度期只放隔离测试号，不受此影响。
- Web 端与 App 同时发版，浏览器刷新即生效，无旧版本问题。

## 9. 可靠性与错误处理

| 场景 | 规则 |
|---|---|
| 发送超时 | 10 秒无 `ack`，用同一 `client_msg_id` 重发，最多 3 次；仍失败标红可手动重发 |
| 重复投递 | `UNIQUE(from_id,client_msg_id)` 命中 → 校验 `to_id` 一致后返回原 `ack`，不重复落库；不一致返回 `42201` |
| 乱序/重复渲染 | 客户端按 `seq` 排序，按 `msg_id` 去重 |
| 断线重连 | 退避 1→30 秒；重连后重拉会话列表与当前聊天最近 50 条 |
| 心跳 | 客户端 25 秒 `ping`；服务端 75 秒无帧断开；Nginx `proxy_read_timeout 90s` |
| 慢消费者 | 出站队列 > 64 帧或 128 KB 关闭 `4004`，客户端重连后重拉 |
| 限流 | 每用户 20 条/秒（突发 40）；认证失败每 IP 60 次/分钟 |
| 多设备互踢 | 新连接先踢旧连接（`kicked.multi_device`）；**被踢端收到后必须停止重连并强退**，否则两台设备会互相顶号 |
| 进程重启 | 连接全断、客户端自动重连；Redis 在线键 TTL 90 秒自然过期 |
| 撤回 | 服务端时间判定 120 秒；重复撤回 `41001`；历史返回 `revoked:true` 且不带正文 |
| 删会话 | 只置自己 `deleted=1`；新消息复活并 `unread+1` |
| 拉黑 | 发送时双向校验，命中 `40302` |
| 账号注销 | 关连接 + 置封禁 + 删除该用户收发的全部消息、相关会话/state/黑名单；对方的会话随之消失（与 Django 硬删口径一致） |
| MySQL 不可用 | 读接口 503；发送返回 `50001`，客户端标失败可重试；进程不退出 |
| Redis 不可用 | 在线标记降级为进程内 Map；鉴权 fail closed（返回 503/`50001`），避免封禁被绕过 |

## 10. 安全

- IM token 与 Django JWT 分离，HS256 密钥 ≥ 32 字节，`IM_SELF_SECRET` 不入库；
- 内部 HMAC 用独立密钥 `IM_SELF_INTERNAL_SECRET`，与 token 密钥不复用；
- token 只放首帧，不放 URL（避免 Nginx access log 落 token）；
- 内部 API 仅 `127.0.0.1` + HMAC + 时间窗；
- 所有 SQL 走预处理语句；JSON 解析异常一律回 `42201`，不泄漏堆栈；
- WS 校验 `Origin`：`IM_ALLOWED_ORIGINS` 白名单；非浏览器客户端无 Origin 放行；
  空值 = 不校验（仅开发），生产必须配置；
- 日志不记录消息正文，只记 `uid/type/latency/code`；
- 文本长度、帧大小、单 IP 连接数（20，取 `X-Real-IP`）三重上限。

## 11. 测试与验收

### 11.1 测试矩阵

| 层 | 方式 | 必测项 |
|---|---|---|
| C++ 单测 | gtest | 帧编解码、token 校验、seq 分配、幂等、撤回时限、拉黑、限流、HMAC |
| C++ 集成 | docker compose（MySQL+Redis+server）+ Python WS 客户端 | 双端收发、离线补拉、重连、互踢、重启、慢消费者、封禁 |
| Django | `manage.py test` | token 签发/校验、灰度选择、门面分发、`user_sig` 响应、注释门禁 |
| Flutter | `flutter test` | ack 超时重发、乱序去重、重连重拉、踢下线、事件映射 |
| Web | vitest | 同上 + 工厂切换 |
| 压测 | `tools/im_load.py`（asyncio） | 500 连接、20 msg/s、p99 < 200 ms、RSS < 300 MB |

### 11.2 验收清单

1. 两个客户端互发文本，`ack` 本地 < 100 ms，`seq` 连续；
2. B 离线时 A 发 3 条，B 登录后会话未读 = 3，历史能看到 3 条；
3. 同一 `client_msg_id` 重发 3 次，库里只有 1 行；
4. 2 分钟内撤回双方都变灰字；超时撤回返回 `41001`；
5. 同账号第二处登录，第一处收到 `kicked` 并强制退出；
6. 封禁后重连被拒 `40301`；解封后可正常登录；
7. 拉黑后发送失败 `40302`，解除后恢复；
8. 重启 imserver，客户端 5 秒内重连，消息不重不漏；
9. 500 连接压测通过，p99 与内存达标；
10. 回退演练：`IM_BACKEND=tencent` 后新登录走腾讯，聊天可用。

## 12. 部署与运维

### 12.1 构建

- 多阶段 Dockerfile：`ubuntu:24.04` 内 `apt install build-essential cmake
  libboost-all-dev nlohmann-json3-dev libmysqlclient-dev libhiredis-dev libssl-dev
  libgtest-dev`，CMake 编译，产物 `/usr/local/bin/imserver`；
- 本地开发用 WSL Ubuntu 24.04 或同一镜像，命令与 CI 一致；
- 二进制带 `--migrate` 子命令：按 `im_schema_version` 表逐版执行 `migrations/*.sql`，
  重复执行安全。

### 12.2 运行

- systemd：`imserver.service`，`Restart=always`，`LimitNOFILE=65535`，
  环境文件 `/www/server/imserver/imserver.env`（600）；
- 服务端环境变量：

| 键 | 默认 | 说明 |
|---|---|---|
| `IM_LISTEN` | `127.0.0.1:9100` | 监听地址，绝不监听公网 |
| `IM_MYSQL_DSN` | — | `mysql://imserver:***@127.0.0.1:3306/chatapp_im` |
| `IM_REDIS_URL` | `redis://127.0.0.1:6379/2` | 在线态与封禁键 |
| `IM_JWT_SECRET` | — | 与 Django `IM_SELF_SECRET` 一致 |
| `IM_INTERNAL_SECRET` | — | 与 Django `IM_SELF_INTERNAL_SECRET` 一致 |
| `IM_ALLOWED_ORIGINS` | 空 | WebSocket Origin 白名单，逗号分隔；空 = 不校验（仅开发），生产必填 |
| `IM_IO_THREADS` / `IM_DB_THREADS` / `IM_DB_POOL` | `2` / `4` / `8` | 并发调优 |
| `IM_MAX_FRAME` / `IM_TEXT_MAX` | `8192` / `2000` | 帧与文本上限 |

- Nginx（`X-Real-IP` 必须设置，服务端用它做限流；否则所有请求都来自 127.0.0.1）：

```nginx
location /im/ws {
    proxy_pass http://127.0.0.1:9100;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 90s;
}
location /im/api/ {
    proxy_pass http://127.0.0.1:9100;
    proxy_set_header X-Real-IP $remote_addr;
}
```

- MySQL：独立库 `chatapp_im` + 账号 `imserver`，只授该库权限；随现有备份一起
  `mysqldump`；
- Redis：DB2，沿用本机实例；
- 日志：JSON 行到 stdout，由 journald 轮转。

### 12.3 本地开发

- imserver 监听 `127.0.0.1:9100`，Django 仍跑 `:8000`；
- `chatapp/.env` 配 `IM_SELF_WS_URL=ws://10.0.2.2:9100/im/ws`、
  `IM_SELF_HTTP_URL=http://10.0.2.2:9100/im/api`，由 `/im/user_sig` 原样返回给 App；
- Web：Vite 增加 `/im` 代理到 `http://127.0.0.1:9100`（`ws: true`），
  浏览器端用同源相对地址；开发时 `IM_ALLOWED_ORIGINS=http://localhost:5173`；
- 集成测试用 `docker compose -f imserver/docker-compose.test.yml` 起 MySQL/Redis，
  与线上同版本。

### 12.4 容量

500 在线连接常驻内存约 20–40 MB；文本消息写入是单行 INSERT，2C2G 足够。
CPU 主要花在 JSON 解析与 TLS（TLS 在 Nginx），imserver 预计 < 10% 单核。

## 13. 迁移与上线门槛

### 13.1 灰度顺序

1. 本地 docker 全链路 + 压测；
2. 服务器部署，`IM_BACKEND=tencent`（对现网零影响）；
3. App/Web 发版（带双后端实现），灰度名单 = **隔离测试号**，测试号之间互聊验证；
4. 观察一周：消息成功率、`ack` 延迟、断线率、崩溃日志；
5. 上线最小版本拦截（§13.4），确认旧版本用户已被挡住；
6. 切换日：`IM_SELF_GRAYLIST=all`，真实用户一次性全量；
7. 保留 `IM_BACKEND` 回退开关至少一个版本周期。

### 13.2 历史消息

切换后客户端只能看到 `chatapp_im` 里的消息。腾讯侧提供单聊消息漫游/导出 REST
（需控制台开通权限），上线前做一次可行性验证：

- 可用：写一次性导入脚本，**在切换前**导入最近 90 天单聊消息：按会话分组、
  按原时间升序分配 `seq`（从 1 开始）、保留原 `created_at`，`client_msg_id`
  用 `tx-<腾讯消息ID>` 保证可重跑去重，最后回填 `last_seq/last_msg_id/last_msg_at`；
- 不可用：必须由产品明确接受「切换点之前的记录不可见」，否则不全量。

### 13.3 全量门槛（缺一不可）

1. 图片消息可用（否则是功能回退）；
2. 历史迁移完成或产品书面确认接受；
3. 500 连接压测达标；
4. 回退演练通过；
5. 客户端最小版本拦截已上线（§13.4）；
6. `docs/api/im.md` 与新协议文档更新完毕。

### 13.4 客户端最小版本拦截（全量前提）

旧版本 App 无法使用自建后端，所以切换日之前必须能挡住它：

- 新增公开接口 `GET /api/v1/app/config` → `{min_app_version, latest_version, download_url}`，
  不需鉴权（启动阶段就要拦）；
- App 启动时（登录页之前）调一次，`appVersion < min_app_version` 时显示阻塞页与
  下载按钮，不允许进入主界面；版本按三段数字逐段比较，不做字符串比较；
- Web 构建注入版本号（Vite `__APP_VERSION__`），低于最小值时显示强制刷新提示；
- 新接口纳入 `docs/api/`，`ApiDocsCoverageTests` 双向门禁照常生效。

## 14. 分期计划

| 阶段 | 交付物 | 人日 | 完成判据 |
|---|---|---|---|
| P0 | CMake 骨架、配置、日志、MySQL/Redis 池、`--migrate`、`/internal/healthz` | 2 | 容器内编译通过，healthz 200 |
| P1 | token 校验、WS 握手、首帧 auth、单设备互踢、心跳 | 3 | 两客户端登录/互踢集成测试绿 |
| P2 | 发送/ack/落库/推送、历史、会话列表、未读/已读、撤回 | 5 | §11.2 的 1–4 绿 |
| P3 | 内部管理 API + Django 门面/灰度 + 系统通知 | 3 | 配对/封禁/举报灰条端到端绿 |
| P4 | Flutter + Web 双实现与切换 | 4 | 双端手测通过，单测绿，`flutter analyze` 与 `vue-tsc`/`eslint` 零告警 |
| P4.5 | 最小版本拦截（`/app/config` + App/Web 阻塞页 + 文档） | 1 | 旧版本被阻塞页挡住 |
| P5 | 集成测试、压测、部署、灰度演练 | 3 | §11.2 全绿 |
| **合计** | | **21** | |

每阶段结束必须全绿再进下一阶段（项目纪律）。

## 15. 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| 腾讯历史无法导出 | 全量切换丢历史 | §13.2 提前验证；不可用则产品签字或延期 |
| 图片二期拖延 | 全量后用户发不了图 | 图片列为全量门槛，不作为“以后再说” |
| 旧客户端不识别 `backend` | 全量后旧版本聊天不可用 | 全量前上线最小版本拦截（§13.4），挡住旧版本 |
| 时钟漂移 | token 刚签发就过期 | 服务器 NTP；校验留 60 秒时钟偏差 |
| Redis 丢失 | 在线态/封禁键丢失 | 在线态可自愈；鉴权 fail closed，等 Redis 恢复；封禁仍由 Django 403 兜底 |
| 单机故障 | 聊天全断 | systemd 自动重启；客户端退避重连；消息已落库不丢 |
| 回退丢自建期消息 | 回退后腾讯侧看不到切换后的消息 | 回退只作止血；自建库保留、可导出，回退前产品知情 |
| Celery 重试重复灰条 | 配对通知重复 | 与现网腾讯路径行为一致，不在本期扩大范围 |
| 聊天记录保留期未定 | 存储持续增长、合规口径不明 | 默认永久保留；上线前由产品确认，若需定期清理则加按 `created_at` 的归档任务并重算 `last_msg` |

## 16. 交付物清单

- `imserver/`：C++ 服务端、迁移 SQL、部署文件、单测与集成测试；
- `chatapp/im/{token,self_client}.py`、`client.py` 门面化、`views.py` 分支、
  settings 配置；
- `app/lib/im/{routing_im_client,self_im_client,im_bootstrap}.dart` 与测试；
- `web/src/im/self/*` 与测试；
- `GET /api/v1/app/config` + App/Web 最小版本阻塞页；
- `docs/api/im.md`、`docs/api/app.md` 更新，`docs/pitfalls/im.md` 增补自建段，部署手册；
- `tools/im_e2e.py`、`tools/im_load.py`。
