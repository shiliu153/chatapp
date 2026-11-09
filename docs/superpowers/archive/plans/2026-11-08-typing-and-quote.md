# 输入中状态 + 引用回复实施计划

> **For agentic workers:** 本仓库**不使用** subagent-driven-development / executing-plans 派子 agent ——
> 实现按 [`~/.dsh/AGENTS.md`](../../../../AGENTS.md) 走**工单**:每张工单开成 issue 评论 `@agent` 交给 WSL 的 superagent worker,
> 本会话只做设计与验收。步骤用 checkbox(`- [ ]`)跟踪。

**Spec:** [2026-11-08-typing-and-quote-design.md](../specs/2026-11-08-typing-and-quote-design.md)

**Goal:** 聊天页顶栏显示「对方正在输入…」;长按消息可引用,气泡上方显示服务端生成的被引用快照。

**Architecture:** L-1 只加一对 `typing` 上下行帧(不落库、两层限流、只发对端);L-2 给 `send` 帧加可选 `ref_msg_id`,
服务端查库**自己生成快照**随消息落库(`im_message` 加两个可空列),下行 `message` 与历史接口在有引用时多一个 `ref` 对象。

**Tech Stack:** imserver C++20(MySQL + Redis)、Flutter 3.47、Vue 3 + TS。

## Global Constraints

- **一单一条栈**,唯一例外是**契约联动**:改 WS 帧必须 fixture + imserver + App + Web **同一次 PR** 做完。
- **验证唯一入口** `scripts/verify.sh <stack>`;推之前必须绿,末尾输出贴进 PR 正文。
- 新增/改 `.py` 必须补 docstring(`Args:`);**C++ 新增构造/函数写注释说明「为什么」**(本项目 C++ 侧无强制覆盖率,但契约帧构造必须解释语义)。
- 改 `/api/v1` 接口必须同改 `docs/api/`;本次**不改** `/api/v1`(typing 与引用都在 imserver 内部契约里,不进 `docs/api/` 门禁)。
- **不要自己合并、不开 auto-merge**;App 有可见变化 → PR 开成 **draft** 并写「等待模拟器验收」。
- 绝对不要:改 `flutter/`、`.remember/`、`.env`、密钥文件;升版本号 / 打 tag / 建 Release。

## 工单映射

| 工单 | Task | 栈 | 依赖 |
|---|---|---|---|
| **L-1** | Task 1 + 2 + 3 | imserver(主)+ App + Web,一个 PR | 无 |
| **L-2** | Task 4 + 5 + 6 | imserver(主)+ App + Web,一个 PR | L-1 合并后 |

## 文件结构

| 文件 | 职责 |
|---|---|
| `imserver/src/net/frames.h` | 新增 `typing_frame(peer)`;`message_json` 里的 `ref` 由 http_api 拼 |
| `imserver/src/net/ws_server.cpp` | 帧分发加 `typing`;`handle_typing` 实现(限流 + 校验 + 只发对端) |
| `imserver/src/util/ratelimit.h` | 复用既有令牌桶(`send_bucket_` 同款) |
| `imserver/src/service/message_service.h/.cpp` | `SendRequest` 加 `ref_msg_id` / `ref_snapshot`;`send()` 里生成快照 |
| `imserver/src/store/message_repo.h/.cpp` | insert 多两列;查询 SELECT 多两列;`find_by_id(conv, msg_id)` 供快照取数 |
| `imserver/src/net/http_api.cpp` | `message_json` 输出 `ref` 对象 |
| `imserver/migrations/006_quote.sql` | 两个可空列 |
| `imserver/tests/fixtures/ws/*.json` | L-1 加 `typing` 两帧;L-2 加 `send_quote` / `message_quote` |
| `app/lib/im/self_im_client.dart` | `sendTyping()` / 解析 `typing`;`refMsgId` 随 send 上行;解析 `ref` |
| `app/lib/im/im_client.dart` | 接口加 `sendTyping` / `ImTyping` 事件 / `ChatMessage.ref` |
| `app/lib/features/chat/chat_page.dart` | 顶栏「正在输入…」;输入框节流发送;引用条 |
| `app/lib/features/chat/widgets/message_bubble.dart` | 引用块渲染 + 点击跳转 |
| `web/src/im/types.ts` / `self/client.ts` | `typing` 事件与 `sendTyping`;`ref` 字段 |
| `web/src/stores/chat.ts` | typing 状态(5 秒过期)、`refMsgId` 发送、引用条状态 |
| `web/src/features/chat/ChatPage.vue` | 顶栏提示、引用条 |
| `web/src/features/chat/MessageBubble.vue` / `MessageMenu.vue` | 引用块渲染;菜单加「引用」 |

---

### Task 1: typing 帧与服务端限流(imserver)

**Files:**
- Modify: `imserver/src/net/frames.h`
- Modify: `imserver/src/net/ws_server.cpp:341-360`(分发)、新增 `handle_typing`
- Modify: `imserver/src/net/ws_server.h`(声明 + 令牌桶成员)
- Modify: `imserver/tests/fixtures/ws/client_to_server.json`、`server_to_client.json`
- Modify: `imserver/tests/frames_fixture_test.cpp`
- Create: `imserver/tests/integration/test_typing.py`

**Interfaces:**
- Produces: `std::string typing_frame(const std::string& peer)`;上行 `{"type":"typing","data":{"to":"u14"}}`;下行 `{"type":"typing","data":{"peer":"u12"}}`

- [ ] **Step 0: 先核实(结论写进 issue 评论)**

```bash
git grep -n 'send_bucket_\|RateLimiter\|ratelimit' -- imserver/src/net/ws_server.h imserver/src/util/ratelimit.h
git grep -n 'im_pair\|pair_exists' -- imserver/src/service/message_service.h
```

确认:① 令牌桶类型与构造参数(照 `send_bucket_` 写一个 `typing_bucket_`);② `send` 里「配对校验」的确切函数名,typing 复用同一个。

- [ ] **Step 1: fixture 先行**

`client_to_server.json` 追加:

```json
{"name": "typing", "frame": {"v": 1, "type": "typing", "data": {"to": "u8"}}}
```

`server_to_client.json` 追加:

```json
{"name": "typing", "frame": {"v": 1, "type": "typing", "data": {"peer": "u8"}}}
```

- [ ] **Step 2: 写失败用例**

`imserver/tests/integration/test_typing.py`(写法抄 `test_self_read.py`):

```python
"""输入中状态的集成测试:只发对端、限流静默、未配对不发。"""

import asyncio
import json
import os
import time

import jwt
import websockets

from _support import ensure, pair

SECRET = os.environ["IM_JWT_SECRET"]
WS = os.environ.get("IM_TEST_WS", "ws://127.0.0.1:19100/im/ws")


def token(uid: int, client_type: str = "app") -> str:
    """签一个带端类型的测试 JWT(与 Django 侧同口径)。"""
    now = int(time.time())
    return jwt.encode({"sub": f"u{uid}", "uid": uid, "iat": now, "exp": now + 3600,
                       "jti": "test", "ct": client_type}, SECRET, algorithm="HS256")


async def connect(uid: int, client_type: str = "app"):
    """连 WS 并完成握手。"""
    ws = await websockets.connect(WS)
    await ws.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token(uid, client_type)}}))
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == "auth_ok":
            return ws


async def recv_until(ws, type_, timeout=3):
    """丢弃无关帧,直到拿到指定类型。"""
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if message["type"] == type_:
            return message


async def expect_silence(ws, seconds=1.5):
    """断言这段时间内没有任何帧下发。"""
    try:
        frame = json.loads(await asyncio.wait_for(ws.recv(), seconds))
    except asyncio.TimeoutError:
        return
    raise AssertionError(f"不该收到任何帧,却收到: {frame}")


async def case_typing_reaches_peer_only(base: int) -> None:
    """1. A 打字:B 收到 typing;A 自己的另一端**收不到**(只发对端)。"""
    me, peer = base, base + 1
    ensure(me); ensure(peer); pair(me, peer)
    app_ws = await connect(me, "app")
    web_ws = await connect(me, "web")
    peer_ws = await connect(peer, "app")

    await app_ws.send(json.dumps({"v": 1, "type": "typing", "data": {"to": f"u{peer}"}}))
    frame = await recv_until(peer_ws, "typing")
    assert frame["data"] == {"peer": f"u{me}"}, frame
    await expect_silence(web_ws, 1.0)   # 自己的另一端不该收到
    for ws in (app_ws, web_ws, peer_ws):
        await ws.close()


async def case_typing_is_rate_limited(base: int) -> None:
    """2. 连发 10 帧:对端收到的远少于 10 且**不产生错误帧**(静默丢弃)。"""
    me, peer = base + 2, base + 3
    ensure(me); ensure(peer); pair(me, peer)
    app_ws = await connect(me)
    peer_ws = await connect(peer)
    for _ in range(10):
        await app_ws.send(json.dumps({"v": 1, "type": "typing", "data": {"to": f"u{peer}"}}))
    received = 0
    try:
        while True:
            message = json.loads(await asyncio.wait_for(peer_ws.recv(), 2))
            assert message["type"] == "typing", message   # 不能出现 error 帧
            received += 1
    except asyncio.TimeoutError:
        pass
    assert 1 <= received <= 4, received
    await expect_silence(app_ws, 0.5)   # 发起端不该收到任何错误回执
    for ws in (app_ws, peer_ws):
        await ws.close()


async def case_typing_requires_pair(base: int) -> None:
    """3. 未配对:对端收不到任何帧(静默丢弃,不回错误)。"""
    me, stranger = base + 4, base + 5
    ensure(me); ensure(stranger)
    app_ws = await connect(me)
    other_ws = await connect(stranger)
    await app_ws.send(json.dumps({"v": 1, "type": "typing", "data": {"to": f"u{stranger}"}}))
    await expect_silence(other_ws, 1.5)
    await expect_silence(app_ws, 0.5)
    await app_ws.close()
    await other_ws.close()


async def main() -> None:
    """依次跑三条用例(账号 id 按时间 + pid 取号,避免撞号)。"""
    base = 600000 + (int(time.time() * 1000) + os.getpid()) % 90000
    await case_typing_reaches_peer_only(base)
    await case_typing_is_rate_limited(base)
    await case_typing_requires_pair(base)
    print("test_typing ok: 只发对端 / 限流静默 / 未配对不发")


asyncio.run(main())
```

把 `test_typing.py` 挂进 `imserver/scripts/test_http.sh`(照 `test_self_read.py` 那一行加)。

- [ ] **Step 3: 跑一遍确认失败** → `docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh`;Expected: 超时收不到 `typing`(帧还不存在)

- [ ] **Step 4: 实现**

`frames.h`:

```cpp
/// 输入中状态(批次 L-1):只发给**对端**,不落库、不补拉。
/// 它是「可丢」信号 —— 丢了最多是对方晚一点看到「正在输入」,所以没有 id、不要 ack。
inline std::string typing_frame(const std::string& peer) {
  return nlohmann::json{{"v", 1}, {"type", "typing"}, {"data", {{"peer", peer}}}}.dump();
}
```

`ws_server.cpp` 分发处(`type == "revoke"` 附近)加:

```cpp
  if (type == "typing") {
    handle_typing(frame);
    return;
  }
```

`handle_typing`:

```cpp
/// 处理上行 `typing`:校验配对后只把一帧推给对端。
///
/// 为什么不回错误帧:typing 是可丢信号,给洪泛者任何反馈都只会鼓励继续打;
/// 限流超限、未配对、目标不存在一律静默返回。
void WsSession::handle_typing(const nlohmann::json& frame) {
  if (!typing_bucket_.allow(now_ms())) {
    return;                       // 限流:静默丢弃
  }
  const auto data = frame.value("data", nlohmann::json::object());
  const auto to_uid = parse_uid(data.value("to", std::string()));
  if (!to_uid.has_value() || *to_uid == uid_) {
    return;
  }
  auto self = shared_from_this();
  run_db([self, peer = *to_uid] {
    if (!self->messages_.pair_exists(self->uid_, peer)) {
      return;                     // 未配对:静默丢弃
    }
    self->registry_.send_to(peer, typing_frame(peer_id(self->uid_)));
  });
}
```

`ws_server.h` 加成员(照 `send_bucket_` 的写法):`RateLimiter typing_bucket_{1.0 / 2.0, 3};`

- [ ] **Step 5: 三端契约测试跟着改**

`frames_fixture_test.cpp` 断言 `typing_frame("u8")` 与 fixture 逐字段一致;App/Web 的解析在 Task 2/3 补。

- [ ] **Step 6: 跑 imserver 全套** → `test_unit.sh` 全绿 + `test_http.sh` 输出 `test_typing ok`

- [ ] **Step 7: 提交**

```bash
git add imserver
git commit -m "feat(imserver): 输入中状态 typing 帧(批次 L-1)"
```

---

### Task 2: typing(App)

**Files:**
- Modify: `app/lib/im/im_client.dart`(`sendTyping` 接口、`ImTyping` 事件)
- Modify: `app/lib/im/self_im_client.dart`(分发 `typing`、实现 `sendTyping`)
- Modify: `app/lib/features/chat/chat_controller.dart`(节流发送 + 5 秒过期状态)
- Modify: `app/lib/features/chat/chat_page.dart`(顶栏提示)
- Modify: `app/test/im/protocol_fixture_test.dart`、新增 `app/test/features/chat/typing_test.dart`

**Interfaces:**
- Consumes: Task 1 的帧
- Produces: `Future<void> sendTyping(String peerId)`;事件 `ImTyping(peerId)`;控制器暴露 `peerTyping`(bool)

- [ ] **Step 1: 写失败用例**

```dart
test('收到 typing 帧后 5 秒内 peerTyping 为真,之后自动变假', () async {
  fakeAsync((async) {
    final c = buildChatController();
    c.onImEvent(const ImTyping(peerId: 'u14'));
    expect(c.peerTyping, isTrue);
    async.elapse(const Duration(seconds: 4));
    expect(c.peerTyping, isTrue);
    async.elapse(const Duration(seconds: 2));
    expect(c.peerTyping, isFalse);
  });
});

test('连续输入只按 3 秒节流发 typing', () async {
  fakeAsync((async) {
    final c = buildChatController();
    c.onInputChanged('a');   // 立即发
    c.onInputChanged('ab');  // 3 秒内:不发
    async.elapse(const Duration(seconds: 3));
    c.onInputChanged('abc'); // 超过 3 秒:再发
    expect(c.sentTypingCount, 2);
  });
});
```

- [ ] **Step 2: 跑确认失败** → `cd app && ../flutter/bin/flutter.bat test test/features/chat/typing_test.dart`;Expected: `ImTyping` 未定义

- [ ] **Step 3: 实现** —— 事件与分发照 `ImSelfRead` 的写法加 `ImTyping`;`sendTyping` 发 `{"v":1,"type":"typing","data":{"to":peerId}}`;
控制器持 `_lastTypingSentAt`,节流 3 秒;收到事件起 5 秒定时器,`dispose` 时取消。

- [ ] **Step 4: 顶栏** —— 昵称下方(或替换在线状态那行)显示「对方正在输入…」,**只在 `peerTyping` 为真时出现**;离开聊天页时清零。

- [ ] **Step 5: 跑 analyze + test** → 零告警 + 全绿

- [ ] **Step 6: 提交**

```bash
git add app
git commit -m "feat(app): 输入中状态展示与节流发送(批次 L-1)"
```

---

### Task 3: typing(Web)

**Files:**
- Modify: `web/src/im/types.ts`、`web/src/im/self/client.ts`
- Modify: `web/src/stores/chat.ts`
- Modify: `web/src/features/chat/ChatPage.vue`
- Modify: `web/tests/unit/im-protocol-fixture.spec.ts`、新增 `web/tests/unit/chat-typing.spec.ts`

**Interfaces:** 同 Task 2 的 Web 版:`sendTyping(peerId)`、`typing` 事件、store 的 `peerTyping` 计算状态

- [ ] **Step 1: 写失败用例**(vitest,假 transport,照 `chat-self-sync.spec.ts` 写法)
- [ ] **Step 2: 跑确认失败** → `cd web && npm run test:run -- chat-typing`
- [ ] **Step 3: 实现** —— store 用 `setTimeout` 5 秒过期,**切会话/离开页面要清**;节流 3 秒
- [ ] **Step 4: 顶栏** —— `ChatPage.vue` 标题下方显示「对方正在输入…」
- [ ] **Step 5: 跑 type-check + lint + test:run**
- [ ] **Step 6: 提交**

```bash
git add web
git commit -m "feat(web): 输入中状态展示与节流发送(批次 L-1)"
```

---

### Task 4: 引用落库与快照(imserver)

**Files:**
- Create: `imserver/migrations/006_quote.sql`;`imserver/src/migrate.cpp` 加 `{6, "006_quote.sql"}`
- Modify: `imserver/src/service/message_service.h`(`SendRequest` 加 `ref_msg_id` / `ref_snapshot`)
- Modify: `imserver/src/service/message_service.cpp`(`send()` 里生成快照)
- Modify: `imserver/src/store/message_repo.h/.cpp`(insert/select 两列;`find_by_id(conv, msg_id)`)
- Modify: `imserver/src/net/http_api.cpp:130`(`message_json` 输出 `ref`)
- Modify: `imserver/src/net/ws_server.cpp`(`handle_send` 解析 `ref_msg_id`;下行 `message` 帧带 `ref`)
- Modify: fixtures(两帧)+ `frames_fixture_test.cpp`
- Create: `imserver/tests/integration/test_quote.py`

**Interfaces:**
- Produces: `SendRequest.ref_msg_id`(`std::optional<uint64_t>`)、`SendRequest.ref_snapshot`(`nlohmann::json`);
  `message_json` 在有引用时输出 `"ref": {msg_id, from, kind, text, revoked}`

- [ ] **Step 0: 先核实** —— `git grep -n 'INSERT INTO im_message\|SELECT .* FROM im_message' -- imserver/src` 找出所有读写 SQL(insert、历史、搜索、会话列表 `last_message`),漏一处就有一端看不到引用。

- [ ] **Step 1: 迁移**

```sql
-- 引用回复(批次 L-2):只加可空列,不改既有列,在线安全。
ALTER TABLE im_message
  ADD COLUMN ref_msg_id BIGINT UNSIGNED NULL,
  ADD COLUMN ref_snapshot TEXT NULL;
```

- [ ] **Step 2: 写失败用例**(`test_quote.py` 四条)

```python
"""引用回复的集成测试:快照由服务端生成、同会话校验、撤回标注、历史回放。"""

# case 1: A 引用 B 的文本消息 → B 收到的下行 message 里 ref.text 是**服务端截断后的原文**
#         且客户端夹带的 ref 字段被丢弃(发一条 ref.snapshot.text="伪造" 的帧,断言落库不是它)
# case 2: ref_msg_id 指向**另一个会话**的消息 → ack ok=false / 42201
# case 3: 引用一条已撤回的消息 → ref.revoked == true 且 ref.text == ""
# case 4: GET /im/api/messages 历史里同样带回 ref(离线补拉也能显示)
```

- [ ] **Step 3: 跑确认失败** → `test_http.sh`;Expected: `ref` 字段不存在

- [ ] **Step 4: 实现快照**

```cpp
/// 生成引用快照(**只能由服务端做**)。
///
/// 为什么不信客户端:客户端传快照等于允许任何人伪造「对方说过 X」。
/// 这里只接受 ref_msg_id,内容一律回库查。
nlohmann::json build_ref_snapshot(const MessageRow& row) {
  nlohmann::json snapshot = {{"msg_id", row.msg_id}, {"from", peer_id(row.from_id)},
                             {"kind", row.kind}, {"revoked", row.revoked_at.has_value()}};
  if (row.revoked_at.has_value()) {
    snapshot["text"] = "";
    return snapshot;
  }
  switch (row.kind) {
    case 1: snapshot["text"] = truncate_utf8(row.body, 120); break;   // 文本:前 120 字
    case 3: snapshot["text"] = "[图片]"; break;
    case 4: snapshot["text"] = "[语音]"; break;
    default: snapshot["text"] = "[贴纸]"; break;                       // kind=2 自定义/贴纸
  }
  return snapshot;
}
```

`send()` 里:有 `ref_msg_id` → `message_repo.find_by_id(conv_id, *ref_msg_id)`;
不存在或 `conv_id` 不同 → 返回失败(`handle_send` 回 `42201`「引用的消息不存在」);
存在 → `request.ref_snapshot = build_ref_snapshot(row)`。

- [ ] **Step 5: 透出** —— `message_json` 里:

```cpp
  if (row.ref_snapshot.has_value()) {
    item["ref"] = nlohmann::json::parse(*row.ref_snapshot);   // 快照原样透出,不再查库
  }
```

下行 `message` 帧同样带 `ref`(与 `/im/api/messages` 用同一个构造函数,别写两份)。

- [ ] **Step 6: 跑 imserver 全套** → unit + `test_http.sh` 输出 `test_quote ok`

- [ ] **Step 7: 提交**

```bash
git add imserver
git commit -m "feat(imserver): 引用回复落库与服务端快照(批次 L-2)"
```

---

### Task 5: 引用(App)

**Files:**
- Modify: `app/lib/im/im_client.dart`(`ChatMessage.ref`、`sendText/sendImage/...` 加 `refMsgId`)
- Modify: `app/lib/im/self_im_client.dart`(上行带 `ref_msg_id`;解析下行 `ref`)
- Modify: `app/lib/features/chat/chat_controller.dart`(引用条状态、发送后清空)
- Modify: `app/lib/features/chat/chat_page.dart`(引用条 UI + 输入栏上方)
- Modify: `app/lib/features/chat/widgets/message_bubble.dart`(引用块 + 点击跳转)
- Modify: `app/test/im/protocol_fixture_test.dart`、新增 `app/test/features/chat/quote_test.dart`

**Interfaces:** `ChatMessage.ref`(`{msgId, from, kind, text, revoked}`)、`controller.quoteTarget`、`sendText(text, refMsgId: …)`

- [ ] **Step 1: 写失败用例**

```dart
test('解析带 ref 的下行帧', () {
  final client = buildFixtureClient();
  final events = <ImEvent>[];
  client.events.listen(events.add);
  client.receiveForTest(fixtureFrame('message_quote'));
  await pumpEventQueue();
  final msg = events.whereType<ImNewMessage>().single.message;
  expect(msg.ref?.msgId, 123);
  expect(msg.ref?.text, '今晚吃饭?');
});

test('设了引用目标后 sendText 上行带 ref_msg_id', () async {
  final transport = FakeTransport();
  final client = buildClient(transport);
  await client.sendText('u14', '好,六点', refMsgId: 123);
  expect(transport.sentFrames.last['data']['ref_msg_id'], 123);
});
```

- [ ] **Step 2: 跑确认失败** → `cd app && ../flutter/bin/flutter.bat test test/features/chat/quote_test.dart`;Expected: `ref` / `refMsgId` 未定义

- [ ] **Step 3: 实现收发**

```dart
/// 引用目标(批次 L-2):输入栏上方的引用条与上行帧都读它。
class QuoteTarget {
  const QuoteTarget({required this.msgId, required this.from, required this.text});
  final int msgId;
  final String from;
  final String text;
}
```
`self_im_client.dart` 的上行组装处(`sendText` 等)在 `data` 里按需写 `'ref_msg_id': refMsgId`;
下行解析处读 `json['ref']` 构造 `QuoteRef(msgId, from, kind, text, revoked)`;控制器持 `quoteTarget`,发送成功后置空。

- [ ] **Step 4: 长按菜单加「引用」** —— 照 `message_bubble.dart` 里既有「撤回 / 复制」的入口写法加一项,点击后 `controller.setQuoteTarget(...)`;
`chat_page.dart` 在输入栏上方渲染引用条(发送者 + 摘要 + 关闭按钮)。

- [ ] **Step 5: 引用块与跳转** —— 气泡上方渲染引用块(`revoked` 时文案「消息已撤回」);
点击时在 `controller.messages` 里找该 `msgId`:找到 → 滚动并高亮 1.5 秒;找不到 → `AppToast`「原消息不在当前记录中」。

- [ ] **Step 6: analyze + test 全绿**

- [ ] **Step 7: 提交**

```bash
git add app
git commit -m "feat(app): 引用回复展示与发送(批次 L-2)"
```

---

### Task 6: 引用(Web)

**Files:**
- Modify: `web/src/im/types.ts`、`web/src/im/self/client.ts`
- Modify: `web/src/stores/chat.ts`
- Modify: `web/src/features/chat/MessageBubble.vue`(引用块)、`MessageMenu.vue`(加 `'quote'` 动作)
- Modify: `web/src/features/chat/ChatPage.vue`(引用条)
- Modify: `web/tests/unit/im-protocol-fixture.spec.ts`、新增 `web/tests/unit/chat-quote.spec.ts`

- [ ] **Step 1: 写失败用例**(`web/tests/unit/chat-quote.spec.ts`,假 transport)

```ts
it('带 ref 的下行帧解析成 ChatMessage.ref', () => {
  const client = makeFixtureClient()
  const seen: ChatMessage[] = []
  client.on('newMessage', (m) => seen.push(m))
  client.receiveForTest(fixtureFrame('message_quote'))
  expect(seen[0].ref).toEqual({ msgId: 123, from: 'u8', kind: 'text', text: '今晚吃饭?', revoked: false })
})

it('设了引用目标后 sendText 上行带 ref_msg_id', async () => {
  const { client, sent } = makeFixtureClientWithSpy()
  await client.sendText('u8', '好,六点', { refMsgId: 123 })
  expect(sent.at(-1)!.data.ref_msg_id).toBe(123)
})

it('revoked 的引用渲染成「消息已撤回」', () => {
  const wrapper = mount(MessageBubble, { props: { message: quotedRevokedMessage() } })
  expect(wrapper.text()).toContain('消息已撤回')
})
```

- [ ] **Step 2: 跑确认失败** → `cd web && npm run test:run -- chat-quote`;Expected: `ref` 未定义 / `ref_msg_id` 未带上

- [ ] **Step 3: 实现收发** —— `types.ts` 的 `ChatMessage` 加 `ref?: QuoteRef`;`client.ts` 的 `sendText/sendImage/sendVoice/sendSticker` 接受可选 `refMsgId` 并写进 `data.ref_msg_id`;
`stores/chat.ts` 加 `quoteTarget`(`{msgId, from, text} | null`)与 `setQuoteTarget / clearQuoteTarget`,发送成功后清空。

- [ ] **Step 4: 菜单与引用条** —— `MessageMenu.vue` 的 `emit('action', …)` 联合类型加 `'quote'` 并渲染「引用」项;
`ChatPage.vue` 处理 `'quote'` 动作 → `setQuoteTarget`;输入栏上方渲染引用条(发送者 + 摘要 + 关闭按钮)。

- [ ] **Step 5: 引用块与跳转** —— `MessageBubble.vue` 在气泡上方渲染引用块:`revoked` 时显示「消息已撤回」;
点击:本地 `messages[peerId]` 里有该 `msgId` → 滚动并高亮 1.5 秒;没有 → `AppToast` 提示「原消息不在当前记录中」。

- [ ] **Step 6: 跑三件套** → `npm run type-check && npm run lint && npm run test:run` 全绿

- [ ] **Step 7: 提交**

```bash
git add web
git commit -m "feat(web): 引用回复展示与发送(批次 L-2)"
```

---

## 验收(整批 L)

**自动化**:`scripts/verify.sh imserver` / `app` / `web` 全绿;契约自测(改 fixture 字段 → 三端同时红)做过并还原。

**留给人验(模拟器 + 浏览器,PR 里写清)**:
1. 两端同时在线:一端打字,另一端聊天页顶栏出现「正在输入…」,停止后 5 秒内消失;
2. 引用文本 / 图片 / 语音 / 贴纸各一条,气泡上方摘要正确,点击跳到原消息;
3. 引用一条已撤回消息 → 显示「消息已撤回」;
4. 自己的另一端**不该**看到自己触发的 typing。

## 上线顺序(发布那一轮)

```
① imserver 换镜像 + docker compose run --rm imserver --migrate(应用 006)
② 观察 im_sends_total / 错误率
③ 随下一个版本发 App/Web(两单都是纯增量帧,老客户端不受影响)
```

**回滚**:回退 imserver 镜像即可(006 只加可空列,旧代码不读也不影响)。

---

## 执行记录(2026-11-09 归档)

**状态:两单均合并进 `origin/master`,尚未上线。** 上线按上面「上线顺序」走(imserver 换镜像 + 跑
`006_quote.sql`,再随下一版本发 App/Web);归档时生产仍是 1.0.10 与旧 imserver 镜像。

| 单 | 栈 | PR | 合并 SHA | 结果 |
|---|---|---|---|---|
| L-1 | imserver + App + Web | #158 | `22b00aa` | `typing` 上下行帧;**只发对端**、未配对静默丢弃、令牌桶限流超限也静默(不给洪泛者任何反馈);App/Web 顶栏「对方正在输入…」5 秒过期、输入侧 3 秒节流 |
| L-2 | imserver + App + Web | #159 | `949a4e0` | `send` 帧加可选 `ref_msg_id`,服务端**回库查并自己生成快照**(客户端夹带的 `ref` 一律丢弃),`im_message` 加 `ref_msg_id` / `ref_snapshot` 两列;下行 `message` 与 `GET /im/api/messages` 共用同一个 `message_json` 透出 `ref`;两端引用条 + 气泡引用块 + 点击跳转 |

**与计划的偏差**:两单都是「一单一条栈」的**契约联动例外**(改 WS 帧必须 fixture + imserver + App + Web
同一次 PR),这一点计划 §工单映射 已预先声明,执行未破例。

**人工验收状态**:计划「验收(整批 L)」列的四条(两端同时在线看 typing、引用文本/图片/语音/贴纸、
引用已撤回消息、自己的另一端不显示自己触发的 typing)**在归档时未见留证记录**;自动化侧
(`scripts/verify.sh imserver/app/web` + 三端契约测试)已覆盖。下一轮发布前需在模拟器 + 浏览器补跑。
