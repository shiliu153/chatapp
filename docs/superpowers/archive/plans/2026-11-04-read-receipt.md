# 已读回执 实施计划

- **Spec**:[2026-11-04-read-receipt-design.md](../specs/2026-11-04-read-receipt-design.md)
- **对应待办**:backlog C-2
- **Goal**:双端会话页能看到「我方消息是否已被对方读过」—— 在线实时(**下行 `read` 帧**)+ 离线补拉(**`peer_read_seq`**)两条链路都通。
- **Architecture**:已读态的唯一事实来源 = `im_conversation_state.read_seq`(读者自己那一行)。服务端在 `read` 帧落库后把「我读到 N」广播给对端;对端离线时由 `GET /im/api/conversations` 的 `peer_read_seq` 补拉。客户端只做「按 `seq ≤ N` 标记我方消息」这一件事,不做状态推断。
- **Global Constraints**:
  - `im/tasks.py` 之外的 IM 副作用不动;`imclient` 对外永不抛异常。
  - 不改 `unread` 语义、不改 `GET /im/api/messages` 契约。
  - App UI 走「心跳」token,不出现裸值;Web 同步改 `tokens.css` 那一侧无需新增 token。
  - 每 Task 结束跑该 Task 的验证命令,全绿再进下一个。
- **验收命令**:
  - imserver:`docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test.sh` 与 `... /src/scripts/test_integration.sh`
  - App:`cd app && ../flutter/bin/flutter.bat analyze && ../flutter/bin/flutter.bat test`
  - Web:`cd web && npm run type-check && npm run lint && npm run test:run`
  - 后端:`cd chatapp && python manage.py test`(本次不动 Django,但接口文档门禁会跑,留作回归)

---

## Task 1 — imserver 存储层:`peer_read_seq`

- [ ] `store/models.h`:`ConversationView` 增加 `uint64_t peer_read_seq = 0;`
- [ ] `store/conversation_repo.cpp::list`:SQL 加
      `LEFT JOIN im_conversation_state ps ON ps.conv_id=s.conv_id AND ps.owner_id=<peer>`,
      select `IFNULL(ps.read_seq,0)`。`<peer>` = `IF(c.user_a=<owner>, c.user_b, c.user_a)`。
      **注意**:`s` 是「我」的行,`ps` 是对端的行;两者都以 `conv_id` 关联,`ps` 走 `im_conversation_state` 的 `(owner_id,conv_id)` 唯一键。
- [ ] `store/conversation_repo.h`:如需,新增 `read_seq_for(lease, owner, peer)`(单会话精确读,供 `mark_read` 与测试用)
- **验证**:`store_test.cpp` 补一例(`mark_read` 后从对端视角 `list` 能读到 `peer_read_seq`);`test.sh` 绿。
- **提交**:`feat(imserver): 会话列表暴露对端已读位置(peer_read_seq)`

## Task 2 — imserver 服务层:`mark_read` 返回生效 seq

- [ ] `service/message_service.h/.cpp`:`bool mark_read(...)` → `std::optional<uint64_t> mark_read(uint64_t uid, uint64_t peer, uint64_t seq)`,
      返回**实际写入的** `target`(`seq==0` 时用 `conversation.last_seq`;语义上取 `GREATEST`,但广播用 `target` 足够 —— 客户端侧只增不减)。
- [ ] 会话不存在 → `std::nullopt`(保持现有「返回 false → ack ok=false」的行为)。
- **验证**:`message_service_test.cpp` 补用例(seq=0 取 last_seq / 显式 seq 原样返回 / 无会话返回 nullopt)。
- **提交**:`feat(imserver): mark_read 返回生效的已读位置`

## Task 3 — imserver 协议层:下行 `read` 帧 + 限流

- [ ] `net/ws_server.cpp::handle_read`:落库成功后
      - 照旧 `send_raw(ack_frame(id, ok))`
      - **新增**:`registry_.send_to(peer, read_frame)` 推给对端,帧形如
        `{v:1,type:"read",data:{peer:peer_id(self->uid_),seq:target}}`(**自建帧,客户端不回 ack**)
      - 对端离线 → 只落库,靠 §3.3 补拉(不需要离线队列)
- [ ] `read` 帧限流:`RateLimiter`(与 send 同级实例或独立 `read_table_`,建议 **60 次/分钟**),超限回 `42901`;目的:防「每滚一屏发一次」打爆对端推送。
- [ ] `net/http_api.cpp` `/im/api/conversations` item 增加 `{"peer_read_seq", view.peer_read_seq}`
- **验证**:`test_integration.sh` 绿(含新增 `tests/integration/test_read.py`)。
- **提交**:`feat(imserver): read 帧广播给对端 + 会话列表带 peer_read_seq`

## Task 4 — imserver 集成测试

- [ ] `tests/integration/test_read.py`(照 `test_send.py` 的双客户端写法):
  1. A 发 3 条 → B 收 3 帧;
  2. B 发 `read{peer:A,seq:0}` → **A 收到下行 `read` 帧**且 `seq == 最后一条的 seq`、`peer == u<B>`;
  3. B 收到的 `read` ack 仍是 `ok=true`(旧行为不破);
  4. B 断开 → A 发第 4 条 → B 重连后 `GET /im/api/conversations` 的 `peer_read_seq` 为 B 之前的读点(**不是**第 4 条);
  5. B 再读 → A 收到新帧,`seq` 增。
- **验证**:`test_integration.sh` 绿。
- **提交**:`test(imserver): 已读回执双客户端集成测试`

## Task 5 — App(Flutter)

- [ ] `im/im_client.dart`:`ImEvent` 增加 `ImPeerRead(peerId, seq)`;`ImCapabilities` 增加 `readReceipt`
- [ ] `im/self_im_client.dart`:解析下行 `type:"read"` → 发 `ImPeerRead`;`capabilities.readReceipt = true`
- [ ] `im/tencent_im_client.dart`:`readReceipt = false`(腾讯分支不渲染假状态)
- [ ] `im/routing_im_client.dart`:能力透传
- [ ] `features/chat/chat_controller.dart`:维护 `peerReadSeq`(只增不减);打开会话时 `fetchConversations()` 取该 peer 的 `peer_read_seq` 初始化;收到 `ImPeerRead` 更新
- [ ] `features/chat/`(气泡组件):我方消息尾部按 spec §4 渲染「发送中 / 重发 / 已读」,灰条与撤回不渲染
- [ ] 测试:`test/` 补「收到 ImPeerRead → 已读出现在 seq ≤ N 的气泡上」「N 更小不回退」「pending/failed 优先于已读」「灰条不显示」
- **验证**:`flutter analyze` 零告警 + `flutter test` 绿
- **提交**:`feat(app): 聊天消息已读回执`

## Task 6 — Web(Vue 3)

- [ ] `im/types.ts`:`ImEvent` 加 `{type:'peerRead';peerId:string;seq:number}`;`ImCapabilities` 加 `readReceipt`;`ImConversation` 加 `peerReadSeq`
- [ ] `im/self/client.ts`:解析下行 `read` 帧;`fetchConversations` 解析 `peer_read_seq`
- [ ] `im/client.ts`(腾讯适配)/`im/routing.ts`:能力与事件透传
- [ ] `stores/chat.ts`:`peerReadSeq` 状态(只增不减)、打开会话时初始化、渲染用的派生
- [ ] 会话页气泡组件:按 spec §4 渲染「已读」
- [ ] 测试(vitest):与 App 对齐的四条;**假 transport 注入下行 read 帧**
- **验证**:`npm run type-check` + `npm run lint` + `npm run test:run` 全绿
- **提交**:`feat(web): 聊天消息已读回执`

## Task 7 — 文档与收尾

- [ ] `docs/ops/imserver.md`:协议章节补下行 `read` 帧、`/im/api/conversations` 的 `peer_read_seq`、`read` 帧限流值
- [ ] `docs/pitfalls/im.md`:一条(`peer_read_seq` 的视角是「对端」,别和 `unread` 混)
- [ ] `docs/api/im.md`:若提到会话列表字段则同步(WS 帧不归 `/api/v1` 门禁管,写清归属)
- [ ] backlog C-2 勾选 + 「完成于 / PR」一行;`docs/milestones.md` 一行
- [ ] 交付后 spec+plan `git mv` 到 `archive/` + `docs/superpowers/README.md` §4 补一行

---

## 执行记录 / 与计划的偏差

(实施过程中填写)

---

## 执行结果(2026-11-04,PR #47)

7 个 Task 全部落地。**与计划的偏差**:

1. Task 1 额外加了 `ConversationRepo::read_seq_for`,并在 `mark_read` 里**回读实库**再返回 —— 计划里写「广播用 `target` 足够」是不对的:`mark_read` 落库是 `GREATEST` 语义,直接用请求里的 seq 会让乱序到达的旧帧把对端推回未读。回读是一次同 lease 的等值查询,`read` 帧有 2/s 限流,成本可忽略。
2. 限流超限**静默丢弃**而不是回 `42901`:回错误帧会让客户端白重试,而 `read` 幂等,下次打开会话/收到新消息还会再发。
3. Web 侧状态词放在 `message-bubble__body` 内(与既有「发送中…/重发」同位置);App 侧放在气泡左侧 —— 版式不同,语义一致。

**踩到的坑**:

1. 给 `ImCapabilities` / `ImConversation` 加必填字段,会连带 6 处测试夹具 + 2 处生产映射(`map.ts` 腾讯分支、`upsertConversation` 新会话兜底)一起红 —— 这类契约字段改动先跑 `npm run type-check` / `flutter analyze` 最省事。
2. `store.close()` 是 async,测试里漏 `await` 会读到没清干净的状态。
3. `test_ws.sh`(WS 集成)**不在 CI 里**(CI 只跑 `test.sh` / `test_integration.sh` / `test_http.sh`),所以新用例同时在 `test_history.py` 里补了两条断言,让 CI 也能覆盖实时下行帧与 `peer_read_seq`。
4. `ninja: no work to do` 不代表没编译 —— 容器里的 `/src/build` 是 bind mount 复用的,源码改过就会重编;判断「新代码真的跑了」靠测试里的正向断言(本次用 ack 计数与 `test_read ok: …` 打印确认)。

**验收对照**:双端互发 → 对方打开会话 → 我方气泡出现「已读」(App `chat.status.read` / Web `data-testid="chat-read"`);断线重连可补拉(会话列表 `peer_read_seq`);imserver 新增 `tests/integration/test_read.py` + `test_history.py` 两条断言。
