# 关系出口:解除配对 + 撤回消息(设计)

日期:2026-10-20 · 状态:已交付(2026-10-20;已读回执挂起待旗舰版)
上游:P1「留存闭环」第三小批(拆分见 `2026-10-20-likes-received-design.md` §1)。
下游:实施计划 `docs/superpowers/plans/2026-10-20-relationship-exits.md`。

## 1. 背景与定位

P1-1「喜欢我的人」、P1-2「设置页补齐」已交付并合入 master。P1-3 原定三件事:

| 能力 | 本批 | 原因 |
|---|---|---|
| 解除配对 | ✅ 做 | 纯业务能力,App/Web 双端可控 |
| 撤回消息 | ✅ 做 | 腾讯 IM SDK 原生能力,体验版可用 |
| 已读回执 | ⏸ 挂起 | **腾讯 IM 旗舰版专享**;当前是体验版(100 用户上限),升级前做不了 |

**问题:** 目前一旦配对就**没有任何出口**。用户遇到不合适的人,只能去「举报/拉黑」——拉黑是给骚扰用的重手段,还会进黑名单列表、可被解除;而「只是不想聊了」没有对应动作。另一方面,发错消息(发错人、打错字、发错图)完全无法收回,只能干看着。

**目标:** 给配对关系一个体面的出口(解除配对),给已发消息一个短窗口的后悔药(2 分钟内撤回),App 与 Web 双端能力对齐。

**非目标(本批不做):**

- 已读回执(旗舰版;挂起原因见 §8);
- 解除配对的恢复 / 撤销(产品语义就是不可恢复);
- 解除原因收集、解除率统计、运营后台可见的解除记录页(数据留了,但本批不做界面);
- 消息编辑、删除对方消息、聊天记录导出;
- 消息页对「已解除」会话的隐藏过滤(见 §4.3 的取舍)。

## 2. 已定关键决策(用户确认)

| 决策点 | 结论 | 落选理由 |
|---|---|---|
| 本批范围 | **解除配对 + 撤回消息**,已读回执挂起 | 旗舰版才能做,体验版做了也不生效 |
| 解除后的消息 | **彻底断开**:删配对 + IM 双向黑名单,不可恢复 | 只清本机会话会让对方再发消息时会话复活,漏洞明显 |
| 落库方式 | **软删除**:`Match` 加 `unmatched_at` / `unmatched_by` | 物理删除 + 新表要额外防 `swipe` 复活;改 Swipe 为 pass 会丢「我喜欢过」历史 |
| 入口 | **聊天页右上「⋯」+ 他人资料页菜单**(已配对时才出现) | 只在消息列表长按发现成本高;只在资料页要多一步 |
| 对方感知 | **完全静默**:无灰条、无推送 | 灰条本身会新建会话,反而引人注意 |
| 撤回时限 | **2 分钟内才显示「撤回」** | 总是显示会诱导用户白点一次再报错 |
| 交付范围 | **App + Web 双端** | 项目惯例:同一套接口、两端能力对齐 |

## 3. 后端设计

### 3.1 `Match` 软删除

`discovery/models.py`:

```python
class Match(models.Model):
    user_a = models.ForeignKey(...)
    user_b = models.ForeignKey(...)
    created_at = models.DateTimeField(auto_now_add=True)
    unmatched_at = models.DateTimeField(null=True, blank=True, db_index=True)
    unmatched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="matches_unmatched",
    )
```

要点:

- **唯一约束 `(user_a, user_b)` 不动**:解除后再滑到也不会新建行,天然防重复;
- `unmatched_by` 用 `SET_NULL`:注销账号不连带删配对记录(虽然注销本来就会 CASCADE 掉 Match,但语义上留一手);
- 新增迁移 `discovery/migrations/0003_match_unmatched.py`(当前最新是 `0002_*`,以实际为准);
- 加属性 `is_active`(返回 `unmatched_at is None`),避免各处手写判空。

### 3.2 新接口 `DELETE /api/v1/matches/{user_id}`

- 路径:`config/api_urls.py` 增 `path("matches/<int:user_id>", discovery_views.unmatch)`;
- `user_id` 是**对方**账号 id,与 `GET /matches` 条目里的 `user_id`、`DELETE /blocks/{user_id}` 同风格,不暴露 match 主键;
- 成功 `204` 空响应(**幂等**:没配对 / 已解除 / 解除自己 一律 204,与 `DELETE /blocks/{user_id}` 一致,不区分「本来就没有」);
- 重封禁 403:全局权限类自动覆盖,白名单不含本接口;
- 事务内写 `unmatched_at=timezone.now()`、`unmatched_by=me`,**提交后**入队 IM 任务:

```python
with transaction.atomic():
    match.unmatched_at = timezone.now()
    match.unmatched_by = me
    match.save(update_fields=["unmatched_at", "unmatched_by"])
    transaction.on_commit(lambda: unmatch_blacklist.delay(me.id, other.id), robust=True)
```

- 不发送任何 IM 消息(静默决策)。

### 3.3 读取侧过滤与「防复活」

所有读 Match 的地方加 `unmatched_at__isnull=True`。目前只有两处:

1. **`match_list`**:`Match.objects.filter(Q(user_a=me) | Q(user_b=me), unmatched_at__isnull=True)`;
2. **`swipe` 的互喜分支**:`get_or_create` 会捞到已解除的旧行,必须显式判断——

```python
match, created = Match.objects.get_or_create(**Match.pair_kwargs(me, target))
if match.unmatched_at is not None:
    matched = False           # 已解除:不复活、不通知
elif created:
    notify_match(match)
    matched = True
else:
    matched = True            # 本来就配对成功过,幂等重放
```

> 这是本批最容易写出 bug 的一处:漏了判断,用户解除后对方再点一次喜欢就会「重新配对」,而发起方毫不知情。

候选池 / 「喜欢我的人」本来就排除已划过的人,无需改动。

### 3.4 IM 双向黑名单任务

`im/tasks.py` 新增:

```python
@shared_task
def unmatch_blacklist(user_a_id: int, user_b_id: int) -> None:
    """解除配对后双向拉黑:双方都收不到、也发不出消息。"""
```

- 参数一律 user_id,任务内查 `User.im_user_id`(任务体内不查 request);
- 双向调 `client.black_list_add(a, b)` 与 `client.black_list_add(b, a)`;
- `im/client.py` 对外永不抛异常,失败只记日志(与现有任务一致);
- 之所以必须放后端:`black_list_add` 是管理员 REST 调用,客户端只能拉黑自己这侧,拉不到对方那侧;且响应路径禁止第三方网络调用。

### 3.5 文档与门禁

- `docs/api/discovery.md` 增 `DELETE /matches/{user_id}` 小节(请求/响应/错误码/幂等语义);
- `docs/api/README.md` 索引与接口计数 35 → 36;
- `ApiDocsCoverageTests` 双向比对必须绿;新增 `.py` 代码补 docstring,`CommentCoverageTests` 必须绿。

## 4. App 设计

### 4.1 入口

**入口 A:聊天页顶栏「⋯」**

`_ChatHeader` 右侧现在是 `SizedBox(width: 48)`(为了让「头像 + 名字」在屏幕上居中)。改成同宽 `IconButton`:

- key `chat.more`,图标 `Icons.more_horiz_rounded`,size 22,色 `AppColors.text1`;
- 点击弹 `showMenu`,目前只有一项「解除配对」(key `chat.menu.unmatch`),危险色 `AppColors.danger`;
- 保留 48 宽度,标题居中不被破坏(布局契约:返回键 48 ↔ 更多键 48)。

**入口 B:他人资料页菜单**

`user_profile_page.dart` 的「举报/拉黑」菜单里,当「当前与他是配对关系」时插入「解除配对」。判定来源:`matchCacheProvider`(key 是 IM id,即 `u$userId`)里是否存在该 peer;缓存未加载完时不显示(避免误判),加载完才出现。

### 4.2 确认与成功流程

弹窗用项目规范 `AppDialog`(不是裸 `AlertDialog`):

> 标题:解除配对?
> 正文:解除后双方将无法再聊天,且无法恢复。
> 按钮:取消 / 解除配对(危险色)

确认后:

1. `imRepository.unmatch(userId)`(新增方法,`ImRepository` 已经持有 `/matches` 的读取)→ `DELETE /matches/{userId}`;
2. 失败:`AppToast` 显示 `ApiException.message`,流程中止(不删本地会话);
3. 成功:
   - `imClient.deleteConversation(peerId)`(失败吞掉,不阻断);
   - `ref.invalidate(matchesProvider)` + `ref.read(conversationsProvider.notifier).reload()`;
   - 聊天页入口:`Navigator.maybePop()`(回到消息页;App 没有 `/chats` 路由,消息页是 HomeShell 的 tab)+ Toast「已解除配对」;
   - 资料页入口:`context.pop()` + Toast「已解除配对」。

### 4.3 对方视角兜底

腾讯 IM **无法远程删除对方设备上的会话**,所以对方仍能看到历史消息。兜底策略:

- 聊天页进入时**主动刷新一次** `matchCacheProvider`(否则缓存是登录时的旧数据,永远发现不了「被解除」);`system_notice` 除外(它不是配对);
- 当「缓存已加载(`value != null`)且 peer 不在缓存里」时:
  - 顶栏下方显示一条横幅「你们已解除配对」(key `chat.unmatchedBanner`),文案中性、不指责;
  - 输入栏禁用(不可输入、不可发图),发送按钮置灰;
  - 历史消息仍可滚动阅读。
- 消息页**不做**隐藏过滤:避免动现有会话列表逻辑,也避免「配对缓存未加载」时误隐藏正常会话。

### 4.4 撤回消息

**IM 抽象层**(`app/lib/im/im_client.dart`):

```dart
class ImMessageRevoked extends ImEvent {
  const ImMessageRevoked(this.msgId);
  final String msgId;
}

abstract class ImClient {
  Future<void> revokeMessage(String msgId);
}
```

`ChatMessage` 增 `bool isRevoked`(默认 `false`),`copyWith` 支持;`ChatMessageKind` 不变(撤回是消息状态,不是新类型)。

**真实实现**(`tencent_im_client.dart`):

- `TencentImSDKPlugin.v2TIMManager.getMessageManager().revokeMessage(msgID: msgId)`;
- advanced listener 注册 `onRecvMessageRevoked: (msgID) => _events.add(ImMessageRevoked(msgID))`;
- 错误码非 0 抛 `ImException`(沿用现有 `_check`)。

**交互**:

- 长按菜单项条件(全部满足才显示「撤回」):
  1. `message.isSelf`;
  2. `message.kind == text || image`;
  3. `!message.isPending && !message.isFailed`;
  4. `now - message.timestamp <= 2 分钟`(常量 `recallWindow`,单位毫秒,与腾讯控制台默认一致);
- 点击直接撤回,无二次确认(微信式);
- 成功后本地先置 `isRevoked = true`(乐观),SDK 事件再兜底;失败 `AppToast` 显示 `ImException.message`;
- 撤回后不可再复制/删除该条(菜单不再弹出,或只保留「删除」——实现取「不弹菜单」)。

**渲染**(`message_bubble.dart`):

- `isRevoked == true` → 居中系统样式小字,key `chat.revoked`:
  - 自己:`你撤回了一条消息`;
  - 对方:`对方撤回了一条消息`;
- 样式走 token(`AppText.micro` + `AppColors.text3`),气泡与头像都不渲染。

### 4.5 会话摘要的已知限制

撤回后,消息页会话摘要可能仍显示原文,直到 SDK 刷新会话(或重进页面)。这是 SDK 行为,不在本批修;写进 §7 已知限制。

## 5. Web 设计

- **IM 层**(`web/src/im/client.ts` + `types.ts`):
  - `ImEvent` 增 `{ type: 'messageRevoked'; msgId: string }`;
  - `ImClient` 增 `revokeMessage(msgId: string)`,内部从 `known` 取消息实例调 `chat.revokeMessage(message)`;
  - 注册 `onMessageRevoked` 事件(名字进 `ImEventNames`,测试可注入)。
- **聊天页**(`ChatPage.vue`):
  - header 右侧加「⋯」按钮 + 下拉菜单(`ChatMoreMenu.vue`),只有「解除配对」;
  - 确认弹窗新建 `UnmatchDialog.vue`(对齐 `DeleteAccountDialog.vue` 的遮罩/焦点/ESC 处理);
  - `api/discovery.ts` 增 `unmatch(userId)`,store `useDiscoveryStore` 增同名 action(调接口 + 从 `matches` 里移除);
  - 成功后清 `chatStore` 会话、`router.push('/chats')`、toast;
  - 对方视角:`discoveryStore.matches` 已加载且 peer 不在其中 → 顶部横幅 + 输入框禁用。
- **消息菜单**(`MessageMenu.vue`):加「撤回」条件项(与 App 同四条规则);`MessageBubble.vue` 渲染撤回态。
- **token 双份维护**:本批不新增视觉 token;若新增颜色(危险色)必须同时改 `app/lib/core/theme/*.dart` 与 `web/src/styles/tokens.css`。

## 6. 测试计划

### 后端(`chatapp/`)

- `Match` 软删除:默认 `unmatched_at is None`、`is_active` 属性;
- `DELETE /matches/{user_id}`:
  - 配对一方可解除 → 204,`unmatched_at/by` 落库;
  - 非配对 / 已解除 → 204 幂等,不重复入队;
  - 未认证 401、重封禁 403;
  - 解除后 `GET /matches` 不再返回;
  - 解除后对方再 `swipe like` → `matched=false`,不重建、不通知(`notify_match.delay` 未被调用);
- `unmatch_blacklist` 任务:双向调用 `black_list_add`;`client` 抛异常不炸任务;
- 接口文档/注释门禁全绿。

### App(`app/`)

- `flutter analyze` 零告警;
- 撤回:菜单条件四条各一个用例(超时/他人/图片/正常)、撤回成功置灰、收到 `ImMessageRevoked` 置灰、渲染文案(自己/对方);
- 解除:聊天页「⋯」→ 确认 → 调接口 → 删会话 → 回消息页;资料页仅在已配对时出现菜单项;失败时不删会话;
- 对方视角:匹配缓存已加载且无此 peer → 横幅 + 输入禁用;缓存未加载 → 不误判;
- 假 IM 客户端补 `revokeMessage` + 事件发射。

### Web(`web/`)

- `vue-tsc` 零错误、`eslint --max-warnings 0` 零告警、`vitest` 全绿(覆盖率门槛 70/60/70/70);
- 对应组件测试:菜单条件、撤回态渲染、解除对话框、对方视角横幅。

### 真机(双模拟器)

- 解除配对:双方配对 → A 解除 → A 回消息页无该会话、B 的配对列表消失;A 的聊天页显示横幅、输入禁用;B 尝试发消息收到失败提示;
- 撤回:A 发消息 → 2 分钟内长按撤回 → 双方均显示「撤回了一条消息」;超过 2 分钟菜单无「撤回」。

## 7. 已知限制

1. **无法远程删对方会话**:对方设备上的历史消息保留可读,这是腾讯 IM 能力边界,靠横幅 + 禁用输入表达状态;
2. **IM 黑名单不可逆**:解除配对后双方永久互不可发消息(与「不可恢复」语义一致),后续若要「重新认识」只能换号;
3. **任务延迟窗口**:`on_commit` 入队到 worker 执行之间有秒级窗口,对方若恰好在此窗口发消息,发起方仍可能收到一条;随后会话被删除,影响可接受;
4. **会话摘要**:撤回后消息页摘要可能短暂显示原文(§4.5);
5. **已读回执**:旗舰版才能做,本批挂起。

## 8. 已读回执为什么挂起

腾讯云 IM 的「消息已读回执」是**旗舰版**功能(控制台需开通且按版本计费),当前应用是**体验版**(100 用户上限,见 `README.md`「腾讯云 IM | 体验版即可」)。在体验版上:

- `sendMessageReadReceipts` / `getMessageReadReceipts` 调用会返回版本不支持的错误;
- 即使前端写好,升级前也不会生效,属于「写了也不绿」的功能。

**升级路径**:采购专业版/旗舰版 → 控制台开启已读回执 → 再立项。届时需要:

- `ImClient` 增 `sendReadReceipt(msgId)` / `getReadReceipts(msgId)`;
- 监听 `onRecvMessageReadReceipts`,在气泡角标显示「已读」;
- 后端无需改动(回执走 IM)。

## 9. 验收标准

- [ ] `DELETE /api/v1/matches/{user_id}` 上线,`docs/api/discovery.md` 同步,接口数 36;
- [ ] 解除后双方配对列表消失、双向发消息失败、不可恢复;
- [ ] 撤回:2 分钟内文字/图片可撤回,双方均显示撤回灰字;
- [ ] App `flutter analyze` 零告警、测试全绿;Web `type-check` + `lint` + `vitest` 全绿;
- [ ] 双模拟器手测通过(§6 真机清单);
- [ ] spec/plan 的 checkbox 回填,CLAUDE.md 里程碑表补一行。
