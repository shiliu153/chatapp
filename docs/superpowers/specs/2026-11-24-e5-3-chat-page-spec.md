# E-5.3 页面规格：对话（会话列表 + 聊天页）—— 气泡、输入栏、时间条

> **立项**：2026-11-24 · **状态**：page spec，**待主人评审**（问题见 §7）
> **上游**：[Ember 规范](../specs/2026-11-23-ui-redesign-ember-design.md)（v1.0）§5 / §7 / §8.2 / §8.3 / §9.3 / §9.4 / §18
> **实施计划**：[E-5 逐页迁移](../plans/2026-11-23-ui-redesign-ember.md) 第 3 单（App 线）
> **模板**：[E-5.1 底栏 shell](2026-11-23-e5-1-shell-nav-page-spec.md) / [E-5.2 遇见页](2026-11-24-e5-2-discovery-page-spec.md)
> **栈**：`app`（单一栈；不碰 `web`、不碰 `chatapp/**`、不碰 `imserver/**`）

---

## 1. 目标

把「对话」tab（会话列表）与聊天页从心跳口径迁到 Ember。业务逻辑零改动 ——
`chat_controller` / `conversations_controller` / `im/` 传输层一行不动，本单只换视觉与动效。

用户可见的变化：

| # | 变化 | 从 → 到 |
|---|---|---|
| 1 | **聊天页顶栏** | 高 62 → **52**（§9.4 二级页 shell：返回 22 + 标题 17/w600 居中） |
| 2 | **气泡** | 圆角 18 → **16**（`radius.md`）；自己 `brand.default` + `brand.on`，对方 `surface.card` + `text.primary`（§8.3 气泡行） |
| 3 | **系统通知官方标** | 蓝色渐变头像 → **`status.info` 单色**（§18.2 明确删除「系统蓝」） |
| 4 | **未读角标** | 自绘红点 → **`EmberBadge`**（≥100 显示「99+」） |
| 5 | **输入栏** | 自绘圆角容器 → **`EmberField`**（`surface.card` + 1px `border.divider` + `radius.md` + 高 52） |
| 6 | **图标** | Material `*_rounded` → **Phosphor Regular / Fill**（§6） |
| 7 | **动效** | duration + curve → **`spring.*`**：聊天页 push 右滑入（`spring.standard`）、面板上浮（`spring.gentle`）、按压 `scale .97`（`spring.fast`） |
| 8 | **头像** | `AppAvatar` → **`EmberAvatar`**（在线点 `status.success` 呼吸、新配对 `emberGlow` 环） |
| 9 | **时间条** | 12 / `text.tertiary` 居中、上下 12、间隔 >5 分钟插入 —— **口径不变**，只换 token 名 |

**明确不在本单**：

- 底栏（E-5.1 已交付）；
- 配对成功全屏编排（E-5.2 已含）；
- IM 协议、已读回执、typing、引用快照的业务逻辑（只换皮）；
- Web 侧聊天（属 W-5.4）；
- 语音录制 / 转码链路（只换录制浮层的视觉）。

## 2. 层级形态（§9.3 / §9.4）

- **会话列表**是 tab 根页面，底栏常驻（E-5.1）。
- **聊天页**是二级页：全屏 push、右滑入；顶栏走 §9.4 统一 shell（52 高）。
- **表情面板 / 更多面板**：底部 sheet（轻量选择），用 `EmberSheet`。
- **图片查看**：全屏 + Hero 转场（沉浸内容）。
- **删除会话 / 解除配对**：Dialog（必须带图标 + 明确动词，不用「确定/取消」）。

## 3. 用的组件（§8）

| 元素 | 用什么 | 取值来源 |
|---|---|---|
| 聊天页顶栏 | §9.4 shell：返回 22 Phosphor `caret-left` + 标题 17/w600 居中；右侧更多 | §9.4 |
| 顶栏头像 | `EmberAvatar` 32（Hero 转场到资料页，**Hero 留给 E-5.4**，本单只保留占位） | §8.2 头像 |
| 会话行 | 自绘行：头像 48 + 昵称 `subtitle` 17/w600 + 摘要 `caption` 13 `text.secondary` + 时间 `caption` 13 `text.tertiary`；行高 68–76 | §5.2 列表行高 |
| 未读角标 | `EmberBadge`（`brand.default` 底 + `brand.on` 字 11/w700） | §8.3 角标行 |
| 免打扰灰点 | `text.tertiary` 直径 8 实心圆（保留现有形态） | §5.3 小场景点 |
| 系统通知行 | 置顶行 + `status.info` 单色官方标 + `EmberBadge` | §18.2 |
| 最近联系人横滑 | `EmberAvatar` 48 + `micro` 11 名字；无头像时首字 + 柔色底 | §8.2 头像 |
| 分组标题（置顶） | `caption` 13/w600 `text.secondary`，贴左不用卡片底 | 保留现状 |
| 气泡 | 改造现有气泡组件：自己 `brand.default` + `brand.on`；对方 `surface.card` + `text.primary`；`radius.md`，靠头像侧上角 6；最大宽 72%；内边距 12/16 | §8.3 气泡行 |
| 气泡（发送中 / 失败） | 发送中：右下角 12 转圈、不显示时间；失败：左侧 `status.danger` 感叹号 + 点按重发（**不静默丢弃**） | §8.3 气泡行 |
| 语音气泡 | 保留现有形态（波形 / 时长 / 播放态），只换 token 与图标 | 规范未覆盖 → 假定保留 |
| 时间条 | `caption` 12 `text.tertiary` 居中，上下边距 12 | §8.3 时间条 |
| 引用条 | `surface.sunken` + `radius.sm` + 左侧 2px `brand.default` 竖线 | §8.3 Chip / 次级容器 |
| 输入栏 | `EmberField`（高 52）+ 图标按钮 44×44 热区（语音 / 表情 / 更多 / 发送） | §8.2 输入框、§8.4 触控 |
| 多选模式顶栏 / 操作条 | 自绘，高度与顶栏对齐（52），不跳版 | 保留现状，换 token |
| 表情面板 / 更多面板 | `EmberSheet` | §8.3 Sheet |
| 空态 / 错误态 | `EmberEmpty` + unDraw 图（同 E-5.2 口径） | §8.2 空态 |
| 骨架 | `EmberSkeleton` 按气泡形状 | §8.2 骨架 |
| Toast | `EmberToast` | §8.3 Toast |

**不新增 token、不新增 `core/ui` 组件**（E-5.2 的 `EmberChip` / `EmberActionButton` 已够用）。

## 4. 状态清单

| 元素 | 状态 | 口径 |
|---|---|---|
| 会话行 | default / pressed | 底 `surface.page`；pressed `surface.sunken`（列表行不用卡片阴影） |
| 会话行 | 未读 | 昵称 w700 + `EmberBadge`；已读 = 常规字重 |
| 会话行 | 免打扰 | 灰点直径 8 `text.tertiary` + 未读显示为灰点而非角标 |
| 会话行 | 草稿 | 摘要前缀「[草稿] 」，`text.tertiary` |
| 会话行 | 多选选中 | 行底 `brand.default` @8% + 左侧 2px `brand.default` |
| 气泡 | 自己 / 对方 | 见 §3；对方气泡圆角镜像 |
| 气泡 | 发送中 | 气泡保持 + 右下角 12 转圈，不显示时间 |
| 气泡 | 发送失败 | 左侧 `status.danger` 感叹号，点按重发 |
| 气泡 | 已读 | 自己最后一条下方 `micro` 11 `text.tertiary`「已读」（保留现有口径） |
| 气泡 | 引用 | 气泡内顶部引用块（`surface.sunken` 底 + 左竖线），点按滚到原消息 |
| 输入栏 | default / focus | `EmberField` 口径：聚焦 2px `brand.default` + 2px 外扩 |
| 输入栏 | disabled（已解除配对） | `surface.sunken` 底 + `text.tertiary`，整栏禁点（保留现状） |
| 输入栏 | sending | 发送按钮转圈，禁连点 |
| 表情 / 更多面板 | default | `EmberSheet`：上圆角 24 + 拖把 36×4 |
| 深色 | — | 不用阴影：气泡与面板靠 `surface.card` + `border.divider` 分层 |
| 字号缩放 | 0.85–1.3 | 支持；`micro`（时间、标签）不跟随 |
| reduced motion | — | 全部 spring → 120ms 线性淡入，取消位移与缩放 |
| 封禁 / 已解除配对 | — | 沿用现有拦截（输入禁用 / 路由层 BannedPage） |

## 5. 空态与错误态

| 场景 | 形态 |
|---|---|
| 会话列表空 | `EmberEmpty`：unDraw 图 + 「还没有对话」+ 说明 + 主按钮「去遇见」（切到发现 tab） |
| 聊天历史加载中 | `EmberSkeleton` 气泡形（左右交替） |
| 聊天加载失败 | `EmberEmpty` 错误形态：unDraw 图 + 说明 + 主按钮「重试」 |
| 历史为空 | 居中提示「打个招呼吧」`caption` `text.tertiary`（不占满屏） |
| 已解除配对 | 输入栏禁用 + 顶部提示条「你们已解除配对」，历史仍可读 |
| 发送失败 | 气泡左侧感叹号（**不弹全局错误**，就地重发） |

## 6. 本单验收

1. `cd app && flutter analyze` 零告警；`flutter test` 全绿；`bash scripts/verify.sh app` 全绿（末尾输出贴进 PR）。
2. **golden**：会话行 × {明, 暗} × {default, 未读, 草稿} = 6；气泡 × {明, 暗} × {自己, 对方, 发送中, 失败} = 8；
   空态 × {明, 暗} = 2。合计 **16 张**。
3. **Semantics 断言**：会话行读作「昵称，最后一条，时间，N 条未读」；气泡读作「我/对方，内容，时间，发送状态」（§8.4 读屏口径）。
4. **手测（必须做）**：`emulator-5554` 上 —— 进会话、发文本、发图片、发语音、引用回复、多选删除、
   typing 提示、已读回执、深色、系统「移除动画」、字号 1.3。
5. **三条 grep 为空**：`grep -rn "0xFF" app/lib/features/chat`、`grep -rn "Curves\." app/lib/features/chat`、
   `grep -rn "Icons\." app/lib/features/chat`。
6. **PR 开成 draft**，正文写「等待模拟器验收」；动了 `pubspec.yaml` 则必须人工合并。

## 7. 评审问题与拍板结果

| # | 问题 | 我的建议 | 备选 / 影响 |
|---|---|---|---|
| 1 | 本单是否拆成两单（会话列表 / 聊天页）？ | **拆两单**：聊天页 `chat_page.dart` 一千三百余行 + 气泡组件四百余行，一单 diff 太大、模拟器手测也压不住 | 不拆则一单交付，但 PR 审不动、回滚粒度粗 |
| 2 | 聊天页顶栏 62 → 52（§9.4）？ | **改 52** | 不改则与「二级页统一 shell」不一致 |
| 3 | 气泡圆角 18 → 16？ | **改 16**（§18.3 已明确是视觉变化） | 保留 18 需先改规范 |
| 4 | 最近联系人横滑条保留？ | **保留**（只换皮） | 删掉会丢功能 |
| 5 | 表情面板 / 更多面板本单迁？ | **本单迁**（它们在聊天页内，拆出去反而割裂） | 留到后面会让聊天页出现两种面板风格 |
| 6 | 系统通知官方标用 `status.info` 单色？ | **是**（§18.2 已删除「系统蓝」） | 保留蓝色需先改规范 |

**拍板后**：结论回填本节下方，再开工单（实现走 issue）。

### 拍板结果（待填）

| # | 结论 |
|---|---|
| — | 待主人评审 |

## 8. 与后续页单的接口

- **E-5.4（我 + 资料页）**：顶栏头像的 Hero 转场与气泡里的头像点击都落到资料页，Hero 由 E-5.4 落地。
- **E-5.6（二级页）**：聊天页顶栏是本单先落地 §9.4 shell 的样板，后续二级页照它做。
- **多选模式**（顶栏 + 底部操作条）属聊天页内，不进公共组件。
