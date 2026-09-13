# 在线状态(最后活跃)设计

日期:2026-09-13
状态:已与用户逐节确认(见 §8 决策记录),待用户终审
上游:后端标准化(错误码/限流/request_id 约定,`specs/2026-09-12-backend-standardization-design.md`);复用单设备登录引入的 45 秒登录态心跳(见 CLAUDE.md「单设备登录」节)
背景:用户提出「抖音式查看用户是否在线」。探索结论:Flutter IM SDK 的 `getUserStatus`/`subscribeUserStatus` 需腾讯控制台开功能开关 + 升级付费套餐(否则 72001),且只返回在线/离线/未登录三态、**不给「最后活跃时间」**——与需求冲突;故选自建方案(用户选 A)。

## 1. 目标与范围

1. **三处展示**(抖音式):
   - 消息列表:在线 → 头像右下角绿点(白描边,直径 ~10px);离线 → 不显示任何标记
   - 聊天页标题:昵称下方一行小字 —— 在线「● 在线」(绿)/ 离线「x 分钟前在线」(灰)
   - 发现卡(滑卡):信息区昵称旁 —— 在线「● 在线」(绿)/ 离线「x 分钟前在线」(灰)
2. **「在线」的定义**:最近 **120 秒**内 App 有过认证请求(45s 心跳 ×2.67,留一个周期抖动余量)。语义 = "App 打开着";App 被杀/后台被系统冻结 → 最多 2 分钟转离线并展示最后活跃时间。
3. **离线文案**:相对时间 —— 刚刚(<1 分钟)/ x 分钟前(<1 小时)/ x 小时前(<24 小时)/ x 天前(≥24 小时;7 天后数据过期,不显示)。
4. **刷新时效**:进入页面批量查一次 + 页面打开期间 **45 秒**定时刷新;多个页面登记的人合并去重成一次请求。
5. **可见性**:沿用全应用「拉黑 = 双向不可见」;被拉黑者从结果中省略。
6. **数据源**:自建(Redis 时间戳),不依赖腾讯 IM 在线状态能力。

**非目标(YAGNI)**:隐身开关(后续可加);真实时推送(订阅/长连接事件);按设备维度;独立「匹配列表」页面(不新建,配对的人都在消息列表);消息列表离线文案(会话行已有预览与时间,塞不下);touch 写入节流(先每次请求都写);presence 落 MySQL(Redis 重启丢历史最后活跃,可接受)。资料页按用户选择不做。

## 2. 数据设计(Redis)

- 键 `presence:{user_id}` → Unix 时间戳(秒),TTL **7 天**;7 天未活跃则查不到,视为"未知"。
- **写入点唯一**:`accounts/authentication.py::SessionJwtAuthentication.get_user()` 校验通过后调用 `users/presence.py::touch(user_id)`;未认证请求(health 等)不写。写失败 try/except 静默记日志,**绝不影响正常请求**。
- **在线判定**:`now - ts ≤ 120s`。
- **前端零上报改动**:现有 45s 登录态心跳 + 所有认证请求天然就是"我在线"信号。
- **测试隔离**:走现有缓存别名(测试自动 DB15);用例需 `cache.clear()` 防跨用例残留(同限流用例纪律,不碰开发数据 DB0)。

## 3. 接口设计(新接口,前缀 `/api/v1`,挂现有鉴权)

```
GET /api/v1/presence?user_ids=3,5,7     # 逗号分隔,去重后 ≤100 个
→ 200
{"results": [
  {"user_id": 3, "online": true,  "last_active_at": "2026-09-13T14:30:00+08:00"},
  {"user_id": 5, "online": false, "last_active_at": "2026-09-13T11:02:10+08:00"}
]}
```

**规则**:
- 返回顺序与请求给出顺序一致;以下 id **直接从 results 省略**(不报错、不泄露关系):被拉黑(双向,复用 `moderation.services.blocked_user_ids`)、不存在、自己、重复项、被重封禁(与公开资料卡 404 语义一致)。
- 无记录(从未活跃/超 7 天)→ `online: false, last_active_at: null` → 前端不显示。
- 参数不合法(缺失/空/非整数/超 100)→ 400 + 中文 message(全局异常处理器既有格式)。
- Redis 不可用 → 全部 `last_active_at: null`,记日志,不 500。
- 限流:新 scope `presence` = 600 次/小时/人(进 `DEFAULT_THROTTLE_RATES`,env 可调;量级参考:一个前台页面 45s 一次 ≈ 80/小时)。
- 重封禁用户被全局权限类自动 403(既有行为,无需额外代码)。

**代码落点**:`users/presence.py`(touch + 批量查询服务)、视图进 `users/views.py`(`PresenceView`),路由注册在 `config/api_urls.py` 顶层 `path("presence", ...)`(与 `/matches` 同级)。

## 4. 业务规则

- 「活跃」= 认证请求时间,不区分前后台(后台未被系统冻结时心跳照跑,和现有心跳行为一致,不额外做生命周期守卫)。
- 在线窗口 120s 与心跳 45s 的倍数关系:2.67 倍,容忍一次心跳丢失 + 网络抖动。
- 拉黑/解封/换号等关系变化无需清理 presence(查询侧实时过滤)。

## 5. 前端设计(新 `features/presence/`)

**新增两个文件**:
- `presence_repository.dart`(纯 IO):`fetchPresence(List<int>)` → `Map<int, Presence>`;`Presence {bool online, DateTime? lastActiveAt}`。
- `presence_controller.dart`(共享 autoDispose Notifier):`track(List<int> userIds)` 登记"当前页面关心的人",立即查一次并维持 45s 定时器;多页面登记的人**合并去重成一次请求**;间隔做成可注入 provider(测试 override,仿 `heartbeatIntervalProvider`);刷新失败保留旧值、下个周期重试,**不弹 SnackBar**;没有页面 watch 时自动销毁、定时器取消。

**`core/format.dart` 新增**:`formatLastActive(DateTime)` → 刚刚 / x 分钟前 / x 小时前 / x 天前(与 `formatPostTime` 同风格;不做「昨天」分支,7 天外的数据本身已过期)。

**三处接线**:

| 页面 | 数据来源 | 展示(ASCII 小样) |
|---|---|---|
| 消息页 `chats_page` | 会话列表 → 经 `matchCache` 把 IM id(`u7`)翻成数字 userId(`MatchEntry.userId`);`system_notice` 跳过;matchCache 未就绪先不显示 | 在线:头像右下角绿点<br>`╭──────╮`<br>`│ 头像 │●   昵称(加粗)`<br>`╰──────╯    最后一条消息预览…`<br>离线:不显示标记 |
| 聊天页 `chat_page` | 进入时 `track([当前对方 userId])` | 顶栏标题昵称下方小字行:<br>`← 昵称`<br>`  ● 在线`(绿)<br>`← 昵称`<br>`  x 分钟前在线`(灰,离线) |
| 发现页 `discovery_page` + `profile_card` | 每拉一批候选 → `track(这批卡片的 userId)` | 信息区昵称旁:<br>`│ 小雨 24  ● 在线 │`(绿)<br>离线:`│ 小雨 24 · x 分钟前在线 │`(灰) |

**边角**:拿不到数据(未知/接口失败)→ 一律不显示,不显示"离线"占位;绿点仅点缀,不阻塞任何列表渲染。

## 6. 测试与验证

**后端(预计 +12~15 用例,基线 310 全绿)**:
- `users` 服务层:touch 写入;未认证请求不写;120s 窗口边界(119s 在线 / 121s 离线);批量查询;拉黑双向省略;不存在/自己省略;参数校验 400;未鉴权 401;限流 429;Redis 故障降级(mock 抛错 → 200 + null)。
- 认证钩子:带 Bearer 请求后 Redis 出现 `presence:{uid}`。

**Flutter(预计 +10~12 用例,基线 170 全绿,analyze 零告警)**:
- repo 解析;controller 合并去重/45s 定时(interval override)/失败保留旧值;`formatLastActive` 各档文案;消息列表绿点(在线/离线/系统通知);聊天页小字两态;发现卡两态;`pageJson` 铺 presence 响应(沿用 harness 假网络)。

**手测(双模拟器)**:
1. A、B 均登录 → B 端消息列表 A 头像绿点、聊天页「● 在线」、发现页卡片「● 在线」。
2. A 杀 App → ≤2 分钟 B 端转「x 分钟前在线」;A 重开 → 下一个刷新周期(≤45s)绿点回来。
3. B 拉黑 A → B 端不再显示 A 的任何状态(接口省略)。
4. A 被第二台设备顶号 → A 侧停心跳 → B 端 ≤2 分钟转离线。

## 7. 改动面

| 端 | 文件 | 动作 |
|---|---|---|
| 后端 | `users/presence.py` | 新增:touch / 批量查询 |
| 后端 | `accounts/authentication.py` | 校验通过后 touch |
| 后端 | `users/views.py` + `config/api_urls.py` | `GET /api/v1/presence` |
| 后端 | `config/settings.py` | `DEFAULT_THROTTLE_RATES` 加 `presence` |
| 前端 | `features/presence/presence_repository.dart`、`presence_controller.dart` | 新增 |
| 前端 | `core/format.dart` | `formatLastActive()` |
| 前端 | `features/chat/chats_page.dart` | `_Avatar` 绿点 + track |
| 前端 | `features/chat/chat_page.dart` | 标题小字 + track |
| 前端 | `features/discovery/discovery_page.dart`、`widgets/profile_card.dart` | 卡片在线标识 + track |
| 文档 | `CLAUDE.md` | 交付后补章节(惯例) |

**已知取舍**:touch 走认证热路径,每请求一次 Redis SETEX(亚毫秒);先按最简单实现,量大了再考虑节流。

## 8. 关键决策记录

- 展示位置:消息列表 + 聊天页 + 发现卡(资料页不做)(用户多选)。
- 离线展示:在线 + 「最后活跃时间」(用户选 2,否决"只标在线")。
- 刷新时效:拉取快照 + 45s 定时刷新(用户选 1,否决更快轮询/真实时推送)。
- 数据源:自建 Redis(用户选 A)——腾讯方案需付费套餐且无最后活跃时间,与需求冲突(用户已知悉)。
- UI 样式:三处均选推荐款(头像右下角绿点 / 昵称下方小字行 / 信息区昵称旁),用户逐项确认(附 ASCII 小样)。
- 视觉沟通:沿用文字描述 + ASCII 小样,不开浏览器伴生页(与既往偏好一致)。
