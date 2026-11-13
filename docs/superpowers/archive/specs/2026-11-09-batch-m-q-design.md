# 批次 M–Q 设计:会话管理 / 登录设备 / 滑卡增强 / 使用报告 / 聊天敏感词

- 状态:**待实施**(设计已定稿,2026-11-09 主人拍板选型)
- 立项日期:2026-11-09
- 相关:[AGENTS.md](../../../../AGENTS.md)(执行约束)、[CLAUDE.md](../../../../CLAUDE.md)(契约)、
  [心跳 UI 规则](../../specs/2026-09-15-ui-design-language-design.md)(App UI 强制)、[docs/api/](../../../api/README.md)(接口文档门禁)、
  [实施计划](../plans/2026-11-09-batch-m-q.md)

---

## 1. 背景与选型

A–E 五批、F–J 五批、K(多端在线)、L(输入中 + 引用回复)全部闭环并随 **1.0.11** 上线,
`docs/backlog/` §7 只剩四条运维尾巴(对象存储 / 树莓派容量 / TOTP 重绑 / Loki 常驻),**没有产品向待办**。
本轮从 6 个候选中由主人选定 5 项(第 6 项「资料语音自我介绍」本轮不做):

| 批次 | 功能 | 一句话 |
|---|---|---|
| **M** | 登录设备管理 | 看到自己在哪些端登录过,并能单独踢掉某一端 |
| **N** | 会话管理三件套 | 会话置顶 / 免打扰 / 主动删除会话 |
| **O** | 滑卡增强 | 30 秒内撤销上一次误划 + 每日喜欢额度 |
| **P** | 个人使用报告 | 周/月/年的配对、喜欢、访客、动态、粉丝数字 |
| **Q** | 聊天文字敏感词 | 本地词库拦聊天文本(不接第三方机审) |

### 1.1 执行方式变更(2026-11-09 实测后定)

原定「实现交给 WSL superagent worker」**本轮不可用**,证据:

| 检查 | 结果 |
|---|---|
| WSL `getent hosts api.github.com` | 解析到 `127.0.0.1`(不是真实地址) |
| WSL `curl https://github.com` | `000`(失败);`curl https://www.baidu.com` = `200`(普通外网通) |
| 宿主 `127.0.0.1:7897` | **无监听**(`ProxyEnable=0`,clash 未运行) |
| 宿主直连 `https://api.github.com` | `200`(走 `重大VPN` / `vgate0` 的 TUN 路由) |

即:GitHub 只有宿主能通,而 WSL 是 NAT 出网、绕不过宿主 TUN,VPN 也没有 LAN 共享代理。
**结论:worker 连 issue 都轮询不到,不能接活。** 本轮实现改为 **Windows 会话内联**,工具链已核实可用:

| 依赖 | 实测 |
|---|---|
| Docker | 29.8.2(MySQL/Redis 走 `docker-compose.ci.yml`) |
| Node | v22.15.0(与 `web` 轨要求一致;Node 24 会红) |
| Git Bash | 有(`scripts/verify.sh` 在 Git Bash 下跑) |
| Python | conda env `Django` |
| Flutter | 3.47.2 |
| 模拟器 | `emulator-5554` 在线 |

由此产生的两条流程差异(仅本轮有效):

1. **合并由本会话执行**。主人 2026-11-09 明确授权「每批自行验收,没有问题就直接合并,我只做最后验收」,
   本条**只覆盖 squash 合并**,不覆盖发版。
2. **发版动作一律不做**:不升版本号、不打 tag、不建 Release、不部署生产、不跑 `docs/ops/release.md`
   的发版步骤 —— 全部留给主人在全部批次完成后统一执行。

worker 网络修复(宿主代理 LAN 共享或 `netsh portproxy`)**另立事项**,不阻塞本轮。

---

## 2. 批次总览与顺序

| 批次 | 栈与 PR 数 | 顺序理由 |
|---|---|---|
| **M** 登录设备 | backend → app → web(3 PR) | 改动面最小,先把「分支→verify→PR→CI→合并→同步」整条链路跑顺 |
| **N** 会话管理 | imserver → app → web(3 PR) | 唯一要动 imserver 表结构 + 镜像构建的一批,放在链路已验证之后 |
| **O** 滑卡增强 | backend → app → web(3 PR) | 纯 Django + 前端,与 M/N 零耦合 |
| **P** 使用报告 | backend → app → web(3 PR) | 同上,只读聚合 |
| **Q** 敏感词 | imserver(1 PR) | 与前面零耦合,风险独立,放最后 |

**每批内部固定顺序**:先服务端(契约源头),再 App,再 Web。**同一批里后一栈的 PR 依赖前一栈已合并**。

**每批合并后立刻**:Windows 仓库 `git pull --ff-only`;WSL 母体 `/root/src/chatapp` 同步(等 worker 修复后才会用到,本轮只保证 Windows 侧不落后)。

---

## 3. 批次 M:登录设备管理

### 3.1 现状

- `accounts.DeviceSession(user, client_type, version, created_at)`,`unique(user, client_type)`,
  读写唯一入口 `chatapp/accounts/device_session.py`(批次 K)。
- 已有 `POST /api/v1/auth/logout/all`(全端下线),**没有**「看设备」与「踢单端」。
- `presence:{uid}` 是**账号级** Redis 时间戳(120 秒窗口),不区分端。

### 3.2 决策

| 决策 | 取值 | 理由 |
|---|---|---|
| 新列 | `DeviceSession.last_active_at`(可空 `DateTimeField`) | 只加这一列;不加 UA/IP —— 个人项目用不上,且多一份隐私面 |
| 写入时机 | 登录签发令牌、`/auth/token/refresh` 成功时更新 | 走 `device_session.py` 唯一入口,不在视图里散写 |
| 「在线」口径 | **不按端判在线**,只展示「最近活跃时间」;`current` 由请求头 `X-Client` 判定 | presence 是账号级,按端拆要动心跳链路,收益不成比例 |
| 列表接口 | `GET /api/v1/devices` → `{results:[{client_type, client_label, current, created_at, last_active_at}]}` | 端类型只有两种,不分页 |
| 踢单端 | `DELETE /api/v1/devices/{client_type}`:该端 `version + 1` + **经 Celery** 踢该端 IM 连接 → `204` | 复用 K 批 `bump_device_version` 与 `im.tasks.kick_user(client_type=...)`;`im` 副作用只走 `im/tasks.py` |
| 踢当前端 | 允许(语义等同注销当前端),客户端收到 204 后自行跳登录 | 服务端不做特判,避免两套语义 |
| 不存在的端 | `204`(幂等) | 与 `/blocks`、`/logout` 的幂等口径一致 |
| 非法 `client_type` | `400` + `40001` | 错误契约 |
| 文档 | `docs/api/auth.md` 新增「登录设备」小节 | 设备与登录同源,不新开分册 |
| 契约 | 同 PR 重生成 `docs/api/openapi.yml` 与 `web/src/api/schema.d.ts` | 门禁 |

### 3.3 验收口径

**后端**(`scripts/verify.sh backend`):两端各一行且 `current` 正确;踢 `web` 后 web 的 access 返 `401/40101` 而 app 仍 `200`;
重复踢返 `204`;非法 `client_type` 返 `400/40001`;`makemigrations --check` 干净;注释覆盖门禁绿。
**App**(`scripts/verify.sh app` + 模拟器):设置 → 登录设备页两行,当前端标「本机」,点另一端的「下线」二次确认后该行消失;
踢自己当前端 → 提示并回登录页;`analyze` 零告警 + 新增 widget 测试。
**Web**(`scripts/verify.sh web`):`/settings/devices` 同构 + store 单测;`type-check` / `lint` 零告警。

**留给人验**:生产上两端真实同时在线时的互踢观感(需部署,本轮不做)。

### 3.4 风险

- 迁移 `accounts/0007` 只加可空列,无回填,可回滚(反向迁移丢列)。
- 踢端后客户端拿 `40101` 走既有强制登出通道,已有测试覆盖。

---

## 4. 批次 N:会话管理三件套(置顶 / 免打扰 / 删除会话)

### 4.1 现状

- `im_conversation_state(owner_id, conv_id, unread, read_seq, deleted, updated_at)`,
  `PRIMARY KEY (owner_id, conv_id)`,`KEY idx_owner_updated (owner_id, updated_at)`。
- 会话列表 `ConversationRepo::list` 按 `c.last_msg_at DESC` 排,已带 `peer_read_seq`。
- **删除会话的 WS 帧已存在**(`delete_conversation`,拉黑 / 解除配对在用),
  但**没有用户主动入口**;客户端 HTTP 面只有 `/im/api/conversations|messages|search`。

### 4.2 决策

| 决策 | 取值 | 理由 |
|---|---|---|
| 存储 | 迁移 `007_conversation_flags.sql`:`pinned_at BIGINT NOT NULL DEFAULT 0`、`muted TINYINT NOT NULL DEFAULT 0` | 与 `read_seq`/`unread` 同表同键(owner 维度) |
| 置顶排序 | `ORDER BY (s.pinned_at>0) DESC, s.pinned_at DESC, c.last_msg_at DESC` | 置顶组按「置顶时间倒序」,组内仍按最近消息 |
| 协议 | **不加 WS 帧**;新增客户端 HTTP `POST /im/api/conversations/flags`,body `{"peer":"u8","pinned":true,"muted":false}`,返回 `{pinned, muted}` | 加帧要三端 fixture 同改(成本 ×3),而这是低频写操作,HTTP 足够 |
| 鉴权 | 与 `/im/api/*` 同口径(IM token,含 `sv`/`ct` 校验) | 复用既有中间层 |
| 未配对 / 会话不存在 | `404` + `40401` | 与 messages 一致 |
| 幂等 | 重复设置同值返 `200` 且状态不变 | |
| 免打扰语义 | **只影响客户端表现**:会话行显示静音图标,未读只显示灰点不显示数字 | 本项目无离线推送,服务端没有可抑制的通道;不改未读统计口径 |
| 删除会话 | 复用既有 WS 帧,客户端补长按入口 + 二次确认 | 服务端零改动 |
| 索引 | **不新增**;会话数个人项目 < 100,排序表达式可接受 | 避免为表达式建索引反而拖慢写路径 |

### 4.3 验收口径

**imserver**(`scripts/verify.sh imserver`):unit —— flags 写入/幂等/未配对返回 false;
排序断言「置顶优先、置顶组内按置顶时间、非置顶按最近消息」;integration —— HTTP 鉴权 `401`、未配对 `404`、
置顶后 `GET /im/api/conversations` 顺序变化、`muted` 字段回显。
**App**(+ 模拟器):会话列表长按 → 置顶 / 免打扰 / 删除三项;置顶会话进「置顶」分组;免打扰显示静音图标 + 灰点;
删除 → 确认 → 行消失;`analyze` 零告警 + 新增测试。
**Web**:右键菜单同构 + 单测;`type-check` / `lint` 零告警。

**留给人验**:生产 imserver 镜像切换与真实两账号的置顶/免打扰观感(本轮不部署)。

### 4.4 风险与部署顺序

- **部署顺序硬约束**:`007` 迁移必须先于新镜像生效 —— 新代码读旧表会报「列不存在」。
  写进发版清单,由主人执行时按「先 migrate 再换镜像」。
- 排序表达式使 `idx_owner_updated` 不再能覆盖排序;量级小可接受,若将来会话数上千再议。

---

## 5. 批次 O:滑卡增强(撤销 / 每日额度)

### 5.1 现状

- `POST /discovery/swipe` 幂等(`Swipe` 唯一约束),互喜建 `Match` + 双方 IM 灰条。
- 候选池排除「已划过」用 `NOT EXISTS`(A-2 索引整改后受 `test_query_budget` 门禁保护)。

### 5.2 决策

| 决策 | 取值 | 理由 |
|---|---|---|
| 撤销窗口 | **30 秒**,且**只允许撤销「未产生配对」的那一次** | 撤销配对要回滚 `Match` + IM 双向拉黑 + 两条灰条,风险远大于收益 |
| 撤销实现 | **硬删除该 `Swipe` 行** + 记一条 info 日志 | 软删要改候选池排除条件(NOT EXISTS + 索引 + 查询预算),收益为零 |
| 无可撤销 | `400` + `40001`「没有可撤销的操作」 | 明确反馈优于静默 |
| 额度 | `SWIPE_DAILY_LIKE_LIMIT`(默认 `0` = 不限),Redis 日计数 `swipe_like:{uid}:{yyyymmdd}` | 复用既有 Redis;默认关闭 = 生产不配等于不存在 |
| 超限 | `429` + `42904`(新业务码),带 `Retry-After` | 与 `42901/42902/42903` 同族;先在 `config/error_codes.py` 查重 |
| 额度查询 | `GET /api/v1/discovery/quota` → `{like_limit, likes_used, likes_remaining}` | 前端要显示剩余次数 |
| 文档 | `docs/api/discovery.md` 两个新接口 + openapi + `schema.d.ts` | 门禁 |
| 幂等边界 | 撤销后再撤销 → `400`(已无最近一次) | |

### 5.3 验收口径

**后端**:撤销未配对的 like 后该人重新出现在候选池;撤销已配对 → `400`;超 30 秒 → `400`;
额度超限 → `429/42904`;默认 `0` 时不限;`test_query_budget` 的候选/配对预算不变。
**App**(+ 模拟器):发现页撤销按钮(30 秒倒计时环,过期置灰)+ 额度文案(仅 `like_limit>0` 时显示)。
**Web**:同构 + 单测。

**留给人验**:真实两人配合时的撤销体验(需部署)。

### 5.4 风险

- 撤销会「复活」对方卡片,但对方若已划过我,按既有候选口径自然排除,无需特判。
- 硬删 `Swipe` 会丢失「我曾划过他」的审计痕迹;个人项目接受,日志里留 uid + target。

---

## 6. 批次 P:个人使用报告

### 6.1 现状

无任何聚合统计接口。消息数据在 `chatapp_im` 库(imserver),**Django 侧读不到**。

### 6.2 决策

| 决策 | 取值 | 理由 |
|---|---|---|
| 指标(7 项) | 新增配对 / 喜欢给出 / 喜欢收到 / 访客 / 动态数 / 动态获赞 / 新粉丝 | 全部在 Django 库内,单库聚合 |
| **不含消息数** | 消息在 IM 库,要 imserver 加统计接口 —— 本轮不做,写进「后续」 | 跨栈成本大于价值 |
| 接口 | `GET /api/v1/stats/me?period=week|month|year`(默认 `week`) | 一次返回全部数字 |
| 时间口径 | 自然周(周一起)/ 自然月 / 自然年,`Asia/Shanghai` | 与运营日报同口径。**注意**:工单初稿举的 `2026-11-03 ~ 2026-11-09` 是滚动 7 天的形状,与本条自相矛盾,已作废;以文字规则为准(2026-11-09 是周一,本周应为 `2026-11-09 ~ 2026-11-15`) |
| 性能 | 7 条 `count()`,依赖既有 `(user, created_at)` 类索引;查询数预算 ≤ 8 | 量级小 |
| 缓存 | 不加 | 一次 7 条 count 可接受 |
| 文档 | 新分册 `docs/api/stats.md` + `docs/api/README.md` 索引 + openapi + `schema.d.ts` | `ApiDocsCoverageTests` 双向门禁 |

### 6.3 验收口径

**后端**:三种周期数字正确(造数跨周/跨月/跨年);未登录 `401`;`period` 非法 `400`;
`test_query_budget` 新增 `stats` 条目并通过;注释覆盖门禁绿。
**App**(+ 模拟器):设置 → 「我的数据」→ 报告页(周/月/年分段控件 + 7 张数字卡,暗色下正常)。
**Web**:`/stats` 页面同构 + 单测。

**留给人验**:生产真实数据的观感与数字是否符合直觉。

### 6.4 风险

- 大表 `count()` 在 2C2G 上:若 `Swipe`/`ProfileVisit` 的时间范围计数变慢,后续加 Redis 缓存(本轮不做)。

---

## 7. 批次 Q:聊天文字敏感词(imserver 单栈)

### 7.1 现状

昵称 / 简介 / 动态 / 评论都有敏感词校验(Django 侧),**聊天文本没有任何过滤**;
图片与语音靠 `/ops/` 人工抽审。imserver 上行 `send` 对 `kind=text` 只校验长度(`text_max`)。

### 7.2 决策

| 决策 | 取值 | 理由 |
|---|---|---|
| 词库位置 | `imserver/config/sensitive_words.txt`(一行一词,`#` 注释,UTF-8),随镜像打包 | 不引「Django 表 → imserver 拉取」的跨系统同步,省一整条链路;改词库 = 改文件 + 重启 |
| 覆盖与降级 | `IM_SENSITIVE_WORDS_FILE` 可覆盖路径;**文件不存在 = 不启用 + warning** | 不 fail-closed,避免误把聊天全挂 |
| 算法 | Aho-Corasick(自实现,~120 行,按 UTF-8 字节 + 中文 3 字节对齐) | 单消息 O(n),词表可扩到几千条 |
| 命中策略 | **拒绝发送**:`error_frame(42201, "消息包含违规内容")`,不落库 | 明确、可测;不做打码(用户看不懂自己发的字被改) |
| 作用面 | 只 `kind=text`;图片 / 语音 / 贴纸 / 系统灰条不查 | 图片语音已有人工抽审 |
| 指标 | `im_sensitive_blocked_total` | 观测命中量 |
| 词表初版 | 明确违规词 ~20–30 条,**标注「示例词表,主人按需增删」** | 不做内容判断上的越权 |
| 关掉的办法 | 清空词表文件(或指向空文件) | 一句话可回退 |

### 7.3 验收口径

`scripts/verify.sh imserver`:unit —— AC 匹配(中文/英文/大小写/词边界/超长文本/空词表)+
integration —— 含敏感词的 `send` 返 `42201` 且不落库、正常文本通过、贴纸不受影响、历史消息不受影响。

**留给人验**:生产镜像切换 + 词表内容是否合适(误伤由主人裁定)。

### 7.4 风险

- 误伤:词表由主人控制,清空即关闭。
- 性能:AC 在启动时构建一次,单消息匹配 < 10µs。

---

## 8. 全批共同约束

1. **一 PR 一条栈**;契约联动(openapi / `docs/api/*.md` / `web/src/api/schema.d.ts` / WS fixture / 心跳 token)同 PR 做完。
2. 每 PR 推之前跑 `scripts/verify.sh <该栈>` 并**把末尾输出贴进 PR 描述**。
3. **App UI 改动必须在 `emulator-5554` 逐页手测并截图留证**;PR 正文写手测记录。
4. **不发版**:不升版本号、不打 tag、不建 Release、不部署生产。
5. 每批合并后 Windows 仓库 `git pull --ff-only`。
6. 一个 PR 只解决一件事;顺手发现的坑写进 PR 正文「遗留」,不顺手改。

---

## 9. 工单拆分(13 张)

| # | 批次 | 栈 | 标题 | 依赖 |
|---|---|---|---|---|
| 1 | M | backend | 登录设备列表 + 单端下线接口 | — |
| 2 | M | app | 设置页「登录设备」 | #1 |
| 3 | M | web | 设置页「登录设备」 | #1 |
| 4 | N | imserver | 会话置顶 / 免打扰(`007` 迁移 + `/im/api/conversations/flags`) | — |
| 5 | N | app | 会话列表长按菜单(置顶 / 免打扰 / 删除) | #4 |
| 6 | N | web | 同上 | #4 |
| 7 | O | backend | 撤销上一次滑卡 + 每日喜欢额度 | — |
| 8 | O | app | 发现页撤销按钮 + 额度提示 | #7 |
| 9 | O | web | 同上 | #7 |
| 10 | P | backend | `GET /stats/me` 使用报告 | — |
| 11 | P | app | 「我的数据」报告页 | #10 |
| 12 | P | web | 同上 | #10 |
| 13 | Q | imserver | 聊天文本敏感词(本地词库 + AC) | — |

---

## 10. 明确不做(本轮)

| 项 | 理由 |
|---|---|
| 资料「语音自我介绍」 | 主人本轮未选 |
| 报告里含「消息条数」 | 消息在 IM 库,要 imserver 加统计接口;跨栈成本大于价值,留作后续 |
| 撤销「已产生配对」的滑卡 | 要回滚 Match + IM 拉黑 + 灰条,风险高 |
| 免打扰抑制服务端推送 | 本项目不做离线推送,没有可抑制的通道 |
| 按端判在线(设备页显示「在线中」) | presence 是账号级,按端拆要动心跳链路 |
| 敏感词命中入 Django 审计表 | 本轮只做拦截 + 指标;落库审计需要 imserver 回调 Django,留作后续 |
