# 设置页补齐(设计)

日期:2026-10-20 · 状态:设计已获用户确认(逐节确认后「开始」)
上游:P1「留存闭环」第二小批(拆分见 `2026-10-20-likes-received-design.md` §1)。
下游:实施计划 `docs/superpowers/plans/2026-10-20-settings-completion.md`。

## 1. 背景与定位

P1-1「喜欢我的人」已交付并合入 master。本批 P1-2 补设置页的三块空白:

1. **意见反馈**:目前用户没有任何反馈入口,问题只能靠运营从举报里猜;
2. **关于 / 版本**:设置页没有应用信息、版本号与协议集中入口;
3. **通知设置骨架**:P1-4 才做推送,但设置页应先把位置留出来,避免上线时再改信息架构。

**目标:** 让用户能提交反馈并被运营看到;设置页形成「账号与隐私 / 帮助与关于 / 危险区」三段式结构;关于页能回答「这是什么应用、什么版本、协议在哪」。

**非目标(本批不做):**

- 反馈图片上传、反馈进度查询、用户侧反馈历史;
- 推送能力本身(P1-4:设备 token、厂商通道、深链);
- 通知开关的持久化(当前没有推送,存了也不会生效);
- 检查更新 / 版本接口(未上架,收益低);
- 客服工单系统、自动回复。

## 2. 已定关键决策(用户确认)

| 决策点 | 结论 | 落选理由 |
|---|---|---|
| 反馈落点 | **新建 `feedback` app + `POST /api/v1/feedback` + ops 台列表** | 塞进 `moderation` 会让举报口径变浑;只靠 mailto 会丢反馈 |
| 反馈字段 | 类型 + 内容 10–500 字 + 可选联系方式(≤64) | 图片上传要复用审核链路,工作量明显变大 |
| 通知设置 | **只读骨架**:禁用开关 + 「即将上线」 | 本地假开关未来会被服务端设置取代,误导用户 |
| 关于 / 版本 | 静态关于页,不做检查更新 | 未上架,没有可比对的版本源 |
| 版本号来源 | App 常量 + pubspec 守卫测试;Web 由 Vite 从 `package.json` 注入 | 引入 `package_info_plus` 只解决 App 一半问题 |
| 交付范围 | **App + Web 双端** | 项目惯例:同一套能力两端对齐 |
| 应用展示名 | **心跳** | 与网页标题、设计语言一致 |

## 3. 后端设计

### 3.1 新 app `feedback`

目录:`chatapp/feedback/{__init__.py, apps.py, models.py, serializers.py, views.py, urls.py, throttles.py, tests.py, migrations/0001_initial.py}`,并加入 `INSTALLED_APPS`。

```python
class FeedbackType(models.TextChoices):
    FEATURE = "feature", "功能建议"
    BUG = "bug", "问题反馈"
    ACCOUNT = "account", "账号问题"
    OTHER = "other", "其他"


class FeedbackStatus(models.TextChoices):
    PENDING = "pending", "待处理"
    HANDLED = "handled", "已处理"


class Feedback(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="feedbacks")
    type = models.CharField("类型", max_length=20, choices=FeedbackType.choices)
    content = models.TextField("反馈内容", max_length=500)
    contact = models.CharField("联系方式", max_length=64, blank=True)
    status = models.CharField("状态", max_length=10, choices=FeedbackStatus.choices,
                              default=FeedbackStatus.PENDING)
    handled_note = models.CharField("处理备注", max_length=200, blank=True)
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="feedbacks_handled")
    created_at = models.DateTimeField(auto_now_add=True)
    handled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
```

要点:

- `user` 用 `CASCADE`:注销账号会连同反馈一起硬删除,与「注销 = 删除全部数据」一致;
- `handled_by` 用 `SET_NULL`:运营账号被删不应连带删用户反馈;
- 状态、处理人、处理时间与 `moderation.Report` 同款,ops 台交互可以照抄。

### 3.2 接口 `POST /api/v1/feedback`

- 鉴权:需要登录;重封禁由全局权限类 403;轻封禁**允许**提交(轻封禁只禁滑卡);
- 限流:按用户 `5/hour`;DEBUG 下 `50/hour`(env `FEEDBACK_RATE`,写法同 `PRESENCE_RATE`);
- 请求体:`{"type": "feature", "content": "...", "contact": "..."}`;
- 校验:类型必须在枚举内;内容去首尾空白后 10–500 字;联系方式选填、≤64 字;
- 响应:`201` + `{id, type, content, contact, created_at}`(不回显 `status` / 处理人,用户侧不需要);
- 错误:400 参数不合法(业务码沿用统一异常处理)、401 未登录、403 重封禁、429 超限。

### 3.3 运营台

- `GET /ops/feedback/`:列表页,默认只看 `pending`,支持 `status` 与 `type` 筛选;最多 200 条;显示时间、用户(手机号 + 昵称)、类型、内容、联系方式、状态;
- `POST /ops/feedback/<id>/handle`:标记已处理,可填备注;写 `handled_by` / `handled_at`;HTMX 局部刷新,与 `post_report_handle` 同款;
- 侧栏新增「意见反馈」入口 + 待处理角标(`ops/context_processors.py` 增加一条 COUNT,仅对 `is_staff` 查库);
- 不提供删除反馈的入口:反馈是运营决策依据,只增不删。

### 3.4 文件

| 文件 | 职责 |
|---|---|
| `chatapp/feedback/models.py`(新增) | `Feedback` / `FeedbackType` / `FeedbackStatus` |
| `chatapp/feedback/serializers.py`(新增) | 入参校验与出参字段 |
| `chatapp/feedback/views.py`(新增) | `create_feedback` |
| `chatapp/feedback/throttles.py`(新增) | 按用户限流 |
| `chatapp/feedback/urls.py`(新增) | `POST /feedback` |
| `chatapp/config/settings.py`(改) | `INSTALLED_APPS` + `FEEDBACK_RATE` + `DEFAULT_THROTTLE_RATES` |
| `chatapp/config/api_urls.py`(改) | 挂载 `feedback.urls` |
| `chatapp/ops/views.py` / `urls.py` / `context_processors.py`(改) | 列表、处理、角标 |
| `chatapp/ops/templates/ops/feedback.html`(新增) | 列表与行内处理表单 |
| `chatapp/ops/templates/ops/base.html`(改) | 侧栏入口 |
| `docs/api/feedback.md`(新增)、`docs/api/README.md`(改) | 接口文档;接口数 34 → 35 |

## 4. App 端设计

### 4.1 设置页信息架构

`app/lib/features/settings/settings_page.dart` 由两张卡改为三张卡:

| 分组 | 行 |
|---|---|
| 账号与隐私 | 黑名单(`settings.row.blocks`)、通知设置(`settings.row.notifications`) |
| 帮助与关于 | 意见反馈(`settings.row.feedback`)、关于(`settings.row.about`)、用户协议(`settings.row.agreement`)、隐私政策(`settings.row.privacy`) |
| 危险区 | 注销账号、退出登录(不变) |

### 4.2 意见反馈页 `/settings/feedback`

- 顶栏:`AppSubPageBar(title: '意见反馈')`;
- 类型:`AppOptionGroup` 四段(功能建议 / 问题反馈 / 账号问题 / 其他),默认选中「功能建议」;
- 内容:`AppTextField(maxLines: 6, minLines: 6, maxLength: 500, counterKey: ...)`,标签「反馈内容」,提示「说说遇到了什么,或希望我们做什么(至少 10 字)」;
- 联系方式:`AppTextField(maxLength: 64)`,标签「联系方式(选填)」,提示「手机号 / 邮箱 / 微信,方便我们回复你」;
- 提交:`AppButton` 通栏;内容去空白后不足 10 字时禁用;提交中显示 loading 且禁用;
- 成功:`AppToast.show('反馈已提交,谢谢你')` 后 `context.pop()` 回设置页;
- 失败:`AppToast.show(error.message)`,保留用户输入,按钮恢复可点;
- key:`feedback.type.{feature|bug|account|other}`、`feedback.content`、`feedback.contact`、`feedback.submit`。

### 4.3 通知设置页 `/settings/notifications`

- 顶栏「通知设置」;
- 两张行卡(或一张卡两行):「新配对提醒」「新消息提醒」,右侧为**禁用** `Switch.adaptive`,标题下副标题说明各自内容;
- 每行尾部或副标题带「即将上线」标记;
- 底部说明段:推送功能将在后续版本上线,届时可分别控制两类提醒;当前不保存任何开关状态;
- key:`notifications.match`、`notifications.message`。

### 4.4 关于页 `/settings/about`

- 顶栏「关于」;
- 居中:品牌标(`AppBrandMark`)+ 应用名「心跳」+ `版本 1.0.0`;
- 行卡:用户协议、隐私政策(复用现有 `/legal/*` 路由);
- 页脚:备案号(常量 `appIcpNumber` 为空时整行隐藏)+ `© 2026 心跳`;
- key:`about.version`、`about.agreement`、`about.privacy`。

### 4.5 版本单一来源

新增 `app/lib/core/app_info.dart`:

```dart
/// 应用展示信息:关于页与测试共用。
const appDisplayName = '心跳';
const appVersion = '1.0.0';
const appIcpNumber = '';   // 备案号下来后填,空串表示不展示
```

新增 `app/test/core/app_info_test.dart`:读取 `pubspec.yaml`,断言 `version:` 行的 `+` 前部分等于 `appVersion`。改版本忘同步会直接红。

### 4.6 文件

| 文件 | 职责 |
|---|---|
| `app/lib/core/app_info.dart`(新增) | 展示名 / 版本 / 备案号 |
| `app/lib/features/settings/feedback_page.dart`(新增) | 表单 + 校验 + 提交 |
| `app/lib/features/settings/notification_settings_page.dart`(新增) | 只读骨架 |
| `app/lib/features/settings/about_page.dart`(新增) | 静态信息 + 协议入口 |
| `app/lib/features/settings/settings_repository.dart`(改) | `submitFeedback` |
| `app/lib/features/settings/settings_page.dart`(改) | 三段式 |
| `app/lib/router.dart`(改) | 三条路由 |
| `app/test/features/settings/*`(新增/改) | 页面与入口测试 |

## 5. Web 端设计

### 5.1 设置页信息架构

`web/src/features/settings/SettingsPage.vue` 的 `entries` 改为三组,每组一张 `AppCard`:

| 分组 | 行 |
|---|---|
| 账号与隐私 | 编辑资料、想找的人、我的动态、黑名单、通知设置 |
| 帮助与关于 | 意见反馈、关于、用户协议、隐私政策 |
| 危险区 | 注销账号、退出登录(保持按钮形态) |

Web 原有的「编辑资料 / 想找的人 / 我的动态」保持在第一组,不因重排而丢失入口。

### 5.2 意见反馈页 `/settings/feedback`(`name: 'settings-feedback'`)

- 壳外二级页,自带「← 返回」;
- 类型:4 个按钮 2×2,选中态复用 `ReportDialog` 的描边 + 品牌色;
- 正文:`<textarea>`(tokens、`maxlength=500`、右下计数、10 字下限);
- 联系方式:`AppInput`(≤64,选填);
- 提交:`AppButton` 通栏;不足 10 字禁用;提交中 loading;
- 成功:整页切「已收到你的反馈」成功态(图标 + 说明 + 「返回设置」按钮),避免重复提交;
- 失败:表单内联错误(`parseApiError(e).message`),保留输入;
- 不新建全局 toast 体系。

### 5.3 通知设置页 `/settings/notifications`(`name: 'settings-notifications'`)

- 标题 + 说明段;
- 两行「新配对提醒」「新消息提醒」,右侧为禁用开关(自绘 pill + 圆点,`aria-disabled`),带「即将上线」文字;
- 不做本地存储。

### 5.4 关于页 `/settings/about`(`name: 'settings-about'`)

- 应用名「心跳」+ 版本号 + 协议/隐私入口 + 版权行;备案号常量空则隐藏;
- 版本号来自 `__APP_VERSION__`。

### 5.5 版本注入

- `web/package.json` 版本对齐到 `1.0.0`;
- `web/vite.config.ts` 增加 `define: { __APP_VERSION__: JSON.stringify(pkg.version) }`(读 `package.json`,不手写第二份);
- `web/src/vite-env.d.ts` 声明 `declare const __APP_VERSION__: string`;
- 新增 `web/src/features/settings/appInfo.ts`:导出 `APP_NAME = '心跳'`、`APP_VERSION = __APP_VERSION__`、`APP_ICP = ''`。

### 5.6 文件

| 文件 | 职责 |
|---|---|
| `web/src/features/settings/appInfo.ts`(新增) | 展示名 / 版本 / 备案号 |
| `web/src/features/settings/FeedbackPage.vue`(新增) | 表单 + 成功态 |
| `web/src/features/settings/NotificationSettingsPage.vue`(新增) | 只读骨架 |
| `web/src/features/settings/AboutPage.vue`(新增) | 静态信息 |
| `web/src/api/settings.ts`(新增) | `submitFeedback` |
| `web/src/features/settings/SettingsPage.vue`(改) | 三组 |
| `web/src/router/routes.ts`(改) | 三条路由 |
| `web/vite.config.ts` / `web/package.json` / `web/src/vite-env.d.ts`(改) | 版本注入 |
| `web/tests/component/*`(新增/改) | 页面与入口测试 |

## 6. 边界与失败路径

| 场景 | 行为 |
|---|---|
| 内容只有空白 | 前端按钮禁用;后端去空白后 <10 字返回 400 |
| 内容超过 500 字 | 前端 `maxLength` 截断;后端 400 |
| 重复提交 | 提交中按钮禁用;成功即离开表单(Web 切成功态) |
| 限流 429 | toast / 内联展示后端文案;输入保留 |
| 提交时被重封禁 | 403 → 展示「账号受限」;页面不崩 |
| 注销账号 | 反馈随 `CASCADE` 删除 |
| 运营重复点「标记已处理」 | 已处理记录不再显示按钮;接口幂等(重复 POST 只更新备注) |
| 备案号为空 | 关于页整行隐藏,不显示「暂无」 |
| 版本号改错 | App 测试读 `pubspec.yaml` 直接红 |

## 7. 测试与门禁

### 7.1 后端(`chatapp/feedback/tests.py`、`chatapp/ops/tests.py`)

- 提交成功:201、字段回显、落库 `pending`;
- 类型非法 400;内容 9 字 / 501 字 400;空白内容 400;联系方式 65 字 400;
- 未登录 401;重封禁 403;轻封禁可提交;
- 限流:patch `FeedbackThrottle.rate` 为 `1/day`,第二次 429;
- 注销账号后反馈被级联删除;
- ops:列表默认只显示 pending、按状态/类型筛选、标记已处理写入处理人/时间/备注、非 staff 403。

### 7.2 App

- 设置页三组入口齐全,点击进入对应页;
- 反馈页:默认类型、内容不足禁用、提交请求体正确、成功 toast、失败保留输入;
- 通知页:两个开关均禁用、显示「即将上线」;
- 关于页:显示「心跳」「1.0.0」,协议入口可点;
- `app_info_test` 守卫 pubspec 版本。

### 7.3 Web

- 设置页三组入口齐全;
- 反馈页:类型切换、内容不足禁用、提交成功切成功态、失败内联错误;
- 通知页:开关禁用 + 即将上线;
- 关于页:显示应用名与版本,协议链接指向 `/legal/*`。

### 7.4 文档与门禁

- `docs/api/feedback.md` 按 7 元素模板写;`docs/api/README.md` 接口数 34 → 35;
- `CLAUDE.md` 接口表补一行;
- `ApiDocsCoverageTests` / `CommentCoverageTests` 绿;
- 后端全量 `python manage.py test`;
- App `flutter analyze` 零告警 + `flutter test`;
- Web `npm run type-check` + `npm run lint` + `npm run test:run`。

## 8. 已知取舍

- **不做反馈图片**:要复用照片上传/审核,超出「补齐设置页」的范围;
- **不做用户侧反馈历史**:反馈是单向通道,没有「工单状态」语义;
- **通知开关只读**:没有推送时给可点开关等于骗用户;上线时再改服务端设置;
- **反馈限流按账号**:换账号可绕过,但提交需要登录且内容会留痕,足够;
- **运营台不删反馈**:保留决策依据;真要清理走数据库。

## 9. 验收标准

1. 设置页三段式结构在 App / Web 一致,新增入口全部可达;
2. 用户能提交反馈,ops 台能看到并标记已处理;
3. 校验(类型 / 10–500 字 / 联系方式)与限流按设计生效;
4. 通知设置页只读、明确「即将上线」,不产生任何本地状态;
5. 关于页显示「心跳」与 `1.0.0`,协议与隐私入口可用,备案号为空时不显示;
6. 接口文档同步,三端门禁全绿。
