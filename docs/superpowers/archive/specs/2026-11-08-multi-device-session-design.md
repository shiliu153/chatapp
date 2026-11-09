# 多端同时在线(一个 App + 一个网页)设计

- **日期**:2026-11-08
- **状态**:**已交付**(批次 K,第六轮功能开发第一批)—— K-1~K-4 于 2026-11-08 合并进 `master`
  (`6aa772f` / `f5802f2` / `37eaf56` / `fabf85a`),2026-11-09 归档;**生产尚未上线**(见 plan 的「收尾记录」)
- **上游**:第六轮功能开发拆批(K → L → M → N → O)。**注意:该拆批从未落进
  [backlog](../../../backlog/2026-11-03-todo.md)**,只存在于会话与本文/姊妹文档的引用里;
  M/N/O 三批在 2026-11-09 收尾时仍未立项(见本文末「执行记录」)

## 1. 背景与现状(2026-11-08 核实)

现在**一个账号同时只能有一台设备在线**,由三层咬合实现:

| 层 | 位置 | 行为 |
|---|---|---|
| Django 鉴权 | `chatapp/accounts/authentication.py:39` | 令牌里的 `session_version` ≠ 库里的值 → `401 + 40101` |
| 登录 | `chatapp/accounts/views.py:211` | 每次登录 `User.session_version += 1`(用 `F()` 自增防并发) |
| IM 建连 | `imserver/src/service/session_registry.cpp:32` | 注册新连接时 `old->kick("multi_device")`;`sessions_` 是 `uid → 单个 weak_ptr` |
| IM 踢人链路 | `chatapp/im/views.py:79-91` + `chatapp/im/tasks.py:43` | 登录时置 `im:kick_pending:{uid}`,拉签名前**先踢旧会话再签发**,顺序反了会踢掉本机新会话(2026-09-12 回归过) |

后果:手机上聊一半换到电脑网页,手机立刻 `401 + 40101` 被强退;再回手机又要重登。对个人项目这是最碍事的设定。

**这也是 2026-10 安全审计的落地项之一** —— 单设备被当作「防账号共享」的手段。本设计**正式作废该结论**,替代措施见 §8。

## 2. 目标与非目标

**目标**:同一账号可同时在线 **1 个 App + 1 个网页**;同类(两个 App 或两个网页)第二次登录**互顶**,行为与今天一致(`401 + 40101` 强退登录页)。

**非目标**(本批不做,别顺手加):
- 设备管理页(设备列表 / 按设备踢人 / 设备名)—— 端数固定为 2,加页面收益不足
- 新设备登录通知 —— 每次登录都推一条,噪声大于价值
- 不限端数 / 多台手机 —— 见 §8 的替代措施
- 离线推送 —— 项目已决定不做([backlog §4](../../../backlog/2026-11-03-todo.md))

## 3. 已拍板的决策

| 决策 | 结论 | 理由 |
|---|---|---|
| 在线形态 | **一个 App + 一个网页**,同类互顶 | 覆盖真实痛点(手机↔电脑);保住「两台手机不能同时登」那半条审计结论;不需要设备管理页 |
| 跨端已读 | **任一端读了就算读** | `read_seq` 保持 `(owner, conv)` 粒度,数据模型零改动;与已交付的已读回执语义一致 |
| 实现路线 | **端会话小表**(不是两列版本号、不是 Redis 存 jti) | 一个 `unique(user, client_type)` 约束就表达「同类互顶」;将来加第三种端只加一行;DB 仍是事实来源 |
| 退出所有设备 | **做**(`POST /auth/logout/all`) | 丢手机场景需要;代价是一个接口 + 设置页一行 |
| 新设备登录通知 | **不做** | 见 §2 |

## 4. 架构

### 4.1 客户端类型的判定:令牌自证

**不用请求头做鉴权判断** —— 头缺失或被伪造会让端判定漂移(例如 Web 请求漏带 `X-Client` 就会被当成 App,把真 App 顶掉)。规则:

- **签发时**看头:`POST /auth/sms/verify` 与 `POST /auth/token/refresh` 按 `X-Client: web` 判 `web`,**缺省一律 `app`**(线上 1.0.10 老 APK 不带这个头,不能因此掉线);
- **鉴权时**看令牌:JWT 里带 `ct` claim(`app` / `web`),`SessionJwtAuthentication` 用**令牌自带的 `ct`** 去查 `(user, ct)` 的会话行;
- **过渡兼容**:没有 `ct` claim 的历史令牌按 `app` 处理(等价于今天的行为),imserver 侧同理(`sv=0` 的旧 token 继续放行,见 `imserver/src/auth/token.h:15`)。

### 4.2 Django 侧数据模型

新增 `accounts.DeviceSession`(迁移 `accounts.0006_devicesession`):

| 字段 | 说明 |
|---|---|
| `user` | 外键,`related_name="device_sessions"` |
| `client_type` | `app` / `web`(`TextChoices`) |
| `version` | 该端的会话版本,登录时 `+1`(同样用 `F()` 防并发) |
| `created_at` | 建档时间 |

约束 `UniqueConstraint(user, client_type)`。**本轮不做** `last_seen_at`:它要么每请求写一次库(不可接受),要么只在登录时写(等于 `created_at` 的副本)。等设备管理页真的出现时再加。

`User.session_version` **保留列但停止参与鉴权**,docstring 标注 deprecated。不删列的理由:一次改太多容易把兼容路径搅乱;删除作为独立清理项(见 §10)。

### 4.3 imserver 侧

新增迁移 `imserver/migrations/005_device_session.sql`(现有最新是 `004_pair.sql`,见 `imserver/src/migrate.cpp:71-74`):

```sql
CREATE TABLE IF NOT EXISTS im_device_session (
  user_id BIGINT NOT NULL,
  client_type VARCHAR(8) NOT NULL,
  session_version BIGINT NOT NULL,
  PRIMARY KEY (user_id, client_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- `TokenClaims` 加 `std::string ct`(缺省 `"app"`);`mint_token` 增加 `ct` 参数;
- `session_version_matches(...)` 的查库改为 `(uid, ct)` 命中 `im_device_session`;`im_user.session_version` 停止使用(保留列);
- `SessionRegistry`:`sessions_` 从 `unordered_map<uint64_t, weak_ptr>` 改为 `unordered_map<uint64_t, unordered_map<string, weak_ptr>>`;
  - `send_to(uid, frame)` → **扇出到本人所有端**;
  - 新增 `kick(uid, client_type, reason)`;`kick(uid, reason)` 保留为「踢全部」(封禁 / 注销用,语义不变);
  - `is_online` / `online_count` 语义不变(按 uid 计,不按连接计)。

### 4.4 协议变更(唯一的帧改动)

下行 `read` 帧的语义是「**对端**读到 seq」(`imserver/src/net/frames.h:91-94`),**不能**用来做跨端同步 —— 发给自己的另一台设备会被解释成「对方已读」,是错的。

新增下行帧:

```json
{"v":1,"type":"self_read","data":{"peer":"u12","seq":42}}
```

含义:「**我**在另一个设备上把与 `peer` 的会话读到了 `seq`」。接收端据此把自己这边的未读清零、`read_seq` 只增不减。

**契约联动(必须同一次改动内做完,否则三条 CI 轨红)**:
`imserver/tests/fixtures/ws/server_to_client.json` + `imserver`(`frames.h` / `ws_server.cpp`)+ App(`self_im_client.dart` + `protocol_fixture_test.dart`)+ Web(`web/src/im/self/*` + `im-protocol-fixture.spec.ts`)。规则见 `imserver/tests/fixtures/ws/README.md`。

### 4.5 需要先核实的两个闸门(动手前,不是动手后)

1. **本人操作要不要扇出到自己的其他设备**:已读(本设计:要)、**删除会话**、**撤回消息**(撤回已向双方广播,是否已覆盖自己另一台?)。先读 `ws_server.cpp` 的 `handle_conversation_delete` / `handle_revoke` 现状,再决定哪些纳入本批 —— 不要把「已覆盖」的重复做一遍。
2. **`im:online:{uid}` 的 TTL 语义**多端后是否仍然成立(任一端活跃即在线,现实现按 uid 写,应天然成立,需一条测试钉住)。

## 5. 发布顺序与兼容

```
① 后端(K-1)+ imserver(K-2)同一窗口上线   ← 老 APK / 老 Web 不受影响(无 ct 视为 app)
② 契约帧(K-3):imserver + App + Web 同一次 PR
③ 双端(K-4):App 全量带 X-Client: app;Web 复核
```

**必须先 ①再 ②③**:老客户端没有 `ct` claim,新 imserver 必须按 `app` 兜底;若先上 imserver 而它不认旧 token,线上所有 IM 连接会集体 40101。

迁移:`accounts.0006` 建表;imserver 换镜像后 `docker compose run --rm imserver --migrate` 会跳过 1–4、应用 005。**不需要**重跑 `im_sync_pairs`(与配对无关)。

## 6. 工单拆分(一单一条栈)

| 单号 | 栈 | 内容 | 依赖 |
|---|---|---|---|
| **K-1** | backend | `DeviceSession` 表 + 迁移;`SessionJwtAuthentication` 按 `(user, ct)` 校验;`sms_verify` 只递增本端;`kick_pending` 键加端维度;`user_sig` 只踢本端旧会话;`POST /auth/logout/all`;`docs/api/auth.md` + `im.md` + `openapi.yml` 重生成 | 无 |
| **K-2** | imserver | 迁移 005;`TokenClaims.ct`;`session_version_matches` 按端;`SessionRegistry` 多连接 + 扇出;`/internal/kick` 与 `/internal/session_version` 带 `client_type` | K-1 同窗口 |
| **K-3** | imserver(主)+ App + Web 附带 | `self_read` 帧 + fixture + 三端解析与未读清零(**契约联动,一个 PR**) | K-2 |
| **K-4** | App + Web | App 全量带 `X-Client: app`;Web 复核 `stores/chat.ts` 的 `multiAccount`(同浏览器两标签仍应互顶) | 无(可并行) |

**K-4 不阻塞发布**:K-1 对缺 `X-Client` 的请求按 `app` 兜底,所以 App 在补头之前行为已经正确;K-4 只是把这个约定显式化,并复核 Web 的多标签逻辑。

## 7. 验收

**worker 能自证的(K-1 / K-2 / K-3 各自 PR 里跑)**:

- 后端:App 登录后 Web 登录 → App 的 access 仍 `200`;同端第二次登录 → 前一个 `401 + 40101`;`refresh` 按端轮换互不影响;`logout/all` 后两端都 `401`;不带 `X-Client` 的登录按 `app` 处理
- imserver:同 uid 两条不同 `ct` 的连接**并存**,下行消息**两端都收到**;同 `ct` 第二条连接踢掉第一条(reason `multi_device`);封禁 `kick` 仍是踢全部;`self_read` 只发给我本人的其他端、不发给对方;旧 token(无 `ct` / `sv=0`)仍能连上
- 契约:故意把 fixture 里 `self_read` 改一个字段名 → **三端同时红**
- 门禁:后端 `scripts/verify.sh backend`、`imserver`、`app`、`web` 各自绿

**留给人验(合并后才发生,不写成 worker 验收项)**:

- 模拟器(App)与浏览器(Web)同时登录同一账号:互发消息两端都到、一端已读另一端红点消失、App 再登一次被顶的提示与文案不变
- 生产发布后:老 APK(1.0.10)仍能登录与收发(无 `ct` 兜底真的生效)

## 8. 作废的审计结论与替代措施

**作废**:「一个账号同时只允许一台设备在线」作为防账号共享手段(2026-10 安全审计落地项)。

**替代措施**(写进 `docs/security/` 的状态注记,避免下一个人当成回归):

1. **同类互顶仍然生效** —— 两台手机不能同时在线,共享账号仍会被互相顶掉;
2. **access 30 分钟 / refresh 30 天轮换**,旧 refresh 进黑名单;
3. **`POST /auth/logout/all`** 提供一键全端下线;
4. 白名单 + 固定验证码这条风险(backlog K-1)与端数无关,**不因本设计而降低或升高**。

## 9. 风险

| 风险 | 处置 |
|---|---|
| 端判定错位把真设备顶掉 | 鉴权只看**令牌里的 `ct`**,不看请求头;头只在签发时用 |
| 老客户端集体掉线 | `ct` 缺省 `app` + imserver 对无 `ct` 的旧 token 兜底;上线前用线上 1.0.10 实测一次 |
| 扇出导致重复投递 / 未读算错 | 未读仍是 `(owner, conv)` 一份;`self_read` 只增不减,重复帧幂等 |
| 迁移失误 | 两个迁移都是**新建表**,不动既有列;回滚 = 回退镜像 + 回退后端 SHA(表留着不影响旧代码) |

**回滚**:后端回退到上一个 `origin/master` SHA;imserver 回退镜像 tag。两端**必须一起回**(只回一端会因 `sv` 语义不一致互相拒绝)。

## 10. 明确不做 / 留给后续

- 删除 `User.session_version` 列与 `im_user.session_version` 列 —— 独立清理项,等本设计稳定一个版本后再做
- 设备管理页、设备名称、按设备踢人
- 第三种端(如平板 / 桌面客户端)
- 多台手机同时在线
