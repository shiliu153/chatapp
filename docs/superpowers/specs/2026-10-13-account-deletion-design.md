# 账号注销入口(设计)

日期:2026-10-13 · 状态:设计已获用户批准(逐节确认「全部通过」)
上游:上线合规轨 `2026-09-18-launch-execution.md` 的 **T-17 账号注销入口核查/开发**(本地文档,不入仓库);本 spec 是其可执行化落地。
下游:实施计划 `docs/superpowers/plans/2026-10-13-account-deletion.md`(待写)。

## 背景与目标

App Store 审核指南与国内五大商店均**硬性要求**「用户可在应用内注销账号」,且必须真正删除数据。当前项目:

- 后端:`users/views.py::me` 只有 `GET/PATCH`,`DELETE /api/v1/users/me` 不存在;
- 全仓 `grep 注销` **零命中** —— App 隐私政策 §四「你的权利」只写了改资料 / 删照片 / 拉黑 / 退出登录,**没有注销路径**;
- IM 侧:`im/client.py` 有 `kick_user`,但**没有** `account_delete`。

**目标:** 交付一条完整、可手测闭环的注销链路 —— 后端接口 + 数据清理 + IM 删号,App 与 Web 双端入口,并把隐私政策文案与接口文档同步到位。

## 已定关键决策(用户确认)

| 决策点 | 结论 | 落选理由 |
|---|---|---|
| 数据处理语义 | **立即硬删除** | 软删+冷静期需状态机/定时任务/登录分支,复杂度不成比例;匿名化保留需 `phone` 可空迁移 + 各处可见性过滤复查。硬删最彻底,合规解释成本最低 |
| 交付范围 | **后端 + App + Web 双端入口** | Web 是同一后端的正式客户端,不加入口 = 网页用户无法注销(合规缺口);Web 侧增量很小 |
| 二次确认强度 | **两步:后果说明 → 输入完整手机号(后端校验)** | 单次弹窗对不可恢复操作只有一击;输入「注销」二字后端无法校验,纯前端拦截易被绕过 |
| 举报记录 | **随 User 级联一并删除**(不迁移) | 账号已不存在,举报主体/对象均消失;保留需 `SET_NULL` + 脱敏快照字段 + ops 台适配,工作量明显变大 |
| 接口落点 | **`DELETE /api/v1/users/me`**(现有 `me` 视图加 DELETE 方法) | 新路由 `/users/me/account` 与「me 就是当前账号」的既有语义重复;`post_delete` 信号做清理则隐式、跨 app 耦合、难测 |

## 交付物

### 1) 接口契约

| 项 | 内容 |
|---|---|
| 方法与路径 | `DELETE /api/v1/users/me` |
| 鉴权 | `Authorization: Bearer <access>` |
| 请求体 | `{"phone": "<完整手机号,字符串>"}` |
| 成功 | `204 No Content`,空体(与 `DELETE /users/me/photos/{id}` 同口径) |
| `phone` 缺失 | `400 {"code":400,"message":"请输入手机号","request_id":…}` |
| `phone` 不匹配 | `400 {"code":400,"message":"手机号与当前账号不一致","request_id":…}`,**用户与数据保持不变** |
| 重封禁账号 | `403 {"code":403,"message":"账号已被封禁,如有疑问请联系客服","request_id":…}` |
| 轻封禁账号 | 允许注销(轻封禁只禁滑卡) |
| 重复调用 | 用户行已不存在 → JWT 鉴权失败 → `401`(不做特殊幂等处理) |
| 限流 | 不加(一次性操作 + 需认证) |

- 错误一律走现有 DRF 异常契约(`config/exceptions.py::api_exception_handler`),**不手搓 `Response({"code": …})`**。
- **重封禁 403 是既有代码天然提供的**:`moderation/permissions.py::BAN_EXEMPT` 白名单只含 `("GET", "/api/v1/users/me")` 与 `("GET", "/api/v1/users/tags")`,`DELETE` 不在内 → 无需新增代码即挡住「注销洗白」。**白名单本次不放开口子**。
- `ApiDocsCoverageTests` 双向比对要求同一次改动内把该端点写进 `docs/api/users.md`。

### 2) 后端清理服务

新增 `users/services.py::delete_account(user) -> None`,职责单一:清数据 + 清文件 + 清缓存 + 入队 IM 删号。

**步骤**

1. 事务内:先收集待删磁盘文件清单 —— `Photo.file.name` 与 `PostImage.file.name`(必须在删行**之前**收集);
2. 事务内:`user.delete()` 触发 CASCADE;
3. `transaction.on_commit(…, robust=True)`:
   - 逐个 `default_storage.delete(name)`(失败只记日志,留孤儿文件不致命);
   - 清 Redis:`presence:{user_id}`、`im:kick_pending:{user_id}`;
   - 入队 `im_tasks.delete_account.delay(im_user_id)`。

**清理对照表**

| 对象 | 处理 | 依据 |
|---|---|---|
| `accounts.User` | 删(根) | 本次操作对象 |
| `users.Profile` | CASCADE 删 | `on_delete=CASCADE` |
| `users.Preference` | CASCADE 删 | 经 `Profile` |
| `Profile.tags` 关联行 | 删 | M2M through |
| `users.Tag`(标签池) | **保留** | 全局字典,非用户数据 |
| `users.Photo` | CASCADE 删 + **磁盘文件删** | 隐私政策承诺删照片 |
| `discovery.Swipe`(双向) | CASCADE 删 | 滑卡记录 |
| `discovery.Match`(双向) | CASCADE 删 | 配对关系;对方的配对列表随之少一条(预期) |
| `feed.Post` | CASCADE 删 | 广场动态 |
| `feed.PostImage` | CASCADE 删 + **磁盘文件删** | 同上 |
| `feed.PostLike` / `feed.PostComment` | CASCADE 删 | 别人的赞/评论随之删除(动态本身已不存在,预期) |
| `feed.PostReport`(reporter=本人) | CASCADE 删 | 举报记录一并删(用户决策) |
| `feed.PostReport`(post=本人动态,别人举报的) | **保留**,`post` 置 `NULL` | `post` 是 `SET_NULL`(运营留档),现有模型行为,不额外处理 |
| `moderation.Report`(reporter/target 双向) | CASCADE 删 | 用户决策「一并删除」 |
| `moderation.Block`(blocker/blocked 双向) | CASCADE 删 | 拉黑关系 |
| `moderation.BanLog` | CASCADE 删 | 封禁审计随账号消失 |
| `Photo.reviewed_by` / `Report.handled_by` / `PostReport.handled_by` / `BanLog.operator` | `SET_NULL` | 仅在**运营账号**被删时相关;注销用户是普通用户,不涉及 |
| Redis `presence:{id}` | 删 | 在线状态是公开信息,不留残影 |
| Redis `im:kick_pending:{id}` | 删 | 待踢标记已无意义 |
| 腾讯云 IM `u{id}` | **异步删**(先 kick) | 见 §3 |
| 对方设备上的历史聊天记录 | **不动** | 腾讯云 IM 侧不提供撤回;非目标 |

### 3) IM 删号(一处有意偏离既有纪律)

- `im/client.py::delete_account(identifier) -> bool`:调 `im_open_login_svc/account_delete`,body `{"DeleteItem": [{"UserID": identifier}]}`。沿用 client 层「对外永不抛异常,失败记日志返回 False」的约定。
  - ⚠️ 参数形状实施时**用真凭据实测**;本仓库已有两个同类前车之鉴:`sendmsg` 的 identifier 必须是管理员(否则 60010)、`account_import` 对已存在账号会覆盖 `Nick`/`FaceUrl` 而非返回 7015。
- `im/tasks.py::delete_account(...)`:先 `kick_user`(断掉在线会话),再 `account_delete`;沿用 `RETRY_POLICY`(autoretry + backoff + jitter,max_retries=5)。
- 🔴 **纪律偏离:该任务参数传 `im_user_id` 字符串,而非 `user_id`。**
  - 既有纪律是「任务参数一律 user_id,任务内查库」。但注销任务执行时**用户行已经不存在**,任务内查库必然拿到 `None` 而静默 `return` —— 删号永远不会发生(现有 `_user()` 兜底模式会把这个 bug 藏起来)。
  - 处理:任务签名 `delete_account(im_user_id: str)`;在 `im/tasks.py` 顶部与函数 docstring 写明「本任务不查库,因为调用时用户行已删」;同步写入 `docs/pitfalls/backend.md`。
- **已知取舍:** 入队失败(`robust=True` 只记日志)或重试 5 次耗尽 → IM 侧残留 `u{旧 id}` 账号。因 MySQL 自增 id 不复用,新注册账号是 `u{新 id}`,**不会撞上残留账号**,故可接受。

### 4) App 端入口

| 文件 | 改动 |
|---|---|
| `app/lib/features/settings/settings_repository.dart`(新增) | `SettingsRepository(ApiClient)` + `Future<void> deleteAccount(String phone)` → `DELETE /users/me`,body `{"phone": phone}`;`final settingsRepositoryProvider = Provider<SettingsRepository>(…)`(与 `profile_repository.dart` 同范式) |
| `app/lib/features/settings/widgets/delete_account_dialog.dart`(新增) | 两步确认的第二步:`AppDialog` 壳 + 标题「注销账号?」+ 后果清单(资料 / 照片 / 配对 / 聊天关系 / 动态将**永久删除且不可恢复**)+ `AppTextField`(手机号,数字键盘,key `deleteAccount.phone`)+ 取消 / 危险实底「确认注销」(key `deleteAccount.confirm`,手机号非 11 位数字时禁用)。返回 `Future<bool>` |
| `app/lib/features/settings/settings_page.dart` | 危险区分组卡内、`settings.logout` 之上新增一行 `AppListRow(key: Key('settings.row.deleteAccount'), title: '注销账号', centerTitle: true, danger: true)`;点击 → 第一步 `showConfirmDialog(title: '注销账号?', message: <单段后果说明>, confirmLabel: '继续', danger: true)` → 第二步 `DeleteAccountDialog` → 成功 `AppToast.show(context, '账号已注销')` → `ref.read(sessionProvider.notifier).logout()` |

- 两次点击不得合并成一次;第一步用既有 `showConfirmDialog`(它只吃 `title` + `message`,故后果写成**单段**文案,不做项目符号列表),第二步才是需要输入框的自定义 `AppDialog`。
- ⚠️ 实施注意(批次⑥实测坑):`AppTextField` 根节点是 `mainAxisSize.max` 的 `Column`,在**宽松高度约束**下会撑满整屏;`AppDialog` 内是 `Column(mainAxisSize: min)` + `Dialog` 的**有界**约束,正常收缩。写测试时若直接把它塞进 `Scaffold(body:)` 会拿到整屏高度、点击落空 —— 组件测试必须包在 `AppDialog` 或 `Material`+有界盒子里。
- 成功后**复用现成登出通道** `sessionProvider.notifier.logout()`:清本地凭证 → 触发 `_forceLogout` → `imStatusProvider.notifier.logout()`。`ImManager.logout()` 已对 SDK 失败静默(`im_manager.dart:70`),IM 账号已被删也不会炸。
- 凭证清空后路由由会话状态自动回登录页,不需要手工 `context.go`。
- 文案与 key 走「心跳」规则(`AppDialog` / `AppTextField` / `AppListRow` 危险行 / `AppToast`),不新增视觉 token。

### 5) Web 端入口

| 文件 | 改动 |
|---|---|
| `web/src/api/users.ts` | `export function deleteAccount(phone: string): Promise<void>` → `http.delete('/users/me', { data: { phone } })` |
| `web/src/stores/session.ts` | 新增 `async function deleteAccount(phone: string): Promise<void>`:**只调 api 层**(`usersApi.deleteAccount`),失败向上抛;不在这里清会话 |
| `web/src/features/settings/DeleteAccountDialog.vue`(新增) | 模态:后果清单 + `AppInput`(手机号)+ `AppButton`(取消 / danger 确认,格式不合法禁用);沿用仓库既有模态范式 |
| `web/src/features/settings/SettingsPage.vue` | 危险区在「退出登录」下方加「注销账号」按钮;成功后**编排顺序与现有 `onLogout` 完全一致**:`await session.deleteAccount(phone)` → `await chat.close().catch(() => {})` → `session.logout()` → `await router.push({ name: 'login' })`(先断 IM 长连接再清会话) |

- 页面**不直接调 `http`**,一律经 store —— 与仓库纪律「页面只碰 store」一致;而「清会话 + 跳登录页」的编排留在页面,与 `onLogout` 保持同一条路径。

- Web 端 401/错误统一走 `api/http.ts` 与 `ApiError`;页面只碰 store、不直接调 `http`。

### 6) 文案与文档同步(同一次改动内完成)

| 文件 | 改动 |
|---|---|
| `app/lib/features/legal/legal_texts.dart` | 隐私政策 §四「你的权利」补「也可以随时在『设置 → 注销账号』中注销账号,注销后你的资料、照片、配对与动态将被永久删除」;`legalVersion` 1 → 2(启动弹窗会重新弹一次,符合既有机制) |
| `web/src/features/legal/privacy.ts` | 同步同一句 |
| `web/src/features/legal/agreed.ts` | `LEGAL_VERSION` 1 → 2(与 App `legalVersion` 语义一致) |
| `docs/api/users.md` | 新增 `DELETE /api/v1/users/me` 信息行 + 参数表 + 响应 + 状态码含义(门禁 `ApiDocsCoverageTests` 双向比对) |
| `CLAUDE.md` | 后端接口表补一行;里程碑表补本批;纪律条目「IM 副作用唯一入口」补注销任务这一例外 |
| `docs/pitfalls/backend.md` | 新增「注销」一节:任务参数例外、先收集文件名再删行、重封禁 403 天然生效 |
| `docs/superpowers/specs/2026-09-15-ui-design-language-design.md` | **不动**(无新增视觉 token) |

## 不做(Non-goals)

- 不做冷静期 / 注销可撤销;
- 不通知配对对象,不做「对方已注销」提示(IM 账号删除后对方会话自然失效);
- 不做 ops 运营台注销审计(举报记录一并删);
- 不发注销回执短信 / 邮件;
- 不做账号冻结 / 停用(≠ 注销);
- 不处理对方设备上的历史聊天记录。

## 测试策略(TDD)

**后端 `users/tests.py::DeleteAccountTests`**

1. 204 成功:User 行消失,`Profile`/`Preference`/`Photo`/`Swipe`/`Match`/`Post`/`PostImage`/`PostLike`/`PostComment`/`Block`/`Report`/`BanLog` 全部查不到;
2. 磁盘照片与动态图文件被删(`default_storage.exists` 为假);
3. `phone` 不匹配 → 400 + 业务码 400,且**用户与照片仍在**;
4. `phone` 缺失 → 400;
5. 重封禁 → 403,且用户仍在;
6. 轻封禁 → 204;
7. mock `im.tasks.delete_account.delay`,断言事务提交后**恰好调用一次**且参数是 `u{id}`;
8. `presence:{id}` 与 `im:kick_pending:{id}` 两个 Redis key 已清;
9. 注销后旧 access 再用 → 401;
10. 同号重新走 `/auth/sms/verify` → `is_new_user=true` 且 `user_id` 与旧值不同;
11. 只删自己的数据:另一个用户的资料 / 照片 / 动态 / 配对**完全不受影响**。

**后端 `im/tests.py`**

12. `client.delete_account`:`ErrorCode=0` → `True`;`ErrorCode≠0` → `False` 且不抛异常;
13. `task.delete_account`:先 kick 后 account_delete(用 mock 断言调用顺序);失败抛异常以触发重试。

**App**

14. `settings_page_test.dart`:注销行存在、点击进入第一步确认;
15. `delete_account_dialog_test.dart`:手机号格式不合法时确认禁用;取消不发请求;确认后调用 repository;
16. 成功路径:假网络返回 204 → 凭证被清空 → 回到登录页;失败路径(400)→ 弹提示且**仍停在设置页**;
17. 全量 `flutter analyze` 零告警 + `flutter test` 全绿(基线 329)。

**Web**

18. `settings-page.spec.ts`:注销入口与弹窗交互;`session-store.spec.ts`:注销 action 清会话;
19. `npm run type-check` 零错误 + `npm run lint` 零告警 + `npm run test:coverage` 达标(70/60/70/70)。

**手测(交用户,模拟器 release 包)**

20. 正常注销:设置 → 注销账号 → 后果说明 → 输错手机号(被拒)→ 输对手机号 → 成功回登录页;
21. 同号重新登录 = 全新账号(需重新走引导页);
22. 重封禁账号手测:注销入口点击后收到封禁提示(403);
23. Web 端同流程走通。

## 风险与已知取舍

| 风险 | 处置 |
|---|---|
| IM 删号失败/入队失败 → IM 侧残留账号 | 已论证不影响新用户(id 不复用);日志可查;`im/tasks.py` 重试 5 次 |
| 举报记录随注销消失(被举报人注销后重注册) | 用户已拍板接受;重封禁账号被 403 挡住,不存在「重封禁者靠注销洗白」路径;轻封禁洗白面可接受 |
| 磁盘文件删除失败 → 孤儿文件 | 只记日志;不影响业务正确性 |
| 删除自己的动态会连带删掉别人在该动态下的评论 | 预期行为(动态本身已不存在) |
| 输入手机号确认需要用户记得自己的号 | 手机号即登录凭证,用户必然知道;输错有明确 400 提示 |

## 自审更正记录(2026-10-13,设计呈现后)

1. **Web 侧 store 与页面职责重复**:初稿让 `stores/session.ts::deleteAccount` 既调接口又 `resetSession(false)`,而 `SettingsPage.vue` 又要 `chat.close()` → `session.logout()` → 跳转,同一件事两处做。改为 **store 只调接口,页面负责编排**,顺序与现有 `onLogout` 完全一致。
2. **第一步弹窗与 `showConfirmDialog` 能力不匹配**:初稿写「后果清单」,但该 helper 只暴露 `title` + `message`,没有 `content` 入口。改为**单段后果文案**走 `showConfirmDialog`(不为一步确认新造组件);真正的清单式呈现留给第二步自定义 `AppDialog`。
3. **补一条实施注意**:`AppTextField` 在宽松高度约束下会撑满整屏(批次⑥实测坑),组件测试必须包在 `AppDialog` / 有界盒子里,否则按 key 取尺寸与点击都会落空。
