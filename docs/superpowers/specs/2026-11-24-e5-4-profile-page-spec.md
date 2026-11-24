# E-5.4 页面规格：我（我的主页）+ 资料页（他人资料）

> **立项**：2026-11-24 · **状态**：page spec，**待主人评审**（问题见 §7）
> **上游**：[Ember 规范](../specs/2026-11-23-ui-redesign-ember-design.md)（v1.0）§5 / §6 / §7 / §8.2 / §8.3 / §9.3 / §9.4
> **实施计划**：[E-5 逐页迁移](../plans/2026-11-23-ui-redesign-ember.md) 第 4 单（App 线）
> **模板**：[E-5.2 遇见页](2026-11-24-e5-2-discovery-page-spec.md) / [E-5.3 对话页](2026-11-24-e5-3-chat-page-spec.md)
> **栈**：`app`

---

## 1. 目标

把「我」tab（我的主页）与**他人资料页**从心跳口径迁到 Ember，并**落地 Hero 转场**
（E-5.2 已约定：发现页卡 → 资料页、对话页头像 → 资料页的 Hero 留给本单）。

业务逻辑零改动：`profile_controller` / `profile_repository` / 语音介绍上传链路一行不动。

用户可见的变化：

| # | 变化 | 从 → 到 |
|---|---|---|
| 1 | **照片头图** | 全出血照片 + 底部 `overlay.scrim` 渐变叠字（`title` 24 Fraunces 白字） |
| 2 | **头像** | `AppAvatar` → **`EmberAvatar`** 96（在线点 `status.success` 呼吸、新配对 `emberGlow` 环） |
| 3 | **Hero 转场** | 无 → 发现页卡照片 / 对话页头像 **Hero 进资料页**（`spring.standard`） |
| 4 | **信息行** | 自绘行 → 行高 68–76、`subtitle` 17/w600 标签 + `body` 15 值、分隔线 `border.divider` |
| 5 | **标签** | 自绘 chip → `EmberChip`（E-5.2 已落地） |
| 6 | **顶栏** | 二级页统一 shell **52**（§9.4：返回 22 + 标题 17/w600 居中；头图场景可透明化） |
| 7 | **图标** | Material `*_rounded` → **Phosphor**（§6） |
| 8 | **动效** | curve → **`spring.*`**；按压 `scale .97` |
| 9 | **语音介绍卡** | 保留形态（波形 / 时长 / 播放态），换 token 与图标 |

**明确不在本单**：

- 编辑资料页（`profile_edit_page.dart`）与偏好设置（`preference_page.dart`）—— 属 **E-5.6 二级页**；
- 「喜欢我的人 / 谁看过我」列表页（属 E-5.5 之后的小单，或随本单只换入口）；
- 资料完善向导（`onboarding`）—— 属 E-5.6；
- 后端 / 接口零改动。

## 2. 层级形态（§9.3 / §9.4）

- **我**是 tab 根页面（底栏常驻）。
- **他人资料页**是二级页：全屏 push，顶栏走 §9.4 shell；**头图滚动时可透明化**（§9.4 唯一例外）。
- 照片查看：全屏 + Hero（沉浸内容）。
- 解除配对 / 举报：Dialog（带图标 + 明确动词）。

## 3. 用的组件（§8）

| 元素 | 用什么 | 取值来源 |
|---|---|---|
| 顶栏 | §9.4 shell（52 高，返回 22 Phosphor `caret-left`，标题 17/w600 居中） | §9.4 |
| 照片头图 | 全出血 `Image` + `overlay.scrim` 底部渐变 + 昵称/年龄 `title` 24 白字 | §8.2 卡片、§3.3 overlay |
| 头像 | `EmberAvatar` 96（在线点 / 新配对光晕） | §8.2 头像 |
| 信息分组 | `EmberCard`（`surface.card` + `radius.lg` + `elev.1`；深色 `border.divider`） | §8.2 卡片 |
| 信息行 | 自绘行：标签 `subtitle` 17/w600 `text.primary`、值 `body` 15 `text.secondary`；行高 68–76 | §5.2 |
| 标签 | `EmberChip`（未选中 `surface.sunken` + `text.secondary`） | §8.3 Chip |
| 语音介绍卡 | 保留现有卡形，换 `EmberCard` + Phosphor `play/pause` | 规范未覆盖 → 假定保留 |
| 主操作（编辑资料 / 打招呼） | `EmberButton`（主按钮 52 高 + `emberGlow`） | §8.2 主按钮 |
| 空态 / 错误态 | `EmberEmpty` + unDraw 图（同 E-5.2 口径） | §8.2 空态 |
| 骨架 | `EmberSkeleton`（头图 + 信息行形状） | §8.2 骨架 |
| Toast | `EmberToast` | §8.3 Toast |

**不新增 token**；组件全部复用 `core/ui`（E-5.2 的 `EmberChip` / `EmberActionButton` 已够）。

## 4. 状态清单

| 元素 | 状态 | 口径 |
|---|---|---|
| 照片头图 | default / 无照片 | 无照片用 `surface.sunken` + Phosphor `user` 64 `text.tertiary`（内容占位） |
| 照片头图 | 滚动 | 顶栏从透明渐变到 `surface.page` + `border.divider` 底边（§9.4） |
| 头像 | default / 在线 / 新配对 | 在线 `status.success` 点 11 + 呼吸；新配对 `emberGlow` 环 2.5px |
| 信息行 | default / pressed（可点行） | pressed `surface.sunken` |
| 标签 | default | `EmberChip` 未选中态；超过一行 `Wrap` 换行 |
| 语音介绍 | 未播放 / 播放中 / 加载中 | 播放中波形高亮 `brand.default`；加载中骨架 |
| 主按钮 | default / pressed / loading | 见 §8.2 |
| 深色 | — | 无阴影：卡片 `border.divider` 1px + `surface.card` |
| 字号缩放 | 0.85–1.3 | 支持；`micro` 不跟随 |
| reduced motion | — | spring → 120ms 线性淡入；Hero 退化为淡入 |
| 封禁 / 未登录 | — | 路由层拦截，本单不改 |

## 5. 空态与错误态

| 场景 | 形态 |
|---|---|
| 资料加载失败 | `EmberEmpty` 错误形态 + 「重试」 |
| 资料加载中 | `EmberSkeleton` |
| 他人资料不存在 / 已注销 | `EmberEmpty` + 返回 |
| 资料不完整（我） | 顶部提示条 + 主按钮「去完善」（跳 onboarding） |
| 无照片 | 头图占位（见 §4），不整页空态 |

## 6. 本单验收

1. `cd app && flutter analyze` 零告警；`flutter test` 全绿；`bash scripts/verify.sh app` 全绿（末尾输出贴进 PR）。
2. **golden**：我的 × {明, 暗} = 2；他人资料 × {明, 暗} = 2；头图占位 × {明, 暗} = 2；信息行 × {明, 暗} = 2。
   合计 **8 张**。
3. **Semantics**：头像读「昵称，在线」；信息行读「标签，值」；语音介绍读「语音介绍，N 秒」。
4. **手测（必须做）**：`emulator-5554` —— 我的页、他人资料页、Hero 转场（从发现页卡与对话页头像各一次）、
   语音介绍播放、深色、系统「移除动画」（Hero 退化为淡入）、字号 1.3。
5. **三条 grep 为空**：`0xFF` / `Curves.` / `Icons.`（范围 `app/lib/features/profile`）。
6. **PR 开成 draft**，正文写「等待模拟器验收」。

## 7. 评审问题与拍板结果

| # | 问题 | 我的建议 | 备选 / 影响 |
|---|---|---|---|
| 1 | Hero 转场本单落地（发现页卡 + 对话页头像两条入口）？ | **本单落地**（E-5.2 已把 Hero 推给本单） | 不做则两处点击仍是硬切，且 E-5.2/5.3 的 Hero 占位会一直悬着 |
| 2 | 编辑资料 / 偏好设置留在 E-5.6？ | **留在 E-5.6**（本单只做展示页） | 并进来会让本单跨到表单与校验 |
| 3 | 他人资料页的操作区（打招呼 / 解除配对 / 举报）保留？ | **保留**，只换 `EmberButton` 与 Dialog 口径 | 删掉会丢功能 |
| 4 | 语音介绍卡保留？ | **保留**（换皮） | 删掉会丢已上线功能 |
| 5 | 「喜欢我的人 / 谁看过我」两个列表页本单一起迁？ | **不一起迁**，只换发现页入口图标（E-5.2 已做） | 一起迁会让本单再大一圈 |

**拍板后**：结论回填本节下方，再开工单。

### 拍板结果（待填）

| # | 结论 |
|---|---|
| — | 待主人评审 |

## 8. 与后续页单的接口

- **E-5.2 / E-5.3**：两处 Hero 占位（发现页卡、对话页头像）在本单闭环。
- **E-5.6**：编辑资料 / 偏好设置沿用本单的信息行与表单口径。
