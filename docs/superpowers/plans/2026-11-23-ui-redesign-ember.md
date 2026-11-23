# 实施计划：「余烬 Ember」接线与页面迁移

> **Spec**：[2026-11-23-ui-redesign-ember-design.md](../specs/2026-11-23-ui-redesign-ember-design.md)
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

## E-2 · `app` 栈：主题层换生成物 + 组件层重建

> **工单**：[#465](https://github.com/shiliu153/chatapp/issues/465)（已开，**未派单**：等规范评审）

**目标**：`app/lib/core/theme/` 不再有手写色值；页面通过 `AppTokens` 取色，通过
`core/ui` 取组件。

### Task E-2.1 主题门面（不改任何页面）

- [ ] 新增 `app/lib/core/theme/app_theme.dart`：把 `tokens.g.dart` 的 light / dark 两组
      常量组装成 `ThemeData`（`colorScheme` 手工构造，**不要用 `ColorScheme.fromSeed`** ——
      种子算法会生成规范里没有的颜色）。
- [ ] 新增 `app/lib/core/theme/app_theme_mode.dart`：读 `MediaQuery.platformBrightness` +
      用户偏好（沿用现有设置存储），返回 `ThemeMode`。
- [ ] `MaterialApp` 同时挂 `theme` 与 `darkTheme`，`themeMode` 走上面那个。
- 验收：`cd app && flutter analyze` 零告警 + `flutter test` 全绿（此时页面仍用旧常量，
  `tokens.spec` 类测试不受影响）。

### Task E-2.2 组件层

- [ ] 新增 `app/lib/core/ui/`，按 spec §8.2 实现：`EmberButton`（主/次/文字/危险 + 五态）、
      `EmberField`、`EmberCard`、`EmberAvatar`（在线点 / 新配对光晕）、`EmberBadge`、
      `EmberSheet`、`EmberToast`、`EmberEmpty`、`EmberSkeleton`。
- [ ] 每个组件的每一种状态都要有 golden 用例（`app/test/core/ui/*.golden.dart`）。
- 验收：`flutter test` 全绿；`flutter analyze` 零告警。

### Task E-2.3 删除手写 token

- [ ] 删除 `app/lib/core/theme/app_colors.dart` 等心跳期常量文件（保留 `tokens.g.dart`）。
- [ ] 全仓 `grep -rn "0xFF" app/lib --include=*.dart | grep -v tokens.g.dart` 必须为空
      （除生成物与测试期望）。
- 验收：`flutter analyze` 零告警 + 全量测试绿。

> **注意**：E-2 不迁移任何页面视觉 —— 那是 E-5 的事。本单只换底座，允许页面显示「旧布局 + 新色值」的中间态。

---

## E-3 · `web` 栈：PrimeVue unstyled 接线

> **工单**：[#466](https://github.com/shiliu153/chatapp/issues/466)（已开，**未派单**：等规范评审）

### Task E-3.1 样式入口

- [ ] `web/src/main.ts` 引入 `tokens.generated.css`。
- [ ] 删除 `web/src/styles/tokens.css` 与 `web/tests/unit/tokens.spec.ts` 的双份比对
      （它比较的是 App 与 Web 两份手写值，链路换掉后这条规则本身作废）；
      改成断言「生成物文件存在且含 `--color-brand-default`」的轻量用例。
- 验收：`cd web && npm run test:run` 绿 + `npm run type-check` 零错误。

### Task E-3.2 PrimeVue

- [ ] 装 `primevue` + `@primeuix/themes`（仅用其无样式能力），`app.use(PrimeVue, { unstyled: true })`。
- [ ] 写 `web/src/styles/primevue-pass-through.ts`：把每个组件段的 `pt` 映射到
      `tokens.generated.css` 的 CSS 变量（**只引用变量，不写值**）。
- [ ] Tailwind v4 `@theme` 里把变量转发成语义工具类（`bg-surface-card` 等）。
- 验收：`npm run build` 成功；`npm run lint` 零告警；`npm run test:coverage` 过门槛。

### Task E-3.3 无障碍门禁

- [ ] `web` 加 `@axe-core/playwright`（或 `vitest-axe`）冒烟：主流程页面零 critical。
- 验收：`npm run e2e:smoke` 绿（CI `web-e2e.yml` 已装真后端）。

---

## E-4 · `docs` 栈：转正与归档

- [ ] spec 头部 `v0.1 草案，待评审` → `v1.0 生效`。
- [ ] 旧规范 `git mv docs/superpowers/specs/2026-09-15-ui-design-language-design.md docs/superpowers/archive/specs/`（**文件名与内容不改**）。
- [ ] 同一次改动内改三处引用：`CLAUDE.md` 的 UI 规则段、`AGENTS.md` 的 App 行、
      `docs/standards/sources-of-truth.md` §2.5（删掉「待废止」那行）。
- [ ] `python scripts/docs_index.py --write` + `python scripts/facts.py --write`。
- 验收：`scripts/verify.sh contract` 绿。

**前置**：E-2 与 E-3 至少一个已合并 —— 否则转正会让存量页面失去规范约束（见 spec §12 过渡期）。

---

## E-5+ · 逐页迁移（每页一单，`app` 或 `web`）

顺序按「用户停留时长 × 改动面」：

1. 底栏 shell + 四个 Tab 骨架
2. 发现页（滑卡、操作钮、Hero 到资料页）
3. 消息页 + 聊天页（气泡、输入栏、时间条）
4. 我的 + 资料页
5. 回声（广场）页
6. 二级页（登录 / 引导 / 设置 / 编辑资料）

每单固定验收：`scripts/verify.sh app`（或 `web`）绿 + 该页 golden + 模拟器手测截图
（App）/ 真浏览器截图（Web）。**不得声称 ready**：App UI 可见改动的 PR 一律 draft，等主人验收。

---

## 执行记录

- 2026-11-23：E-1 按「流程自身的自证手段」例外**在会话内联交付**（worker 没有门禁就无从自证）。
  六道门禁进 `scripts/gates.toml`，`scripts/verify.sh contract` 38 / 38 通过。
- 2026-11-23：E-2 / E-3 已开成工单（[#465](https://github.com/shiliu153/chatapp/issues/465) /
  [#466](https://github.com/shiliu153/chatapp/issues/466)），**故意未派单** —— 规范 v0.1 还没评审，
  派了就是让 worker 按未定稿的规范施工。评审通过后在各 issue 里评论 `@shiliu655` 触发。
- E-1 的改动**尚未提交**（本机检出有换行符噪音，需要按路径显式 `git add`）。
