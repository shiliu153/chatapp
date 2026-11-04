# 已读回执(消息已读状态)设计

- **日期**:2026-11-04
- **对应待办**:[backlog C-2](../../backlog/2026-11-03-todo.md)
- **状态**:待批准 → 实施
- **范围**:`imserver/`(C++ 协议 + 存储)、`app/`(Flutter)、`web/`(Vue)

---

## 1. 问题与现状(已核实,不是猜测)

backlog 原文写「当前只是客户端未接」,**核实后不准确**。逐条查证结果:

| 环节 | 现状 | 证据 |
|---|---|---|
| 客户端上报已读 | **已有** | App `self_im_client.dart:352` `markConversationRead` 发 `{type:'read',data:{peer,seq:0}}`;Web `im/self/client.ts:409` 同 |
| 服务端落库 | **已有** | `ws_server.cpp:481 handle_read` → `message_service.cpp:123 mark_read` → `conversation_repo.cpp:168 mark_read` 写 `im_conversation_state.read_seq`(GREATEST 单调) |
| 服务端通知对端 | **没有** | `handle_read` 只 `send_raw(ack_frame(id, ok))` 回发送者,**不向对端推帧** |
| 对端读到哪(离线补拉) | **查不到** | `im_conversation_state.read_seq` 属「读者自己」的行;`ConversationView` / `GET /im/api/conversations` 都不含对端 `read_seq` |
| 客户端渲染 | **没有** | App/Web 全仓无已读态 UI |

**结论:必须两端都改。** 只改客户端会得到一个「永远显示未读」的假状态;只改服务端没有消费者。

## 2. 语义定义(先定死,避免各端理解不一致)

1. `seq` 是**一对会话共享**的单调序号(不是每用户),所以「B 读到 seq N」= 「会话里 seq ≤ N 的消息 B 都看过了」,**其中包含 A 发的**。
2. `read_seq` 语义是「**我**读到哪」,存在**我**的 state 行。对端要看的是**我的** read_seq,即 `peer_read_seq`(站在对端视角)。
3. 由此推出显示规则(A 看自己的气泡):
   - 我发消息 `seq = s`,对端 `peer_read_seq = N`
   - `s ≤ N` → **已读**;`s > N` → **未读**
4. **只有我方消息**需要状态;对方消息不显示(对方是否读自己的消息与我无关)。

## 3. 协议(唯一的契约变更)

### 3.1 上行 `read` 帧 —— **不变**(客户端已在用)

```json
{"v":1,"type":"read","id":"read-1720000000000","data":{"peer":"u9","seq":0}}
```

`seq=0` = 「读到该会话最新」,服务端解析为 `conversation.last_seq`(现有行为,`message_service.cpp:127`)。

### 3.2 下行 `read` 帧 —— **新增**(服务端 → 被读的一方)

```json
{"v":1,"type":"read","data":{"peer":"u7","seq":123}}
```

- 触发:任何 `read` 帧落库成功后,若对端在线则推一帧(对端离线则只落库,靠 §3.3 补拉)。
- `peer` = **读消息的人**(即收帧者的对端),`seq` = 他读到的位置(**不是** `last_seq`,是 `GREATEST` 之后的实际值)。
- 收帧方:把 `peerId == peer` 且 `isSelf` 且 `seq ≤ N` 的消息标为已读。
- **无 `id` 字段**:这是服务端主动推的,**不要求 ack**,客户端也不应回。

### 3.3 `GET /im/api/conversations` 响应 —— **新增字段**

每个 item 增加 `peer_read_seq`(整数,缺省 0):

```json
{"peer":{"id":"u9","nickname":"…","avatar":"…"},"unread":0,"last_seq":42,"peer_read_seq":17,"updated_at":1720000000000}
```

用途:打开会话 / 重连后**补拉已读态**(§验收「断线重连后已读态可补拉」)。`GET /im/api/messages` **不加**该字段 —— 它按 `peer` 查历史,加字段要改三端 history 解析,收益重复;客户端打开会话时用一次 conversations 请求取。

### 3.4 为什么不改 `history` 帧/`messages` 响应

单一事实来源:已读态**只**由 `peer_read_seq` + 下行 `read` 帧驱动。少一个入口就少一处不一致。

## 4. UI 口径(「心跳」规则下的最小实现)

- **我方气泡**尾部追加一个 11px 状态词,顺序优先级:`isFailed` → 「重发」;`isPending` → 「发送中」;已读 → 「已读」;**未读不显示任何字**。
- 理由:微信口径。显示「未读」会在每条消息上反复出现(一屏十几条),等于噪声;而且「未读」无法区分「已送达未读 / 没送达」。验收里的「已读/未读」在本实现中体现为「**有/无『已读』标记**」,在 spec 与本条 backlog 记录里写明。
- **灰条(system_notice)、撤回消息、对方消息**不显示状态。
- 颜色走 token(中性色三级),不引入新色值,不加动效。
- 腾讯后端分支:capabilities 增加 `readReceipt`(腾讯 `false`),`false` 时一律不渲染 —— D-4 删除腾讯分支后该开关自然消失。

## 5. 边界与非目标

| 项 | 结论 |
|---|---|
| 多设备同账号 | 单设备登录已强制(`session_version`),不考虑多端已读合并 |
| 未读数(`unread`) | 与已读回执是两条链路,`unread` 归零逻辑**不动** |
| 「已送达」 | **不做**:当前协议无 delivery ack,send ack 只代表服务端落库 |
| 群聊/多人已读 | **不做**:产品是 1v1 |
| 已读的已读(双向实时) | 不做群组态;1v1 双向本来就都拿得到 |
| 历史消息的初始态 | 打开会话时用 `peer_read_seq` 一次性算,不逐条查 |

## 6. 风险

1. **广播风暴**:`read` 帧可被刷 → 现有 `ip_counter_`/`read_table_` 限流已在入口(`/im/api/conversations` 有;WS `read` 帧目前**无**独立限流)。实施时给 `read` 帧加与 `send` 同级的轻量限流(复用 `RateLimiter`,按 uid 每分钟 N 次),避免「每滚一屏发一次 read 帧」打爆对端推送。
2. **单调性**:`read_seq` 用 `GREATEST` 更新,乱序到达的旧 read 帧不会回退 —— 客户端也要按「只增不减」处理(收到更小的 N 忽略)。
3. **对端 state 行不存在**:`peer_read_seq` 默认 0(从未读过),不是错误。
