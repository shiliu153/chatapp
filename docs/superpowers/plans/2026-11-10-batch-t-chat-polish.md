# 批次 T 实施计划:聊天体验打磨

- **状态**:待实施
- **Spec 链接**:[批次 R–W 设计](../../specs/2026-11-09-batch-r-w-design.md) §4.3
- **交接来源**:[批次 U/W 交接](2026-11-10-batch-u-w-handoff.md) §2「T 批」
- **Goal**:多选删除(仅删我这一侧)/ 草稿 / 图片全屏 / 语音进度与倍速 —— 四件事让聊天「像微信」。
- **Architecture**:imserver 新增 `im_message_hidden`(迁移 `008`)+ 一个 **HTTP** 写接口
  `POST /im/api/messages/delete`,**零 WS 帧改动**(照 N 批 `/im/api/conversations/flags` 的先例);
  三处读口径(历史 / 未读数 / `last_message`)必须同改。App/Web 只加客户端行为,不动协议。
- **Global Constraints**:一单一条栈;App UI 走「心跳」token;App 单 PR 必须 draft + 模拟器手测;
  不动版本号、不发版、不合并 PR;不改 `imserver/tests/fixtures/ws/*.json`(本批零帧改动)。
- **验收命令**:`scripts/verify.sh imserver` / `scripts/verify.sh app` / `scripts/verify.sh web`

---

## 0. 现状核实(动手前查过:**四件事里有两件两端已经做完了**)

| 设计里要的 | 实际 | 本期还剩什么 |
|---|---|---|
| 发送失败气泡「未发送」+ **手动重发** | **两端都已交付**:App 失败时左侧红色重发图标(`chat_page.dart` → `onRetry` → `controller.retry()`),注释明确写「**失败不写字** —— 左侧已有红色重发图标,再写字是重复」;Web `MessageBubble.vue` 有重试按钮 + 「发送中…」 | **不做**。为了加「未发送」三个字去改掉两端既有的状态口径,是负收益 —— 记进「不做」 |
| 图片点击全屏(双指缩放 + 左右切) | App:`PhotoViewerPage` **已有** `InteractiveViewer`(双指缩放)+ `PageView`(左右切),**但聊天只传了单张 URL**(`openPhotoViewer(context, urls: [url])`);Web:`ImageViewer.vue` 收 `urls[] + index` 却**只渲染一张**,无缩放、无切换 | App:传会话内**全部**图片 + `initialIndex`;Web:补缩放 + 左右切 + 页码 |
| 语音进度条可拖 + 倍速 | 两端都**没有**:App `VoicePlayer` 只有 `play/stop/onComplete`(注释还写着「只关心播没播完的实现不必实现 onPosition」),`VoiceBubble` = 图标 + 秒数;Web `voicePlayer.ts` 注释明写「**不做播放进度**」 | 两端都要新做(seek + 1.0x/1.5x/2.0x) |
| 多选删除 / 草稿 | 两端都没有。但 App 已留好接口位:`ImClient.deleteMessage(ChatMessage)`(语义「删除本地消息,对方不受影响」)在 `self_im_client.dart` 里是**空实现** | 全做(本批主体) |

其余已核实、直接复用:

| 已有 | 位置 | 复用方式 |
|---|---|---|
| HTTP 写接口的完整先例(鉴权 / 限流 / 405 / 42201 / 40401 / 回读实库) | `imserver/src/net/http_api.cpp` 的 `/im/api/conversations/flags`(批次 N) | 新接口照抄骨架 |
| HTTP 路由是**硬白名单** | `http_api.cpp` 里 `if (target.path != ... ) return 40401` | 新路径必须加进这一行,否则 404 |
| 迁移机制 | `imserver/src/migrate.cpp` 的 `kMigrations[]` + `apply_sql` 按 `;` 切语句 | 加 `{8, "008_message_hidden.sql"}`;**SQL 注释里不能有分号** |
| 集成测试清单 | `imserver/scripts/test_http.sh` **逐个列文件** | 新测试文件必须追加进这一行,否则 CI 不跑它 |
| 消息行查询 | `MessageRepo::list_messages` / `search`(都用 `kSelect`) | 两处都要排除「我隐藏的」 |
| 会话列表 SQL | `conversation_repo.cpp::list_conversations`(join `im_message m ON m.msg_id=c.last_msg_id`) | `last_message` 改成「我的最后一条可见」 |
| 未读是**计数器**不是聚合 | `im_conversation_state.unread`,`upsert_state` 加、`mark_read` 清零 | 删除时**减计数**,不能靠聚合排除 |
| App 输入框与会话列表 | `chat_page.dart` 的输入栏、`chats_page.dart` + `ConversationRow` | 草稿读写与「[草稿]」前缀 |
| App/Web 语音播放单例 | `app/lib/features/chat/voice_playback.dart`、`web/src/im/voicePlayer.ts` | 加 seek / rate / 进度流,保持「同一时刻只播一条」 |
| App 二级交互范式(长按菜单) | `chat_page.dart::_showMessageMenu`(已有「引用」「撤回」两项) | 加「多选」入口 |
| App integration_test 写法 | `app/integration_test/discovery_filter_test.dart`(真实指针事件) | 多选删除照它写一条 |

---

## Task 1 —— T-1 imserver(先合;唯一动库的一批)

### 1. 迁移 `008_message_hidden.sql`

```sql
-- 多选删除(批次 T):只记「谁不想再看到哪条」,不碰消息本体、不通知对端。
-- 主键 (user_id,msg_id) 正好服务「我的历史里排除我隐藏的」这个唯一读法;
-- 反向索引给「注销账号时按 msg_id 清理」用。
CREATE TABLE IF NOT EXISTS im_message_hidden (
  user_id BIGINT UNSIGNED NOT NULL,
  msg_id BIGINT UNSIGNED NOT NULL,
  created_at BIGINT NOT NULL,
  PRIMARY KEY (user_id, msg_id),
  KEY idx_hidden_msg (msg_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
```

- `migrate.cpp` 的 `kMigrations[]` 追加 `{8, "008_message_hidden.sql"}`;
- **注释里不能出现分号**(`apply_sql` 按 `;` 切);
- 不加外键(与既有表一致,靠应用层清理)。

### 2. `POST /im/api/messages/delete`(唯一新接口)

请求:`{"ids": ["123", "124", ...]}`(元素接受字符串或整数,统一解析成 uint64)。
响应:`200 {"deleted": <本次**新**隐藏的条数>}`。

- 路由:加进 `http_api.cpp` 那行硬白名单(与 `conversations` / `flags` / `messages` / `search` 并列);
- 方法:只 `POST`,其它 → `405 + 40501`;
- 鉴权:`authenticate(req)` 同既有(失败 401 + 40101);
- 限流:新 `RateTable delete_table_{1.0, 10.0}`(1/s、突发 10),超限 `429 + 42901`;
- body 解析失败 / 非对象 / `ids` 不是数组 → `400 + 42201`;
- `ids` 为空、或超过 **50** 条 → `400 + 42201`(上限 50 条/次,文案写清);
- 元素解析失败(非数字、0、负数)→ `400 + 42201`;
- **只对自己可见的消息生效**:只处理 `from_id=uid OR to_id=uid` 的 id;不属于我的 id **静默忽略**
  (不回 403/404 —— 报错会变成「探测别人消息是否存在」的信道);
- **幂等**:`INSERT IGNORE`,重复删同一批返回 `{"deleted": 0}`;
- **不通知对端、不产生任何帧、不改消息本体、不动 `im_conversation.last_seq`**。

### 3. 服务层:`MessageService::hide_messages(uid, ids)`

返回本次新隐藏条数。一个事务内做三件事:

1. **取可见行**:`SELECT msg_id, conv_id, seq, from_id, to_id FROM im_message WHERE msg_id IN (...) AND (from_id=uid OR to_id=uid)`;
2. **落隐藏**:逐条 `INSERT IGNORE INTO im_message_hidden (user_id,msg_id,created_at) VALUES (...)`,
   用 `mysql_affected_rows` 判断「是不是新的」(1 = 新隐藏、0 = 早就删过);
3. **减未读**:对**新隐藏**且 `to_id=uid` 的每条,判断它是否还没读(`seq > 该会话我的 read_seq`),
   按会话汇总后一条 SQL 减:
   ```sql
   UPDATE im_conversation_state SET unread=GREATEST(unread-?,0), updated_at=?
   WHERE owner_id=? AND conv_id=?
   ```
   —— 未读是**计数器**(`upsert_state` 累加、`mark_read` 清零),不靠聚合,所以必须显式减,
   而且必须 `GREATEST(...,0)`,否则乱序会减成负数。

### 4. 三处读口径同改(漏一处就是「删了还占未读 / 删了还在列表顶部」)

1. **历史**`MessageRepo::list_messages`:
   现有 `SELECT ... FROM im_message WHERE conv_id=X AND seq<Y ORDER BY seq DESC LIMIT N`;
   改成 `FROM im_message m LEFT JOIN im_message_hidden h ON h.msg_id=m.msg_id AND h.user_id=<uid>`
   + `WHERE m.conv_id=X AND ... AND h.msg_id IS NULL`。
   **必须仍走 `uk_conv_seq(conv_id,seq)`**:用 `EXPLAIN` 断言 `type=range` 且 `key=uk_conv_seq`
   (隐藏行很少,`LEFT JOIN` 是主键点查,不会退化成全表扫)。
2. **搜索**`MessageRepo::search`:同样加 `LEFT JOIN im_message_hidden ... AND h.msg_id IS NULL`
   —— 否则「删了还能被搜到」,与历史口径不一致。
3. **会话列表**`conversation_repo.cpp::list_conversations` 的 `last_message`:
   `LEFT JOIN im_message m ON m.msg_id=c.last_msg_id` 换成「**我的**最后一条可见消息」:
   ```sql
   LEFT JOIN im_message m ON m.msg_id = (
     SELECT m2.msg_id FROM im_message m2
     WHERE m2.conv_id=c.id
       AND NOT EXISTS (SELECT 1 FROM im_message_hidden h2
                       WHERE h2.user_id=<owner> AND h2.msg_id=m2.msg_id)
     ORDER BY m2.seq DESC LIMIT 1)
   ```
   走 `uk_conv_seq` 反向扫,每会话最多一行。
   `last_seq` / `has_last` / `updated_at` 的语义**不变**(仍是会话全局);只有 `last_message` 变。
   **实测若慢**:退路是「只有 `c.last_msg_id` 被我隐藏时才走子查询」,但那要两条 SQL ——
   先按上面写,并把 `EXPLAIN` 结果贴进 PR。

### 5. 注销账号清理

`MessageService::delete_account(uid)` 里,在删 `im_message` **之前**清隐藏表:
`DELETE FROM im_message_hidden WHERE user_id=uid OR msg_id IN (SELECT msg_id FROM im_message WHERE from_id=uid OR to_id=uid)`
—— 先算 `msg_id` 列表再删,避免边删边查。

### 6. 测试(必须真的断言)

`tests/integration/test_delete.py`(新文件,**追加进 `scripts/test_http.sh` 的清单**):

1. **删后历史不含**:A→B 发 3 条,B 删中间 1 条,B 的历史 2 条、**A 的历史仍是 3 条**(单方);
2. **未读数减少**:B 未读 3 → 删 1 条未读 → 未读 2;删**已读**那条 → 未读**不变**;
3. **`last_message` 落到上一条可见**:B 删掉最后一条 → B 的会话列表 `last_message` 是前一条,
   A 的仍是原来那条;
4. **搜索不再命中**:删掉的文本再搜,`hits` 里没有它(对端仍能搜到);
5. **超限**:51 条 → `400 + 42201`;空数组 → `400 + 42201`;
6. **幂等**:同一批删两次,第一次 `deleted=N`,第二次 `deleted=0`,历史条数不变;
7. **非参与者的 id 被忽略**:拿一条别人的 msg_id 混在批量里 → 不报错、不计入 `deleted`、那条消息对谁都还在;
8. **鉴权与限流**:无 token → 401;`GET` → 405;
9. **不改协议**:`git diff` 里**不应出现** `tests/fixtures/ws/` 的任何改动。

`tests/unit`(或 `message_service_test.cpp`)补一条:减未读用 `GREATEST(...,0)`,删已读消息不减计数。

### 验收口径

1. `scripts/verify.sh imserver` 全绿(unit + db + 集成三段,末尾输出贴进 PR 正文)。
2. 上面 9 组断言全过,且**改回错误实现会红**(未读不减、`last_message` 不改、搜索不排除、幂等、超限五条尤其)。
3. `EXPLAIN` 结果贴进 PR:历史查询走 `uk_conv_seq`;会话列表的子查询也走 `uk_conv_seq`。
4. `docs/ops/imserver.md` 新增一节(§20 或续 §19):接口契约、三处口径、以及
   「**这是单方删除** —— 对端仍可见、不通知、不可恢复」这条产品口径。

### 禁止事项

**不改任何 WS 帧 / 不改 `tests/fixtures/ws/*.json`**;不改消息本体与 `im_conversation.last_seq`;
不加外键;不动既有接口的响应形状;不改 `im_conversation_state` 的既有列语义;不动版本号、不部署。

### 不在本期范围

自动重发 / 断线队列(要 `client_msg_id` 幂等键 → 改 `send` 帧 → 三端 fixture 联动,单独一单);
双向删除(对端也消失);消息编辑;隐藏行的定时清理(按天删太老的隐藏行,收益不抵成本)。

---

## Task 2 —— T-2 App(依赖 T-1 已合并)

### 改什么

1. **IM 客户端**:`ImClient` 加 `Future<void> deleteMessages(List<String> msgIds)`(批量);
   `deleteMessage(ChatMessage)` 保留并委托给它(单条兼容);
   `self_im_client.dart` 实现走 HTTP:`_http!.post('/messages/delete', {'ids': ids})`;
   `test/support/fake_im_client.dart` 记 `log.add('delete:${ids.join(",")}')` 并可注入失败。
2. **多选删除**(`chat_page.dart`):
   - 长按菜单(`_showMessageMenu`)加一项 **「多选」**(`Key('chat.menu.multi')`),点了进多选模式;
   - 多选模式:顶栏换成「已选 N 条」+「取消」;每条消息左侧出勾选圈,点消息本体切换选中
     (此时引用/长按菜单不生效);**已撤回/发送中的消息不可选**;
   - 底部操作条:`删除`(danger 色)、`复制文本`(仅当选中里 ≥1 条文本消息时可用);
   - 删除前弹确认:「删除这 N 条?只在你这边删除,对方仍可见」→ 确认后调 `deleteMessages`,
     成功后从列表移除并退出多选;**失败保留选中 + `AppToast`**;
   - 复制:`Clipboard.setData`,多条按时间顺序用 `\n` 连接,成功后 toast「已复制」。
3. **草稿**(`shared_preferences`,仓库已有依赖):
   - `DraftStore`(provider + 内存 map,启动/进会话时异步预加载):key `chat_draft:{peerId}`;
   - 输入框 `onChanged` 防抖 300ms 存;进入会话时回填;**发送成功或输入框清空**后删 key;
   - 会话列表:有草稿时在摘要前加 **「[草稿] 」** 前缀(`chats_page.dart` 的 row)。
4. **图片全屏**:`chat_page.dart` 的 `_openImage` 改成收集**会话内全部图片消息**的 URL,
   传 `openPhotoViewer(context, urls: all, initialIndex: 当前条的下标)`。
   `PhotoViewerPage` 本身**不用改**(缩放 + 左右切已有),只补一条 `Key` 或页码可选。
5. **语音进度 + 倍速**:
   - `voice_playback.dart`:`VoicePlayer` 加 `Future<void> seek(Duration position)` 与
     `Future<void> setRate(double rate)`(接口 + `DeviceVoicePlayer` 用 `audioplayers` 的
     `seek` / `setPlaybackRate`);`onPosition` 已有流,直接用;
   - `voice_bubble.dart` 改成「播放/暂停图标 + **可拖进度条**(`Slider`,拖动时暂停跟手、
     松手 seek)+ 剩余/总时长 + **倍速按钮**(点一下循环 1.0x → 1.5x → 2.0x → 1.0x)」;
     换条播放时倍速**复位 1.0x**;`Key`: `chat.voice.slider` / `chat.voice.rate`。
6. **integration_test**:新增 `app/integration_test/chat_multi_select_test.dart`
   (照 `discovery_filter_test.dart` 走**真实指针事件**,不碰网络):
   ① 长按 → 菜单里点「多选」→ 顶栏变「已选 0 条」;② 点两条消息 → 「已选 2 条」;
   ③ 点底部「删除」→ 确认框 → 确认 → 列表少 2 条。**并把路径追加进 `.github/workflows/app-ui.yml` 的 `script:` 行**(只加路径)。

### 验收口径

1. `scripts/verify.sh app` 全绿(`flutter analyze` 零告警 + 全部测试)。
2. 新增组件测试:多选选中/取消、删除成功后移除、删除失败保留选中并 toast、草稿存取与恢复、
   图片全屏收到**全部** URL 且 `initialIndex` 正确、`VoiceBubble` 拖动触发 seek 且倍速循环顺序正确。
3. `no_raw_colors_test.dart` 与 `dark_mode_sweep_test.dart` 仍绿(新 UI 一律走 `colors.*` / `AppSpacing` / `AppRadius`)。
4. **PR 必须开 draft**,正文写「等待模拟器验收」;**不得声称 ready**。
5. 模拟器逐页手测由人做(见 §4.1:坐标一律用 Pillow 从原始 PNG 量,不要目测)。

### 禁止事项

不改 WS 帧 / 不改 `app/test/im/protocol_fixture_test.dart`;不引新依赖(`audioplayers` / `shared_preferences` 已有);
不碰 `flutter/`;不改既有「失败不写字」的状态口径;不写裸 hex / 裸字号 / 裸间距;不动版本号。

### 不在本期范围

语音转文字、图片保存到相册、多选转发、草稿跨设备同步。

---

## Task 3 —— T-3 Web(依赖 T-1 已合并)

### 改什么

1. `web/src/im/self/client.ts` 加 `deleteMessages(ids: string[])` → `POST /messages/delete`;
   `web/src/im/types.ts` 与 `client.ts` 的接口同步(若有抽象层)。
2. **多选删除**:`ChatPage.vue` 加多选模式(同 App 口径:长按/右键菜单加「多选」→ 勾选 →
   底部操作条 → 确认框「只在你这边删除,对方仍可见」);`MessageMenu.vue` 加「多选」项;
   删除成功后从 store 移除,失败 toast 且保留选中。
3. **草稿**(`localStorage`,key `chat_draft:{peerId}`):`ChatPage.vue` 输入框防抖 300ms 存、
   进入会话回填、发送成功或清空后删;`ConversationRow.vue` 摘要前加「[草稿] 」。
4. **图片全屏**:`ImageViewer.vue` 补三件事 —— ① 缩放(滚轮 + 双击,`transform: scale`);
   ② 左右切(`←` / `→` 键 + 左右按钮,`index` 上移下移);③ 页码 `i/n`。
   `MessageImage.vue` / `MessageBubble.vue` 打开时传**会话内全部图片**与当前下标。
5. **语音进度 + 倍速**:`web/src/im/voicePlayer.ts` 补进度回调(`timeupdate`)、`seek(ratio)`、
   `setRate(rate)`(仍是单例、同一时刻只播一条);`MessageVoice.vue` 加可拖进度条
   (`<input type="range">` 或自绘)+ 倍速按钮(1.0x/1.5x/2.0x 循环),换条播放复位 1.0x。

### 验收口径

1. `scripts/verify.sh web` 全绿(`vue-tsc` 零错误 + `eslint --max-warnings 0` + vitest 覆盖率门槛 70/60/70/70 + `npm run build`)。
2. 组件/store 测试:多选删除调用接口并移除、失败保留、草稿存取与 `[草稿]` 前缀、
   `ImageViewer` 的缩放与左右切与页码、`MessageVoice` 拖动 seek 与倍速循环。
3. `no-raw-color.spec.ts` / `tokens.spec.ts` 仍绿(新样式一律用 `var(--…)` token)。

### 禁止事项

不引 UI 库/新依赖;不手改 `web/src/api/schema.d.ts`(本批无契约变化,它不该出现在 diff 里);
不碰 `web/src/im/self/map.ts` 的帧映射(零帧改动);不改既有「发送中…」状态口径;不动版本号。

### 不在本期范围

多选转发、语音转文字、图片缩放后的拖拽惯性、草稿跨设备同步。

---

## 执行记录

(合并后补:每单 PR / 合并 SHA / 关键交付 / 与计划的偏差 / 踩到的坑 / 模拟器验收结论 / 遗留)
