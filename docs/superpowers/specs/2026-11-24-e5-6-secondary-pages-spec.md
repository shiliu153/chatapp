# E-5.6 页面规格：二级页 —— 登录/引导、设置、表单与列表

> **立项**：2026-11-24 · **状态**：page spec，**已确认**（2026-11-24 主人拍板，结论见 §7；**本单拆成 E-5.6a–d 四个子单**）
> **上游**：[Ember 规范](../specs/2026-11-23-ui-redesign-ember-design.md)（v1.0）§5 / §6 / §7 / §8.2 / §8.3 / §9.3 / §9.4
> **实施计划**：[E-5 逐页迁移](../plans/2026-11-23-ui-redesign-ember.md) 第 6 单（App 线，最后一单）
> **模板**：[E-5.3 对话页](2026-11-24-e5-3-chat-page-spec.md) / [E-5.5 回声页](2026-11-24-e5-5-square-page-spec.md)
> **栈**：`app`

---

## 1. 目标

把**所有二级页**从心跳口径迁到 Ember，并把 §9.4 的「二级页统一 shell」落到一处可复用的实现上。
业务逻辑零改动。

本单覆盖的页面（按功能分四组）：

| 组 | 页面 | 现状行数（约） |
|---|---|---|
| **A 准入** | `auth/splash_page`、`auth/login_page`、`onboarding/onboarding_page`、`legal/legal_page` + `legal_gate` | 151 / 183 / 338 / 52 + 16 |
| **B 设置** | `settings/settings_page`、`notification_settings_page`、`devices_page`、`blocked_users_page`、`about_page`、`feedback_page`、`theme_mode_row`、`visits_hidden_row` | 178 / 91 / 159 / 113 / 81 / 121 / 104 / 58 |
| **C 表单** | `profile/profile_edit_page` + `profile_form_fields`、`preference_page`、`square/post_compose_page` | 183 + 109 / — / — |
| **D 列表** | `notifications/notifications_page`、`square/favorites_page`、`my_posts_page`、`post_likes_page` | 241 / — / — / 113 |

用户可见的变化（四组共通）：

| # | 变化 | 从 → 到 |
|---|---|---|
| 1 | **顶栏** | 各自实现 → **统一 §9.4 shell**：高 52、返回 22 Phosphor `caret-left`、标题 17/w600 居中；抽成 `core/ui` 的 `EmberPageScaffold` |
| 2 | **表单控件** | 自绘输入框 → **`EmberField`**（`surface.card` + 1px `border.divider` + `radius.md` + 高 52；focus 2px `brand.default` + 2px 外扩；error 2px `status.danger` **且必须带文字说明**） |
| 3 | **主按钮** | 自绘 → **`EmberButton`**（52 高、`radius.pill`、`emberGlow`） |
| 4 | **列表行** | 自绘 → 行高 68–76、`subtitle` 17/w600 + `caption` 13 `text.secondary`、分隔线 `border.divider` |
| 5 | **开关 / 选择行** | 自绘 → 统一行组件（标题 + 副标题 + 右侧 `Switch`/值/箭头），`Switch` 用 `brand.default` |
| 6 | **危险操作** | 红字按钮 → `EmberButton` 危险变体（描边 `status.danger`，**确认后才实底**） |
| 7 | **Dialog** | 自绘 → 统一 Dialog：图标 + 明确动词（§9.3） |
| 8 | **图标** | Material `*_rounded` → **Phosphor** |
| 9 | **动效** | curve → **`spring.*`**；页面 push 右滑入（`spring.standard`）；按压 `scale .97` |

**明确不在本单**：

- 五个主 tab 页（E-5.1–E-5.5 已覆盖）；
- 后端 / 接口零改动；Web 侧对应页面（属 W-5.x）。

## 2. 层级形态（§9.3 / §9.4）

- 全部是**二级页**：全屏 push，顶栏走 §9.4 shell（52 高）。
- **需要专注完成的流程**（登录、完善资料、编辑资料、发帖）→ 独立二级页，**不用 sheet**。
- **单一字段编辑 / 筛选** → 底部 sheet（`EmberSheet`）。
- **破坏性确认**（注销账号、清空、解除配对）→ Dialog（图标 + 明确动词）。
- **轻量结果反馈** → `EmberToast`。

## 3. 用的组件（§8）

| 元素 | 用什么 | 取值来源 |
|---|---|---|
| 二级页骨架 | **新增 `core/ui/ember_page_scaffold.dart`**：§9.4 顶栏（52 / 返回 22 / 标题 17-w600 居中）+ 内容区（水平内边距 20）+ 可选底部主操作区 | §9.4 |
| 表单输入 | `EmberField`（含 `errorText`） | §8.2 输入框、§8.3 输入框行 |
| 主 / 次 / 文字 / 危险按钮 | `EmberButton`（四种变体） | §8.2 按钮、§8.3 按钮行 |
| 设置行 / 列表行 | **新增 `core/ui/ember_settings_tile.dart`**（标题 + 副标题 + 右侧 slot：值 / 开关 / 箭头） | §5.2 行高、§8.3 |
| 分组容器 | `EmberCard`（`radius.lg` + `elev.1`；深色 `border.divider`） | §8.2 卡片 |
| 标签选择 | `EmberChip`（E-5.2 已落地） | §8.3 Chip |
| 头像 / 照片格 | `EmberAvatar` + 自绘照片格（`radius.sm`） | §8.2 |
| 列表项（通知 / 收藏 / 点赞） | `EmberSettingsTile` 或 `EmberCard` + `EmberAvatar` | §8.2 |
| 空态 / 错误态 | `EmberEmpty` + unDraw 图 | §8.2 空态 |
| 骨架 | `EmberSkeleton` | §8.2 骨架 |
| Dialog | 新增 `core/ui/ember_dialog.dart`（图标 + 标题 + 说明 + 危险/常规两个按钮） | §9.3 |
| Toast | `EmberToast` | §8.3 Toast |

**新增三个 `core/ui` 组件**：`EmberPageScaffold`、`EmberSettingsTile`、`EmberDialog`（都按 §8.3 取值，
供后续页单与 Web 端对齐）。不新增 token。

## 4. 状态清单

| 元素 | 状态 | 口径 |
|---|---|---|
| `EmberPageScaffold` | default / 滚动 | 顶栏 `surface.page` 底 + 滚动时加 `border.divider` 下边线 |
| `EmberField` | default / focus / error / disabled | 见 §8.3 输入框四行；error **必须带文字** |
| 主按钮 | default / pressed / disabled / loading | 见 §8.3 按钮行 |
| `EmberSettingsTile` | default / pressed / disabled | pressed `surface.sunken`；disabled 文字 `text.tertiary` |
| 开关行 | on / off / disabled | `Switch` 选中 `brand.default`；关闭 `surface.sunken` |
| 列表项 | default / 未读 / 空 | 未读用 `EmberBadge` 或 `brand.default` 左侧竖线 |
| 照片格 | 有图 / 上传中 / 失败 / 空位 | 上传中骨架 + 进度；失败 `status.danger` 角标 + 点按重试 |
| Dialog | default / 危险 | 危险变体按钮描边 `status.danger`，确认后实底 |
| 深色 | — | 无阴影：卡片 `border.divider` + `surface.card` |
| 字号缩放 | 0.85–1.3 | 支持；`micro` 不跟随 |
| reduced motion | — | spring → 120ms 淡入 |
| 封禁 / 未登录 | — | 路由层拦截 |

## 5. 空态与错误态

| 场景 | 形态 |
|---|---|
| 黑名单空 | `EmberEmpty` + unDraw + 说明 |
| 收藏 / 我的动态空 | `EmberEmpty` + unDraw + 「去回声看看」主按钮 |
| 通知空 | `EmberEmpty` + unDraw + 说明 |
| 设备列表空 | `EmberEmpty`（极少见，仍给形态） |
| 表单校验失败 | 字段下方 `status.danger` 文字 + 字段描边转 `status.danger`（**不弹全局 Toast**） |
| 提交失败 | 表单底部 `status.danger` 提示条 + 保留已填内容 |
| 加载失败 | `EmberEmpty` 错误形态 + 「重试」 |

## 6. 本单验收

1. `cd app && flutter analyze` 零告警；`flutter test` 全绿；`bash scripts/verify.sh app` 全绿（末尾输出贴进 PR）。
2. **golden**（按组各 2 张明暗）：`EmberPageScaffold` 2、`EmberField` × {default, focus, error} × 2 = 6、
   `EmberSettingsTile` × 2、`EmberDialog` × {常规, 危险} × 2 = 4、四组代表页各 2 = 8。合计 **22 张**。
3. **Semantics**：返回按钮读「返回」；开关行读「标题，已开启/已关闭」；危险 Dialog 的按钮读明确动词
   （「注销账号」而不是「确定」）。
4. **手测（必须做）**：`emulator-5554` —— 登录、完善资料、改设置（含通知开关）、设备列表、黑名单、
   编辑资料（含换照片）、偏好、发帖、收藏、我的动态、通知页、注销账号 Dialog、深色、字号 1.3、移除动画。
5. **三条 grep 为空**：`0xFF` / `Curves.` / `Icons.`（范围 `app/lib/features/{auth,onboarding,settings,notifications,legal,profile,square}` 的二级页文件）。
6. **PR 开成 draft**，正文写「等待模拟器验收」；动了 `pubspec.yaml` 则必须人工合并。

## 7. 评审问题与拍板结果

| # | 问题 | 我的建议 | 备选 / 影响 |
|---|---|---|---|
| 1 | 本单是否拆成 4 单（A 准入 / B 设置 / C 表单 / D 列表）？ | **拆 4 单**：合计约二十个页面、四千余行，一单 diff 与手测都压不住 | 不拆则一次交付，但 PR 审不动、回滚粒度粗 |
| 2 | 是否新增三个公共组件（`EmberPageScaffold` / `EmberSettingsTile` / `EmberDialog`）？ | **新增**（二级页统一 shell 需要一处实现，否则每个页面各写一遍 52 顶栏） | 不加则 §9.4 只能靠复制粘贴 |
| 3 | 登录页是否保留「手机号 + 验证码」单页两步？ | **保留**（只换皮） | 改成两步页属交互改动，不在视觉迁移范围 |
| 4 | 编辑资料的照片管理是否保留现有交互（长按拖动排序）？ | **保留**（只换皮） | 重做拖拽排序属功能改动 |
| 5 | 注销账号 Dialog 是否改成必须输入文字确认？ | **不改**（保持二次确认 Dialog，动词明确即可） | 加强确认属安全口径变更，另开单 |
| 6 | 发帖页的「最多 9 张 / 单张 5MB」两条提示是否保留？ | **两条都保留**，但要把可达性写清（见下） | 删掉会丢防御性护栏；保留而不写清会让人以为「页面上真有 5MB 限制」 |

**拍板后**：结论回填本节下方，再开工单。

### 拍板结果（2026-11-24 主人确认）

| # | 结论 |
|---|---|
| 1 | **拆四单**：**E-5.6a 准入**（A 组）/ **E-5.6b 设置**（B 组）/ **E-5.6c 表单**（C 组）/ **E-5.6d 列表**（D 组），各自一单一栈、各自 PR、各自回滚 |
| 2 | **新增三个公共组件**（`EmberPageScaffold` / `EmberSettingsTile` / `EmberDialog`），由 **E-5.6a** 先落地，b/c/d 直接复用 |
| 3 | 登录页 **保留单页两步**（手机号 + 验证码），只换皮 |
| 4 | 编辑资料照片管理 **保留现有交互**（长按拖动排序），只换皮 |
| 5 | 注销账号 Dialog **不改**为输入文字确认（加强确认属安全口径变更，另开单） |

| 6 | 两条上限提示 **都保留**；可达性不同，已在 `post_compose_page.dart::_pick` 的 docstring 与用例里写明：**「最多 9 张」是真实用户路径**（已选 2 张再一次性多选 9 张 → 循环补到 9 张时命中）；**「单张 > 5MB」生产路径够不到**（`pickImagesFromGallery` 的 `maxWidth: 1080 / imageQuality: 85` 已把图降采样），保留为防御性护栏，由注入假 picker 的 widget 测试覆盖 |

> **§7 第 6 条的取证**（2026-11-28，`emulator-5554` + 本机 dev 后端）：往相册推入一张
> 6000×6000 / 43.2MB 的 jpg，在发帖页选中后**直接进九宫格、无任何提示** —— 证实 5MB 那道
> 在 UI 上够不到；而「已选 2 张 + 一次多选 9 张」会让 `_images.length` 在循环中触到 9 并弹提示。
> 两条现在都有 widget 测试钉住，不再是死码。

**子单排期**：E-5.6a → E-5.6b → E-5.6c → E-5.6d（a 先落地三个公共组件，后续三单只消费）。
每组各自的 golden 数量按 §6 第 2 条拆分：a 组 = 组件 12 + 代表页 2；b 组 = 4；c 组 = 4；d 组 = 2。

## 8. 与后续页单的接口

- 本单交付后 **App 侧逐页迁移全部完成**，可评估把 spec 与 plan 归档（`docs/superpowers/archive/`）。
- `EmberPageScaffold` / `EmberSettingsTile` / `EmberDialog` 三个组件同时是 Web 线（W-5.x）的对照物：
  Web 端做二级页时应保持同一套顶栏高度、行高与 Dialog 口径。
