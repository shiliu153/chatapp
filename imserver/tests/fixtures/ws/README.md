# 跨栈 IM 协议 fixture(backlog E-2)

这里放 **IM WebSocket 协议帧的共享样例**,是三端(App / Web / imserver)唯一的
「线上帧长什么样」的事实来源。

| 文件 | 方向 |
|---|---|
| `client_to_server.json` | 客户端 → 服务端(上行:auth / ping / send / read / revoke / conversation_delete) |
| `server_to_client.json` | 服务端 → 客户端(下行:auth_ok / pong / kicked / error / ack / message / read / revoked) |

## 谁在读它

| 端 | 测试 | 校验方式 |
|---|---|---|
| imserver | `imserver/tests/frames_fixture_test.cpp`(CI:`imserver.yml` → `test.sh`) | 下行帧用**真实序列化函数**生成,与 fixture 逐字段比对;上行帧做结构校验 |
| App | `app/test/im/protocol_fixture_test.dart`(CI:`app.yml`) | 用 `SelfImClient` 的真实解析路径吃 fixture,断言产出的事件/消息模型;并断言客户端实际发出的帧与上行 fixture 一致 |
| Web | `web/tests/unit/im-protocol-fixture.spec.ts`(CI:`web.yml`) | 同上(`SelfImClient` + `messageFromJson`) |

> 三端 CI 的 `paths` 都包含 `imserver/tests/fixtures/**`:只改 fixture 也会把三条轨都拉起来。

## 改协议的正确姿势(必须同一次改动)

1. 先改 fixture(它代表新契约);
2. 改 imserver 的序列化/解析;
3. 改 App 与 Web 的收发解析;
4. 三端测试全绿才能合并。

**只改一端 = 另外两端红**,这是有意的:以前「服务端改了帧格式」只有人工手测能发现
(审查 D-3)。

## 比对规则

- **动态字段**:`auth` 的 `token` 在 fixture 里是占位符 `<IM_TOKEN>`,测试只校验类型;
  下行帧里的 `server_time` / `ts` 用固定值,服务端测试直接传这些常量,不做模糊匹配。
- **媒体签名**:`image.url` / `image.thumb_url` / `voice.url` 在 fixture 里是**不带 query**
  的规范地址;线上帧会追加 `?e=&s=` 限时签名,服务端测试比对前统一剥掉 query
  (签名算法本身由 `imserver/tests/media_sign_test.cpp` 覆盖)。
- **枚举**:`kind` 只能是 `text` / `image` / `voice`;`custom`(灰条)不走 `send` 帧,
  由服务端内部产生,不在本 fixture 范围。
- **新增帧**:fixture 里加一条 `{"name","frame"}` 后,服务端测试会因为
  「fixture 新增了帧但服务端没有对应构造」而红 —— 先把序列化函数加进
  `imserver/src/net/frames.h`,再补 App/Web 的解析与断言。
