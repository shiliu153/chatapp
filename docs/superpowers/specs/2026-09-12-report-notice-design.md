# 举报处理通知设计

日期:2026-09-12
状态:已与用户逐节确认(两入口两路径都发 / 统一文案 / 服务层收口 / admin 覆盖),待用户终审
上游:M3 合规(`specs/2026-09-11-m3-compliance-design.md`)、封禁系统消息与消息页(`specs/2026-09-11-ban-notice-message-page-design.md`)
背景:用户手测举报流程(提交举报 → 运营台「同意/已处理」)后提出 —— 举报者全程无感知,应有一条「举报已处理」的系统消息形成闭环。

## 1. 目标与范围

1. 举报处理完成时,以「系统通知」身份给**举报者**发一条 IM 消息,告知举报已处理。
2. 覆盖两条处理路径:ops 台「已处理」与「快速封禁」。
3. 覆盖两个处理入口:ops 台与 Django admin(「admin 与 ops 同源」的项目既定模式)。
4. 文案统一、不披露处罚细节、不引用运营内部备注。

**非目标(YAGNI):** 「驳回/无效举报」通知(系统里没有此状态)、按举报类型定制文案、处罚细节披露、前端新视觉(复用现有系统通知灰条)。

## 2. 消息形态

- custom 消息 `TIMCustomElem`,Data `{"type": "report_handled"}`,From = `system_notice`(与 `ban_notice`/`ban_lifted` 同构)。
- Desc 文案(固定):`您提交的举报已处理,感谢您对社区安全的支持。`
- App 内渲染:归入现有「系统通知灰条」(聊天页居中灰条 + 会话列表预览取 Desc),无新视觉。

## 3. 后端链路(全部经任务队列,响应路径不碰腾讯)

沿用举报/封禁现有模式:client 封装(失败只记日志返回 False)→ Celery 任务(带重试)→ 服务层 `_enqueue` 入队(on_commit + robust)。

- `im/client.py::send_report_handled(to_identifier) -> bool` — 发 custom 消息,Desc 为固定文案。
- `im/tasks.py::report_handled(reporter_id: int)` — 任务参数一律 user_id,任务内查库取 `im_user_id`;用户不存在时静默返回(与现有任务一致)。
- `moderation/services.py::notify_report_handled(report) -> None` — `_enqueue(im_tasks.report_handled, report.reporter_id)`。

**触发点(3 处,均挂在各自已有的「首次标记处理」分支上):**

| 入口 | 分支位置 |
|---|---|
| ops「已处理」按钮 | `ops/views.py::report_handle` 的 `report.status == PENDING` 分支内 |
| ops「快速封禁」按钮 | `ops/views.py::report_ban` 中 pending → handled 的标记分支内 |
| Django admin | `moderation/admin.py::ReportAdmin.save_model` 中「首次补 handled_at」分支内 |

**幂等:** 三处都只在首次标记处理时进入,重复点击不会重复入队;`report_ban` 对已处理举报再封禁时不发通知(处理时已发过)。被举报人的封禁通知(`ban_notice`)逻辑不变,两条消息互不影响。

## 4. 前端

- `tencent_im_client.dart::_kindOf`:`report_handled` → `ChatMessageKind.banNotice`(一行映射;不为它新增 kind——渲染与文案来源完全一致,Desc 即文案)。
- 会话列表预览、聊天页灰条:沿用 banNotice 分支,零新代码。

## 5. 测试与验证

**后端(预计 +5~7 个用例,全量 247 保持全绿):**
- `send_report_handled` payload:From/To、Data type、Desc 文案(mock `requests`,不真打腾讯)。
- `report_handled` 任务体:调 client 打桩断言目标;用户不存在时静默。
- ops 两路径:各断言「入队 `report_handled(reporter_id)`」(patch `im.tasks.report_handled.delay` + `captureOnCommitCallbacks`);「已处理」重复点击只入队一次。
- admin:首次改状态为已处理时入队(admin 测试客户端);补写分支外(重复保存)不入队。

**Flutter(预计 +1~2 个用例,全量 156 保持全绿,analyze 零告警):**
- `report_handled` → 灰条渲染,文案取 Desc。

**手测(双模拟器 + /ops/):**
1. 举报者(A)提交举报 → ops 点「已处理」→ A 的消息页「系统通知」置顶行出现灰条「您提交的举报已处理…」。
2. 「快速封禁」路径:举报者同样收到;被举报者收到原有封禁通知,两条互不影响。
3. 重复点「已处理」不产生第二条通知。

## 6. 关键决策记录

- 两条路径都发(用户选 1):「快速封禁」对举报者正是「举报成功」的典型场景。
- 统一模糊文案(用户选 1):处罚细节不向举报者披露,防试探/报复;运营备注是内部语言,不进通知。
- 服务层收口 + 三处「首次」分支调用(用户选 A):与 `log_ban_change` 同模式,通知逻辑单点维护、天然幂等。
- admin 一并覆盖(用户选 1):运营两个入口行为一致。
