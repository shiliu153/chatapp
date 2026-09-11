# M3 合规收尾设计

日期:2026-09-11
状态:已与用户逐节确认,待用户终审
上游:spec `2026-09-09-dating-app-mvp-design.md` §8/§12;接口约定来源:M2a/M2c 计划末尾「留给下一个里程碑」

## 1. 目标与范围

M3 里程碑原文(spec §12):审核台、举报拉黑联调、协议文本、封禁、<18 拒绝;Android 签名 APK 真机测试。ICP 备案是用户并行事项,不阻塞开发。

**M1/M2 已完成、本期不重复做的部分:**
- <18 拒绝(PATCH 生日 → 400)
- `banned_light` 禁滑卡 / `banned_heavy` 拒签 userSig —— 只是接口级兜底,**没有后台操作入口**,测试里靠直接改库造数据
- 昵称/简介过 `moderation/text_check.py` 词库;照片 `AUTO_APPROVE` 开关
- 前端照片已有「待审核/已驳回」角标

**本期交付:**
1. moderation 实体(Report/Block/BanLog)与 Django admin 审核台(照片审核、举报队列、封禁操作 + 审计)
2. 举报/拉黑接口 + 前端入口(对方公开资料卡,聊天页进入)
3. 拉黑联动:双向不可见、IM 黑名单同步、拉黑方本机删会话
4. 重封禁全域 403(全局 DRF 权限类)+ IM 踢下线
5. 用户协议/隐私政策文本 + 首次启动弹窗同意 + 设置页入口
6. Android 签名 APK(先装模拟器验证;真机后补)

**非目标(YAGNI):** 举报证据截图上传、举报自动封禁、解封申诉流程、通知被拉黑方(静默是行业惯例)、文本/图片审核接腾讯云内容安全(保持开关,M4 接真)。

## 2. 数据模型

`chatapp/moderation/models.py` 新增:

```python
class Report(models.Model):          # 举报
    reporter     = FK(User, related_name="reports_made")
    target       = FK(User, related_name="reports_received")
    type         = TextChoices: harassment 骚扰 / porn 色情 / fraud 诈骗 / other 其他
    detail       = CharField(200, blank=True)
    status       = TextChoices: pending 待处理 / handled 已处理
    handled_note = CharField(200, blank=True)                 # 处理备注
    handled_by   = FK(User, null=True, on_delete=SET_NULL)    # 处理人(运营账号)
    created_at / handled_at(null=True)
    # ordering: -created_at

class Block(models.Model):           # 拉黑
    blocker = FK(User, related_name="blocks_made")
    blocked = FK(User, related_name="blocks_received")
    created_at
    # unique(blocker, blocked);CheckConstraint(blocker != blocked)

class BanLog(models.Model):          # 封禁审计,只增不改
    user     = FK(User, related_name="ban_logs")
    action   = TextChoices: ban_light 轻度封禁 / ban_heavy 重度封禁 / unban 解封
    reason   = CharField(200, blank=True)
    operator = FK(User, null=True, on_delete=SET_NULL)
    created_at
    # ordering: -created_at
```

`users.Profile` 新增 `ban_reason = CharField(200, blank=True)`:存**当前生效**的原因,供前端封禁页展示;历史追溯靠 BanLog。解封时清空。

**写入时机**:`ProfileAdmin.save_model` 对比新旧 `status` → 调 `moderation/services.py` 写一条 BanLog(封禁级别或 unban,reason 取保存后的 `ban_reason`,operator = 当前 admin 用户)。运营只改 Profile 两个字段,审计自动落。

**为什么**:TextChoices 防拼错且中文可读;唯一约束/CheckConstraint 放数据库,并发下也只可能有一条;审计表只增不改,误操作可还原。

## 3. 后端

### 3.1 新增接口

moderation 新建 `urls.py` 挂到 `config/api_urls.py`;资料卡挂 `users/urls.py`。

| 接口 | 行为 |
|---|---|
| `GET /users/{id}` | 公开资料:`user_id/nickname/gender/age/city/bio/tags/approved photos`;**目标 heavy 封禁、或与请求者存在任一方向 Block → 404「用户不存在」**;light 封禁不影响可见性(轻封禁只禁其滑卡) |
| `POST /reports` | `{target_user_id, type, detail?}`;不能举报自己;`(reporter, target)` 已有 pending 举报 → 不新建,返回已有记录(200),否则建一条(201);响应 `{id, status}` |
| `GET /blocks` | `[{user_id, nickname, avatar_url, blocked_at}]`(头像取第一张已过审照片) |
| `POST /blocks` | `{target_user_id}`;不能拉黑自己;`get_or_create` 幂等(201 新建 / 200 已有);创建后后台线程同步 IM 黑名单 |
| `DELETE /blocks/{user_id}` | 204 幂等;后台线程移除 IM 黑名单 |

### 3.2 封禁拦截(全局)

- `moderation/permissions.py::IsNotHeavyBanned`,加入 `REST_FRAMEWORK.DEFAULT_PERMISSION_CLASSES`
- 规则:未登录请求直接放行(登录/验证码/刷新 token 都是 AllowAny);`banned_heavy` → 403 `{"code":403,"message":"账号已被封禁,如有疑问请联系客服"}`
- 白名单(方法 + 路径):`GET /api/v1/users/me`(前端要能读封禁原因)、`GET /api/v1/users/tags`
- **保留** `discovery/views.py` 里的显式检查(它同时管轻封禁);**移除** `im/views.py` 的 heavy 检查(全局类已覆盖)
- Django admin 不走 DRF,不受影响

### 3.3 拉黑可见性与 IM 同步

- 候选卡片、`GET /matches`:排除「我拉黑的 ∪ 拉黑我的」;`GET /users/{id}` 双向 404
- 已有 Swipe/Match 记录**不物理删除**:解除拉黑后配对关系仍在,对方(设备上会话还在)发消息即可重建会话;拉黑方本机会话已删,聊天记录不恢复
- `im/client.py` 新增 `black_list_add(owner, other)` / `black_list_delete(owner, other)`:`POST v4/sns/black_list_add|delete`,body `{From_Account: owner, To_Account: [other]}`;沿用「永不抛异常、失败记日志」约定
- 重封禁时新增 `kick_user(identifier)`:`POST v4/im_open_login_svc/kick`,把在线 IM 会话踢下线(不然等 userSig 过期最长 7 天还能聊)
- 以上调用一律后台线程异步(沿用 `discovery/services.py::_notify_async` 模式);测试里 patch 后台函数,**别 patch 线程里的真实调用**(M2c 教训)

### 3.4 限流

`DEFAULT_THROTTLE_RATES` 增 `"report": "20/day"`,throttle 类放 `moderation/throttles.py`(沿用 discovery 的写法)。

## 4. 审核台(Django admin)

- **PhotoAdmin**(users):列表加缩略图预览(`format_html` 的 `<img height=60>`);批量动作「通过所选照片」「驳回所选照片」;动作后对涉及的每个用户 `refresh_status()`(照片被驳回可能让人掉回「未完善」,失去候选资格)
- **ProfileAdmin**(users):编辑页出现 `status` + `ban_reason`;`save_model` 自动写 BanLog;列表沿用 status 过滤
- **ReportAdmin**(moderation):列表 type/status/双方/时间/处理人;过滤器 status、type;搜索双方手机号;详情页填 `handled_note` 并把 status 改 handled,`save_model` 自动补 `handled_at`+`handled_by`
- **BlockAdmin / BanLogAdmin**:只读(`has_add/change/delete_permission=False`),供对账;手工加 Block 会漏 IM 同步,审计表改了就不叫审计
- **运营账号**:`createsuperuser`(先看库里有没有,没有则新建,口令用户定)

封禁动线:举报队列点进被举报人 Profile → 改 status + 填原因 → 保存 → 审计自动落 + (重封禁)后台踢下线。

## 5. 前端

| 块 | 内容 |
|---|---|
| 资料卡 `features/profile/user_profile_page.dart`,路由 `/users/:id` | 入口:聊天页 AppBar 标题;照片区/昵称·年龄·城市/标签/简介;底部「举报」「拉黑(红字)」;404 → 「用户不存在」错误态 |
| 举报 | 底部弹窗:4 类型单选 + 补充说明(≤200);成功 SnackBar「已收到举报,我们会尽快处理」 |
| 拉黑 | 二次确认(注明会清本机聊天记录)→ `POST /blocks` → 调 IM `deleteConversation(c2c_uX)` → 刷新会话列表 → SnackBar「已拉黑」→ 返回上一页;`lib/im/im_client.dart` 抽象层新增 `deleteConversation`(Tencent + Fake 两实现) |
| 黑名单管理 `/settings/blocks` | 设置页入口;列表(头像/昵称/时间)+「解除」二次确认 → DELETE → 移除;空态「还没有拉黑任何人」 |
| 协议与隐私 `features/legal/` | `legal_texts.dart` 两份文本 + **版本号**;启动时读 `shared_preferences` 的 `legal_agreed_version`,与当前版本不一致(含首次为空)→ 不可关的弹窗(简短说明 + 两个全文链接 + 「同意并继续」/「不同意」;不同意 → `SystemNavigator.pop`,桌面/Web 降级为提示);同意后写入当前版本再继续启动鉴权;设置页加「用户协议」「隐私政策」入口(全文页 `/legal/agreement`、`/legal/privacy`) |
| 封禁页 | `home_shell` watch `profileProvider`,`status == banned_heavy` → 整屏封禁页(原因 + 退出登录);轻封禁不特殊处理 |

**被拉黑方视角**:App 无法感知(隐私设计),发消息失败由 SDK 标准提示兜底,不做额外 UI。

## 6. 签名打包与验证

1. `keytool` 生成 keystore;keystore 文件 + 口令由用户保管并备份(丢了将无法更新已上架应用)
2. `app/android/key.properties`(gitignored)+ `build.gradle.kts` 配 release signingConfig
3. `flutter build apk --release --dart-define=API_BASE=http://<电脑局域网IP>:8000/api/v1`;`.env` 的 `ALLOWED_HOSTS` 加该 IP
4. 安装验证:**先装到模拟器**(adb install)跑核心链路;真机测试用户方便时后补

## 7. 实施批次

每批结束:`python manage.py test` 全绿、`flutter analyze` 零告警 + `flutter test` 全绿,可手测。分支 `m3-compliance`,用户手测通过后合 master。

1. **模型 + 封禁链路**:moderation 三模型、`ban_reason`、全局权限类、admin 封禁与审计、kick 实测(后端)
2. **举报/拉黑接口 + 可见性联动**:Report/Block API、限流、候选/配对过滤、资料卡 404、IM 黑名单同步实测(后端)
3. **资料卡 + 举报/拉黑前端**:`GET /users/{id}`、资料卡页、举报弹窗、拉黑流 + 删会话(全栈)
4. **黑名单管理 + 协议与隐私 + 封禁页**(前端为主)
5. **签名打包 + 双端手测 + 文档收尾**(CLAUDE.md、计划勾选)

## 8. 测试与验收

**后端新增用例要点**:举报幂等 + 限流;拉黑双向不可见(候选/配对/资料卡 404)、解除后恢复;IM 黑名单/踢人调用被 mock 且被断言;heavy 用户遍历业务接口 403、白名单放行;light 只拦滑卡;admin 保存封禁自动写 BanLog;照片批量驳回后用户资料状态重算。

**前端新增用例要点**:资料卡渲染与 404;举报提交;拉黑流(断言 FakeImClient 收到 deleteConversation);黑名单解除;协议弹窗(首见弹/已同意不弹/不同意退出);banned_heavy 时 home_shell 显示封禁页。测试脚手架默认写入「已同意」,仅协议用例造首见状态。

**双端手测清单**(两台模拟器):互滑配对 → 互聊;A 举报 B → admin 队列可见;A 拉黑 B → B 发消息失败、A 会话消失、双方互相不可见;解除拉黑 → 恢复可见;admin 重封禁 → 被封端整屏封禁页 + IM 被踢;admin 照片审核 → 端上角标状态变化;签名 APK 安装启动。

**验收**:以上全绿 + 双端手测通过 + 文档更新到位。

## 9. 风险与待实测点

| 风险 | 处置 |
|---|---|
| `sns/black_list_add|delete` 的 `identifier` 语义(是否同 sendmsg 必须管理员) | 实施时用真凭据先打一发验证,与 M1 的 sendmsg 经验一致 |
| `im_open_login_svc/kick` 的账号要求与返回码 | 同上,实测 |
| IM 黑名单的实际拦截范围(单聊、消息类型)以腾讯云控制台当前配置为准 | 实施时对照官方文档;UI 侧还有「删会话 + 双向不可见」兜底 |
| 重封禁用户若已有有效 userSig,kick 前仍可能收发消息 | kick 调用失败只记日志;业务接口已即时 403 |
| 协议文本仅为草稿 | 上架前按商店与法规核对修订(spec §13 已记) |
