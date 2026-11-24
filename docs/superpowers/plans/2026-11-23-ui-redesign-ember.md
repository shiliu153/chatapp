# 实施计划：「余烬 Ember」接线与页面迁移

> **Spec**：[2026-11-23-ui-redesign-ember-design.md](../specs/2026-11-23-ui-redesign-ember-design.md)（v0.1，**2026-11-23 评审通过**）
> **Goal**：把已落地的 token 链路（E-1）接到两端，删掉双份手写，再按页迁移。
> **Architecture**：`design/tokens/*.json` → `scripts/design_tokens.py` → Dart / CSS 生成物；
> 页面只消费生成物与组件层，不出现裸值。
> **Global Constraints**：一单一条栈（跨栈回报拆单）；生成物禁手改；推之前该栈门禁必须绿；
> 不碰 `deploy/**`、`.github/**`、版本号、`flutter/`。
> **验收命令**：`scripts/verify.sh contract`（每条都跑）/ `scripts/verify.sh app` / `scripts/verify.sh web`

## 0. 已完成（E-1，2026-11-23）

- [x] `design/tokens/{primitive.color,semantic.light,semantic.dark,scale}.json`（DTCG）
- [x] `scripts/design_tokens.py`（`--write` / `--check`，纯标准库，字节级比对）
- [x] `scripts/design_contrast.py`（阈值从 spec §3.4 解析，双模式 19 对配对）
- [x] `scripts/design_spec_sync.py`（§3.2 / §3.3 的表 ↔ token **双向**比对，含透明度）
- [x] `design/contrast-pairs.toml`（配对映射）
- [x] 六道门禁注册（`contract-design-tokens` / `-tokens-selftest` / `-contrast` / `-contrast-selftest` /
      `-spec-sync` / `-spec-sync-selftest`）
- [x] 生成物已提交：`app/lib/core/theme/tokens.g.dart`、`web/src/styles/tokens.generated.css`、
      `design/tokens.resolved.json`
- [x] `scripts/verify.sh contract` 36 / 36 通过

---

## E-2 · `app` 栈：主题层换生成物 + 组件层重建 —— ✅ 已交付（2026-11-23，PR #470）

> **工单**：[#465](https://github.com/shiliu153/chatapp/issues/465)（会话内联交付后关闭；
> 原计划派给 worker，改为本机做完 —— 规范当时尚未评审，不宜派单）。

**目标**：`app/lib/core/theme/` 不再有手写色值；页面通过 `AppTokens` 取色，通过
`core/ui` 取组件。

### Task E-2.1 主题门面（不改任何页面）

- [x] 新增 `app/lib/core/theme/app_theme.dart`：把 `tokens.g.dart` 的 light / dark 两组
      常量组装成 `ThemeData`（`colorScheme` 手工构造，**不要用 `ColorScheme.fromSeed`** ——
      种子算法会生成规范里没有的颜色）。
- [x] 新增 `app/lib/core/theme/ember_theme_context.dart` + `theme_controller.dart`：
      按明暗模式取 token 与 `ThemeMode`。
- [x] `MaterialApp` 同时挂 `theme` 与 `darkTheme`，`themeMode` 走上面那个。

### Task E-2.2 组件层

- [x] 新增 `app/lib/core/ui/`，按 spec §8 实现：`EmberButton`（主/次/文字/危险 + 五态）、
      `EmberField`、`EmberCard`、`EmberAvatar`（在线点 / 新配对光晕）、`EmberBadge`、
      `EmberSheet`、`EmberToast`、`EmberEmpty`、`EmberSkeleton`，外加 `EmberPressable` /
      `EmberGlow` / `EmberComponentSizes` 等基件。
- [x] 每个组件的每种状态都有 golden 或 Semantics 断言（`app/test/core/ui/`）。

### Task E-2.3 删除手写 token

- [x] 删除 `app/lib/core/theme/app_colors.dart` 等心跳期色值常量文件（保留 `tokens.g.dart`）。
- [x] `grep -rn "0xFF" app/lib --include=*.dart` 除 `tokens.g.dart` 外为空
      （仅剩 `im/upload_idempotency.dart` 的位掩码，非色值）。

> **注意**：E-2 不迁移任何页面视觉 —— 那是 E-5 的事。本单只换了底座，页面此刻处于
> 「旧布局 + 新色值」的中间态。

---

## E-3 · `web` 栈：PrimeVue unstyled 接线 —— ✅ 已交付（2026-11-23，PR #468）

> **工单**：[#466](https://github.com/shiliu153/chatapp/issues/466)（会话内联交付后关闭，原因同 E-2）。

### Task E-3.1 样式入口

- [x] `web/src/main.ts` 引入 `tokens.generated.css`（`ember-compat.css` 承接旧变量名）。
- [x] 删除 `web/src/styles/tokens.css`；`web/tests/unit/tokens.spec.ts` 改为「生成物存在 +
      带 `--color-brand-default` + 明暗键集一致」的轻量断言。

### Task E-3.2 PrimeVue

- [x] 装 `primevue`（unstyled 模式）并在入口 `app.use(PrimeVue, { unstyled: true })`。
- [x] `web/src/styles/primevue-pass-through.ts`：把组件段的 `pt` 映射到
      `tokens.generated.css` 的 CSS 变量（**只引用变量，不写值**）。
- [x] Tailwind v4 `@theme` 转发成语义工具类。

### Task E-3.3 无障碍门禁

- [x] `web` 加 `@axe-core/playwright` 冒烟：主流程页面零 critical。
      **已落地（2026-11-23，随 [#468](https://github.com/shiliu153/chatapp/pull/468)）** ——
      `web/tests/e2e/support/a11y.ts` 提供 `expectNoCriticalA11y`，`ci-smoke.spec.ts` 在
      登录 / 完善资料 / 发现 / 广场四页各扫一次；只卡 `critical` 档，`serious` 里的配色对比度
      归 `scripts/design_contrast.py` 管（避免两份阈值）。

---

## E-4 · `docs` 栈：转正与归档 —— ✅ 已交付（2026-11-23）

- [x] spec 头部 `v0.1 评审通过` → `v1.0 生效`（并补版本变更记录）。
- [x] 旧规范 `git mv docs/superpowers/specs/2026-09-15-ui-design-language-design.md docs/superpowers/archive/specs/`（**文件名与内容不改**，只把顶部作废横幅改成「已归档」）。
- [x] 同一次改动内改引用：`CLAUDE.md` 的 UI 规则段（双轨 → 单轨）、`AGENTS.md` 的 App 行与 §二 token 条目、
      `docs/standards/sources-of-truth.md` §2.5、`docs/pitfalls/README.md` 与 `frontend.md`、`docs/superpowers/README.md`，
      以及三份 archive 文档里指向旧路径的相对链接。
- [x] `python scripts/docs_index.py --write` + `python scripts/facts.py --write`。
- 验收：`scripts/verify.sh contract` 39 / 39 绿。

**前置已满足**：spec §12 的三项 v1.0 生效条件 —— token 链路落地 ✅ + 门禁全绿 ✅ +
首个页面按新规范交付并通过验收 ✅（E-5.1 底栏 shell，[#476](https://github.com/shiliu153/chatapp/pull/476)，2026-11-23 模拟器手测通过）。

---

## E-5+ · 逐页迁移（每页一单，`app` 或 `web`）

两条线分开排：**App 线（E-5.x）与 Web 线（W-5.x）各自一单一栈**，互不阻塞。

### App 线（`app` 栈）

| 单 | 状态 |
|---|---|
| E-5.1 底栏 shell + 四个 Tab 骨架 | ✅ [#476](https://github.com/shiliu153/chatapp/pull/476)（2026-11-23） |
| E-5.2 遇见（发现）页 | ✅ [#495](https://github.com/shiliu153/chatapp/pull/495)（2026-11-24） |
| E-5.3 对话页（会话列表 + 聊天页） | ✅ [#501](https://github.com/shiliu153/chatapp/pull/501)（2026-11-24） |
| E-5.4 我的 + 资料页（含 Hero 三条入口） | ✅ [#510](https://github.com/shiliu153/chatapp/pull/510)（2026-11-24） |
| E-5.5 回声（广场）页 + 动态详情 | ✅ [#511](https://github.com/shiliu153/chatapp/pull/511)（2026-11-24） |
| E-5.6 二级页（拆 a/b/c/d 四单） | 🔄 a 准入进行中（[#512](https://github.com/shiliu153/chatapp/pull/512)）；b 设置 [#507](https://github.com/shiliu153/chatapp/issues/507) / c 表单 [#508](https://github.com/shiliu153/chatapp/issues/508) / d 列表 [#509](https://github.com/shiliu153/chatapp/issues/509) 排队 |

顺序按「用户停留时长 × 改动面」：

1. ~~底栏 shell + 四个 Tab 骨架~~ ✅
2. ~~发现页（滑卡、操作钮、Hero 到资料页）~~ ✅
3. ~~消息页 + 聊天页（气泡、输入栏、时间条）~~ ✅
4. ~~我的 + 资料页~~ ✅
5. ~~回声（广场）页~~ ✅
6. 二级页（登录 / 引导 / 设置 / 编辑资料）—— 拆四单，进行中

### Web 线（`web` 栈）

**现状**：E-3 只接底座 —— `tokens.generated.css` 已进样式入口、PrimeVue 走 unstyled + passThrough、
`ember-compat.css` 承接旧变量名；**页面视觉仍是「旧布局 + 新色值」**。裸 hex 只剩
`features/discovery/CandidateCard.vue` 与 `DailyStrip.vue` 各一处；axe 门禁已随 E-3.3 落地。

顺序同样按「停留时长 × 改动面」，每单一页 spec 一单工单：

1. **W-5.1 登录 + 引导**：`auth/LoginPage`、`onboarding/OnboardingPage`、`legal/LegalGate`、`app/ForceUpdate`
2. **W-5.2 发现**：`discovery/DiscoveryPage`、`CandidateCard`、`SwipeDeck`、`MatchMoment`、`DailyStrip`、
   `LikesPage`、`VisitsPage`
3. **W-5.3 回声（广场）**：`square/` 的列表、详情、评论
4. **W-5.4 对话**：`chat/ChatsPage`、`ChatPage`、气泡 / 输入栏 / 搜索 / 弹窗
5. **W-5.5 我**：`profile/MyProfilePage`、`settings/`、编辑资料
6. **W-5.6 二级与公共**：`notifications/`、`stats/`、设备管理、举报弹窗、`dev/ComponentsPage` 对齐新组件

每单固定验收：`scripts/verify.sh app`（或 `web`）绿 + 该页 golden + 模拟器手测截图
（App）/ 真浏览器截图（Web）。**不得声称 ready**：App UI 可见改动的 PR 一律 draft，等主人验收。

开工前先按 spec §11.3 写一页纸 page spec（目标 / 层级形态 / 用的组件 / 状态清单 / 空态与错误态），
评审通过再开工单 —— 否则第一单就没有「新规范下的验收基线」。

---

## 执行记录

- 2026-11-23：E-1 按「流程自身的自证手段」例外**在会话内联交付**（worker 没有门禁就无从自证）。
  六道门禁进 `scripts/gates.toml`，`scripts/verify.sh contract` 38 / 38 通过。
- 2026-11-23：E-2 / E-3 开成工单（[#465](https://github.com/shiliu153/chatapp/issues/465) /
  [#466](https://github.com/shiliu153/chatapp/issues/466)）后**改为会话内联交付**（规范当时仍是草案，
  派给 worker 等于按未定稿施工），分别落在 PR [#470](https://github.com/shiliu153/chatapp/pull/470) /
  [#468](https://github.com/shiliu153/chatapp/pull/468)，两条工单随之关闭。
- 2026-11-23：**规范评审通过**（主人审批 v0.1）→ 实施解封：本计划、spec §12 / §14 / §16、
  `docs/superpowers/README.md`、`docs/standards/sources-of-truth.md` §2.5、`CLAUDE.md` 的
  token 规矩段落同步改为「评审通过 / 实施期」。E-4 仍卡在「首个页面验收」，E-5 可开工。
- ~~遗留提醒：字体资产仍是 Space Grotesk 双份（`app/assets/fonts/*` ↔ `web/public/fonts/*`），
  Ember §4 的 Fraunces 标题字体没有落地~~ —— **已解决（2026-11-23 字体单）**：两端换成
  `Fraunces-Variable.ttf`（可变字体，字重走 wght 轴），Space Grotesk 三份静态字重删除，
  `web/tests/unit/fonts.spec.ts` 仍双向比对（现在还会断言旧字体确实没了）。踩坑见 spec §4.1。
- 2026-11-24：**E-5.2 遇见页 page spec 已拍板并合并**（[#486](https://github.com/shiliu153/chatapp/pull/486)），
  实现单 [#487](https://github.com/shiliu153/chatapp/issues/487) 已派给 worker。同一次改动把
  **Web 线（W-5.1–W-5.6）单独排期**（E-3 只接底座，页面仍是「旧布局 + 新色值」），并把 E-3.3 的
  过期勾回填 —— axe 冒烟其实随 [#468](https://github.com/shiliu153/chatapp/pull/468) 已落地
  （`web/tests/e2e/support/a11y.ts`，登录 / 完善资料 / 发现 / 广场四页零 critical），此前标着「未做」。
- 2026-11-24：**App 线五单连交付** —— E-5.2 [#495](https://github.com/shiliu153/chatapp/pull/495)、
  E-5.3 [#501](https://github.com/shiliu153/chatapp/pull/501)、E-5.4 [#510](https://github.com/shiliu153/chatapp/pull/510)、
  E-5.5 [#511](https://github.com/shiliu153/chatapp/pull/511)（E-5.1 已于 11-23 交付）。每单都过
  `verify.sh app` + golden + Semantics + `app-ui`（真模拟器），由本机会话逐单审核 diff 后合并。
  过程中沉淀的三条口径写在这里，后续页单照做：
  ① **临时产物不许进提交**（`tmp_*` / `scratch_*`，E-5.2 与 E-5.3 各出现过一次，靠审核抓）；
  ② **组件级 golden 里带 `Image.asset` 的，`pumpScene` 必须先 `precacheImage`**，否则截到的是「图还没出来」那一帧
     （E-5.5 的空态 golden 就这么漏了插画，返工一次）；
  ③ **跨页 Hero 的骨架也要带同名 tag** —— Hero 只在 push 后下一帧扫一次，资料页首帧是 loading 骨架，
     骨架不带 tag 就「有 tag 但不飞」（E-5.4 发现并写了用例钉住）。
- 2026-11-24：E-5.6 拆四单后，**a 准入**（[#512](https://github.com/shiliu153/chatapp/pull/512)）落地了三个公共组件
  `EmberPageScaffold` / `EmberSettingsTile` / `EmberDialog`，b/c/d 直接复用。同单还修了
  `EmberField` 一个真实缺陷：聚焦时才包一层 `Container` 会让内层 `TextInputConnection` 重建、
  同页第二个字段 `enterText` 静默丢字（真机丢 IME 组字）。另发现 `EmberButton` 读屏标签念两遍
  （`EmberPressable` 的 Semantics 与内层 `Text` 各贡献一份），已开组件单
  [#513](https://github.com/shiliu153/chatapp/issues/513) 单独修。
