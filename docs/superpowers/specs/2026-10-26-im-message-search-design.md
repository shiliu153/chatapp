# 聊天记录搜索 设计（自建 IM，2026-10-26）

> 状态：已获用户批准（2026-10-26）。实施计划见 `docs/superpowers/plans/2026-10-26-im-message-search.md`。

## 1. 背景与目标

自建 IM（`imserver/`）已具备文本/图片消息、离线补拉、已读、撤回、拉黑、签名 URL 与 30 天清理，功能门槛全部满足。
但**没有任何检索能力**：用户想找回「上周说过的地址」只能手动往上翻。腾讯后端有云端搜索（旗舰版），自建后端没有对应能力。

**目标**：自建后端下，用户能按关键词搜索自己全部单聊的**文本消息**；点击结果进入聊天页并**定位到那条消息**（回溯历史 + 滚动 + 高亮）。App 与 Web 双端同构交付。

## 2. 非目标（本期不做）

- 腾讯后端搜索：腾讯云搜索是旗舰版能力，`capabilities.search=false`，入口隐藏（与图片能力位同一套做法）。
- 图片消息、系统通知、自定义灰条的检索。
- 会话内搜索（`peer` 限定）、搜索历史记录、热门词。
- 全文索引（FULLTEXT/ES）：先用 `LIKE`，见 §9 的容量判断。
- 搜索结果分页无限滚动：只做「加载更多」按钮。

## 3. 已定决策（用户确认）

| 决策点 | 结论 | 理由 |
|---|---|---|
| 结果形态 | **消息级**：一条命中一条结果，带对端资料与关键词上下文 | 能直接看到命中的那句话 |
| 点击行为 | **定位到那条消息**：进聊天页 → 回溯历史 → 滚到该条 → 高亮 1.5s | 只进聊天页看不到旧消息，等于白搜 |
| 端范围 | **App + Web 双端** | 与既有功能批次一致 |
| 检索实现 | MySQL `LIKE '%kw%'` + 只扫「我参与的会话」 | 2C2G 规模下够用；ngram 全文索引对单字查询不友好（`ngram_token_size` 默认 2） |
| 服务端归属 | imserver 新增 `GET /im/api/search` | 消息库在 imserver；Django 不参与，nginx 已有 `/im/api/` 反代，无需改配置 |

## 4. 服务端设计

### 4.1 接口

```
GET /im/api/search?q=<关键词>&limit=20&before_id=<游标>
Authorization: Bearer <IM token>   # 与 /im/api/messages 同一个 token
```

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| q | String | 是 | URL 编码的关键词；去首尾空白后 1–150 字节（约 50 汉字），空或超长 → 42201 |
| limit | Integer | 否 | 默认 20，上限 50 |
| before_id | Integer | 否 | 游标：只取 `msg_id < before_id`；缺省 = 第一页 |

响应：

```json
{
  "items": [
    {
      "msg_id": "1024",
      "seq": 12,
      "from": "u7",
      "to": "u9",
      "ts": 1761465600000,
      "revoked": false,
      "kind": "text",
      "text": "晚上去吃火锅吗",
      "from_profile": { "nickname": "小七", "avatar": "https://…" },
      "peer": { "id": "u9", "nickname": "阿九", "avatar": "https://…" }
    }
  ],
  "has_more": true
}
```

- `peer` 是**对端**（相对当前请求者）：我是发送方时 `peer = to`，否则 `peer = from`。客户端用它渲染头像/昵称，不再二次查资料。
- 排序：`msg_id DESC`（新 → 旧）。`msg_id` 自增，与时间同序。
- `has_more`：多取一条判断（`limit+1`），不靠 `rows.size()==limit` 猜。

### 4.2 查询口径

只返回同时满足下列条件的消息：

1. `kind = 1`（文本；图片/自定义灰条不参与）；
2. `revoked_at IS NULL`（已撤回不参与）；
3. 我参与的会话（`im_conversation.user_a = uid OR user_b = uid`）；
4. 会话没被我删除（`im_conversation_state.deleted = 0`，无 state 行视为未删除）；
5. 对端不是系统通知（`uid = 0`）；
6. **我没有拉黑对端**（`im_blacklist` 中不存在 `owner=uid, peer=对端`）——解除配对会双向拉黑，所以解除后的历史也不会被搜出来；
7. `body LIKE '%<转义后的关键词>%' ESCAPE '!'`。

关键词转义：`!`、`%`、`_` 前加 `!`（`ESCAPE '!'`），防止用户输入 `%` 变成通配符。用 prepared statement 绑定，不做字符串拼接。

### 4.3 限流

每 uid 60 次/分钟、burst 20（`TokenBucket(1.0, 20)`），超限 `42901` + HTTP 429。
进程内 `unordered_map<uint64_t, Bucket>`，**加互斥锁**（`IM_IO_THREADS` 默认 2，HTTP 处理跑在两个线程上）；map 超过 4096 条时清理 10 分钟未活跃的条目。

### 4.4 索引与迁移

`im_conversation` 现在只有 `uk_pair(user_a,user_b)`：`OR user_b = ?` 那半边走不了索引。新增迁移 **v2**：

```sql
ALTER TABLE im_conversation ADD KEY idx_user_b (user_b);
```

`migrate.cpp` 目前**写死只跑 v1**（`version_applied(1)` 后直接 return），本次改为按版本表循环，后续加迁移只加文件与表项。

> 迁移是显式步骤：服务器升级时必须先 `docker compose run --rm imserver --migrate` 再 `up -d`。

### 4.5 已知限制

`LIKE '%kw%'` 无法走索引，会扫描「我参与的会话」里的全部文本消息。当前规模（2C2G、单表万级）单次约几十毫秒；数据量到十万级后应换 MySQL FULLTEXT（ngram）或 ES，届时本接口的请求/响应形状不变，只换实现。

## 5. 客户端设计

### 5.1 能力位与接口

- `ImCapabilities` 增加 `search`：自建 `true`，腾讯 `false`。
- `ImClient.searchMessages(keyword, {limit, beforeId})` 返回 `ImSearchResult{items, hasMore}`；腾讯实现抛 `ImException(42202, '当前聊天服务暂不支持搜索')`（与图片同款兜底）。
- `fetchHistory` 增加可选 `beforeSeq`：自建映射到 `/messages?before_seq=`，腾讯忽略（腾讯后端没有搜索入口，走不到回溯分支）。
- 消息模型增加 `seq`（自建从响应解析；腾讯给 0），回溯翻页需要它。

### 5.2 入口与搜索页

- 消息页标题右侧搜索图标，**仅 `capabilities.search` 时显示**；点击进 `/search`。
- 搜索页：输入框自动聚焦、300ms 防抖、关键词高亮（片段里命中部分用主色加粗）、结果行（头像 / 昵称 / 片段 / 时间）、加载骨架、空态、错误重试、底部「加载更多」。
- 空关键词不发请求；输入变化后取消上一次的计时器，避免竞态覆盖（用请求序号丢弃过期响应）。

### 5.3 定位到消息

点结果 → `/chat/{peer}?focus={msgId}`（Web 用 query，App 用 go_router queryParameters，两边一致）。

聊天页拿到 `focusMsgId` 后：

1. 照旧加载最近 50 条；
2. 目标不在列表 → `loadOlder(untilMsgId)`：以当前最早一条的 `seq` 作 `before_seq`，每次 50 条往前翻，**最多 5 页**，直到找到目标或翻到顶；
3. 滚动定位：反序列表里逐屏 `jumpTo(pixels + 视口 × 0.8)`，目标气泡一旦构建出来就 `Scrollable.ensureVisible(alignment: 0.5)`（最多 24 次，不依赖估算行高）；
4. 命中气泡高亮 1.5s（主色 8% 底 + 淡出）。

定位失败（目标已撤回/被删除）不报错，静默停在最新一条。

## 6. 错误码

| 码 | HTTP | 场景 | 客户端处理 |
|---|---|---|---|
| 40101 | 401 | token 失效 / 被封禁 | 与既有 IM HTTP 一致：提示重登 |
| 42201 | 422 | `q` 为空或超长 | 输入框侧就不发请求，兜底提示 |
| 42901 | 429 | 搜索过于频繁（60 次/分钟） | 提示「稍后再试」 |
| 50001 | 500 | 内部错误 | 错误态 + 重试 |

## 7. 测试策略

- **imserver 集成测试**（`tests/integration/test_search.py`，进 `test_http.sh`）：中文命中、新旧排序、分页游标、`has_more`、撤回后不可见、拉黑后不可见、删除会话后不可见、未认证 401、空关键词 42201、超频 42901。
- **imserver 单测**：`like_pattern()` 的转义（`%`/`_`/`!`）与前后 `%` 包装。
- **App**：搜索页（防抖、命中渲染、空态、加载更多、错误）、聊天页定位（假 client 返回跨页历史 → 目标高亮 key 出现）。
- **Web**：搜索页组件测试、聊天页 `?focus=` 定位测试（注入假 client）。
- **回归**：后端全量、App `analyze` 零告警 + 全量测试、Web `type-check`/`lint`/`vitest --coverage`、imserver unit/db/http。

## 8. 交付物

- imserver：`/im/api/search`、`util/like.h`、`MessageRepo::search`、迁移 v2、限流、集成/单测。
- App：能力位、`searchMessages`、`SearchPage`、聊天页定位与高亮、假 client 扩展。
- Web：`ImSearchHit`/`searchMessages`、`SearchPage.vue`、聊天页定位与高亮。
- 文档：`docs/api/im.md` 6.4、自建 IM 设计 §6 接口表、`docs/ops/imserver.md`（限流/迁移/已知限制）。

## 9. 风险

| 风险 | 影响 | 对策 |
|---|---|---|
| LIKE 全表扫描随数据量变慢 | 搜索卡顿 | 只扫我参与的会话；限流；§4.5 的升级路径 |
| 迁移忘执行 | 搜索走全表扫描（慢但正确） | 部署核对单写明 `--migrate` 是升级前置步骤 |
| 定位循环在超长会话里空转 | 进聊天页卡顿 | 24 次上限 + 5 页上限，超限静默停下 |
| 腾讯后端用户看不到入口 | 能力不一致 | 能力位控制，与图片同一套语义，属预期 |
