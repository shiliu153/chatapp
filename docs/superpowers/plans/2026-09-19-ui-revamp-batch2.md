# UI 整改批次②(发现页)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按「心跳」规则整改发现页全页:页壳(大标题/骨架屏/空态/错误态)+ 滑卡卡面 + 圆形操作钮 + 配对情感时刻(完整 cinematic)+ 资料未完善引导;行为零变化,只动视觉层。

**Architecture:** 先做 core 层扩展(token 两个新常量、BreathingDot 从 AppAvatar 提炼为共享组件、新 HeartRipple、AppEmptyState 加 mark 参数、新 DeckSkeleton),再自底向上重做发现页四个文件(profile_card → swipe_deck → match_overlay → discovery_page)。规则文档 v1.1 附录先于代码落笔(§9 边界流程)。

**Tech Stack:** Flutter 3.47(`../flutter/bin/flutter.bat`)、Riverpod、现有 widget 测试体系(真实 provider + 假网络 + 假 IM);零新增依赖。

**Spec:** `docs/superpowers/specs/2026-09-19-ui-revamp-batch2-design.md`;视觉细节一律以「心跳」规则 `docs/superpowers/specs/2026-09-15-ui-design-language-design.md`(含本批新增附录 A)为准。

## Global Constraints

- 所有 flutter 命令 cwd = `app/`,用 `../flutter/bin/flutter.bat`(Windows)。
- 新代码**禁止裸 hex / 裸字号 / 裸间距 / 裸圆角**(token 文件本身与从 token 派生的 `withValues/Color.lerp` 除外)。
- 只动发现页四个文件 + 所列 core 文件;**不改其他页面**;不迁移页面既有 SnackBar 用法;接口/路由/控制器零改动。
- 每步全绿再进下一步:改完必跑 `flutter analyze`(零告警)+ 相关测试;标了「全量」的步骤跑全量 `flutter test`。
- **无限动画纪律**:`BreathingDot`/`DeckSkeleton`/`AppSkeleton` 是无限呼吸动画,凡处于可见状态的用例**只用有限 `pump`,禁 `pumpAndSettle`**(见 `docs/pitfalls/testing.md` 与批次① `app_avatar_test` 先例)。
- **弹层无循环动画**:配对弹层与 HeartRipple 必须是有限/静态动画,保证 `pumpAndSettle` 可达完成帧(现有 `discovery_page_test` 依赖)。
- 代码提交在分支 `ui/batch2`;完成手测后 ff 合并 master、删分支、push origin(计划文档本身直接提交 master)。
- 手测连服务器 `http://<SERVER_IP>/api/v1`(不用起本地后端);**动模拟器前先与用户确认**。
- 基线:批次①后全量 **220 用例绿**、analyze 零告警。

---

### Task 1: 基线确认 + 建分支

**Files:** 无(仅环境)

- [ ] **Step 1: 确认 analyze 基线**

Run: `cd app && ../flutter/bin/flutter.bat analyze`
Expected: `No issues found!`

- [ ] **Step 2: 跑全量测试基线并记录数量**

Run: `../flutter/bin/flutter.bat test`
Expected: 全部通过;记录 `All tests passed` 前的用例数(预期 220),作为本批对照基准。

- [ ] **Step 3: 建分支**

Run(仓库根): `git checkout -b ui/batch2`

---

### Task 2: 「心跳」规则文档 v1.1 附录(§9 边界流程,先于代码)

**Files:**
- Modify: `docs/superpowers/specs/2026-09-15-ui-design-language-design.md`(头部状态行 + 文末新增附录 A)

- [ ] **Step 1: 更新头部状态行**

第 3 行 `状态:**v1.0,设计内容已获用户批准**(浏览器视觉评审三屏通过);文档文本待用户终审。本文件是**常驻规则文档**` 改为:

```markdown
状态:**v1.1(2026-09-19 增补附录 A:发现页落地补充),设计内容已获用户批准**(浏览器视觉评审通过);本文件是**常驻规则文档**
```

- [ ] **Step 2: 文末(§11 之后)追加附录 A**

```markdown
## 附录 A:发现页落地补充(2026-09-19,批次②)

本附录是 §9 边界流程的产出:以下场景规则正文未覆盖,经浏览器模拟图评审确认后定稿;后续页面遇同类场景以此为准。

### A.1 滑卡操作钮(发现页专属)

- 跳过:圆形 56,白底 + 1.5px `divider` 描边,`close_rounded` 24 `text3`,浮卡阴影
- 喜欢:圆形 64,`gradientHeart` 底,`favorite_rounded` 24 白,主按钮光晕阴影
- 间距 44;按压 scale .96(`fast`);点喜欢时脉冲 `1→1.25→1`(`base`,与滑卡飞出并行,不阻塞)
- 语义:两钮等价于左右滑卡(与拖拽同一套判定)

### A.2 照片叠字 scrim

- 渐变:上 `Colors.transparent` → 下 `AppColors.photoScrim`(`#101114`,87%)
- 用途:照片上叠文字时的对比度兜底;叠字用白色系(主 93%、次 72%、辅 88%)

### A.3 涟漪空态元素(HeartRipple)

- 三圈同心环(外→内:`heartOrange` 30%、brand/橙中值 55%、`brand` 90%,描边 2px)+ 中心渐变光点(带 brand 光晕);尺寸 96
- **纯静态,不做动画**(无限动画会挂死用 pumpAndSettle 的测试)
- 语义:与「心跳光晕」签名同源;空态大号元素以此为默认,emoji 为备选(AppEmptyState 的 `mark` 参数优先)

### A.4 照片切换指示(胶囊点)

- 普通张:6px 圆点(白 45%);当前张:18×6 白 全圆小胶囊;间距 5,居中,距卡顶 8
- 替代旧 8px 圆点方案

### A.5 配对情感时刻编排参数

- 遮罩:`text1` 94% 深底;总时长 ~1100ms,单控制器 Interval 分段
- 分段:光晕扩散 0–550 / 双头像相向 150–550 / 碰撞光环 + 心形弹出 500–800 / 粒子飘散 600–1100 / 文案按钮 800–1100
- 粒子:约 24 个,2–5px,`brand`/`heartOrange`/`amber`/白,自碰撞点向外飘散渐隐
- 任意点击直达完成帧;系统「减弱动态效果」直接呈现完成帧;全程无循环动画
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-09-15-ui-design-language-design.md
git commit -m "docs: 「心跳」规则 v1.1——附录 A 发现页落地补充(§9 边界:滑卡圆钮/scrim/涟漪/胶囊点/配对编排)"
```

---

### Task 3: token 扩展(discoveryCard 圆角 + photoScrim 色)

**Files:**
- Modify: `app/lib/core/theme/app_radius.dart`
- Modify: `app/lib/core/theme/app_colors.dart`
- Test: `app/test/core/theme/tokens_test.dart`(追加断言)

**Interfaces:**
- Produces: `AppRadius.discoveryCard`(=24,后续 ProfileCard/DeckSkeleton 消费);`AppColors.photoScrim`(=Color(0xDE101114),ProfileCard 消费)

- [ ] **Step 1: 写失败断言(追加到 `tokens_test.dart` 的 main 内)**

```dart
  test('发现卡圆角与照片 scrim(附录 A)', () {
    expect(AppRadius.discoveryCard, 24);
    expect(AppColors.photoScrim, const Color(0xDE101114));
  });
```

(文件顶部补 `import 'package:chatapp_app/core/theme/app_colors.dart';`——若已有 AppRadius import 则只补 colors。)

Run: `cd app && ../flutter/bin/flutter.bat test test/core/theme/tokens_test.dart`
Expected: 编译失败(`discoveryCard`/`photoScrim` 不存在)

- [ ] **Step 2: 实现**

`app_radius.dart` 在 `full` 之前追加:

```dart
  static const discoveryCard = 24.0; // 发现页全屏大卡(§5.1,附录 A)
```

`app_colors.dart` 在 `systemBlue` 之后追加:

```dart
  /// 照片叠字 scrim:发现卡底部渐变终点 rgba(16,17,20,.87),起点用 Colors.transparent(附录 A.2)。
  static const photoScrim = Color(0xDE101114);
```

- [ ] **Step 3: 测试通过 + analyze**

Run: `../flutter/bin/flutter.bat test test/core/theme/tokens_test.dart && ../flutter/bin/flutter.bat analyze`
Expected: 全过;`No issues found!`

- [ ] **Step 4: Commit**

```bash
git add app/lib/core/theme/app_radius.dart app/lib/core/theme/app_colors.dart app/test/core/theme/tokens_test.dart
git commit -m "feat(ui): token 扩展——discoveryCard 圆角 24 与 photoScrim(附录 A)"
```

---

### Task 4: BreathingDot 提炼为共享组件(AppAvatar 改用)

**Files:**
- Create: `app/lib/core/widgets/breathing_dot.dart`
- Modify: `app/lib/core/widgets/app_avatar.dart`(删私有 `_BreathingDot`,改用它)
- Test: `app/test/core/widgets/app_avatar_test.dart`(**不动**——key 保持即验证提炼无损)

**Interfaces:**
- Produces: `BreathingDot({Key?, size = 11, borderColor = Colors.white})`——AppAvatar 传 `Key('avatar.onlineDot')`;Task 8 卡面传 `Key('card.onlineDot')`,size 8

- [ ] **Step 1: 新建 `breathing_dot.dart`**

```dart
import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_motion.dart';

/// 在线点:green + 呼吸光晕(§5.3/§4);描边色 = 所在背景色。
/// 无限动画:处于可见状态的测试只用有限 pump,禁 pumpAndSettle。
class BreathingDot extends StatefulWidget {
  const BreathingDot({
    super.key,
    this.size = 11,
    this.borderColor = Colors.white,
  });

  final double size;
  final Color borderColor;

  @override
  State<BreathingDot> createState() => _BreathingDotState();
}

class _BreathingDotState extends State<BreathingDot> with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: AppMotion.loop)..repeat(reverse: true);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _c,
        builder: (context, _) => Opacity(
          opacity: 0.55 + 0.45 * _c.value, // 呼吸:透明度 .55↔1
          child: Container(
            width: widget.size,
            height: widget.size,
            decoration: BoxDecoration(
              color: AppColors.green,
              shape: BoxShape.circle,
              border: Border.all(color: widget.borderColor, width: 2),
            ),
          ),
        ),
      );
}
```

- [ ] **Step 2: 改造 `app_avatar.dart`**

1. 加 `import 'breathing_dot.dart';`,删 `import '../theme/app_motion.dart';`(不再用)。
2. Stack 里的 `_BreathingDot(size: ..., borderColor: ...)` 整段替换为:

```dart
            child: BreathingDot(
              key: const Key('avatar.onlineDot'),
              size: size >= 48 ? 11 : 8,
              borderColor: dotBorderColor,
            ),
```

3. 删除文件末尾整个 `_BreathingDot` / `_BreathingDotState` 类(含其上的文档注释)。

- [ ] **Step 3: 验证(既有 avatar 测试全过即无损)**

Run: `../flutter/bin/flutter.bat test test/core/widgets/app_avatar_test.dart && ../flutter/bin/flutter.bat test test/core/widgets/ && ../flutter/bin/flutter.bat analyze`
Expected: 全过(key `avatar.onlineDot` 沿用);`No issues found!`

- [ ] **Step 4: Commit**

```bash
git add app/lib/core/widgets/breathing_dot.dart app/lib/core/widgets/app_avatar.dart
git commit -m "refactor(ui): 在线点提炼为共享 BreathingDot,AppAvatar 改用(key 不变)"
```

---

### Task 5: HeartRipple 涟漪组件

**Files:**
- Create: `app/lib/core/widgets/heart_ripple.dart`
- Test: `app/test/core/widgets/heart_ripple_test.dart`

**Interfaces:**
- Consumes: `AppColors.brand/heartOrange`、`AppGradients.heart`
- Produces: `HeartRipple({size = 96})`——静态;Task 11 空态/引导态消费

- [ ] **Step 1: 写失败测试**

`app/test/core/widgets/heart_ripple_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/heart_ripple.dart';

void main() {
  testWidgets('三圈同心环 + 中心光点;纯静态(有限 pump 不变化)', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: Center(child: HeartRipple())),
    ));

    expect(find.byType(HeartRipple), findsOneWidget);
    expect(
      find.descendant(of: find.byType(HeartRipple), matching: find.byType(Container)),
      findsNWidgets(4), // 3 环 + 中心点
    );

    // 静态:推进两帧后仍无变化(无动画控制器)
    await tester.pump(const Duration(milliseconds: 600));
    await tester.pump(const Duration(milliseconds: 600));
    expect(find.byType(HeartRipple), findsOneWidget);
  });

  testWidgets('尺寸参数生效', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: Center(child: HeartRipple(size: 120))),
    ));
    expect(tester.getSize(find.byType(HeartRipple)), const Size(120, 120));
  });
}
```

Run: `cd app && ../flutter/bin/flutter.bat test test/core/widgets/heart_ripple_test.dart`
Expected: 编译失败(组件不存在)

- [ ] **Step 2: 实现 `heart_ripple.dart`**

```dart
import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_gradients.dart';

/// 「心跳」规则附录 A.3 涟漪空态元素:三圈同心渐变环 + 中心光点。
/// 纯静态(不用动画控制器);空态/引导态的大号彩色元素。
class HeartRipple extends StatelessWidget {
  const HeartRipple({super.key, this.size = 96});

  final double size;

  @override
  Widget build(BuildContext context) {
    final mid = Color.lerp(AppColors.brand, AppColors.heartOrange, 0.5)!;
    return SizedBox.square(
      dimension: size,
      child: Stack(
        alignment: Alignment.center,
        children: [
          _ring(size, AppColors.heartOrange.withValues(alpha: 0.30)),
          _ring(size * 0.69, mid.withValues(alpha: 0.55)),
          _ring(size * 0.42, AppColors.brand.withValues(alpha: 0.90)),
          Container(
            width: size * 0.15,
            height: size * 0.15,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: AppGradients.heart,
              boxShadow: [
                BoxShadow(color: AppColors.brand.withValues(alpha: 0.65), blurRadius: 16),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _ring(double diameter, Color color) => Container(
        width: diameter,
        height: diameter,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          border: Border.all(color: color, width: 2),
        ),
      );
}
```

- [ ] **Step 3: 测试通过 + analyze**

Run: `../flutter/bin/flutter.bat test test/core/widgets/heart_ripple_test.dart && ../flutter/bin/flutter.bat analyze`
Expected: 全过;`No issues found!`

- [ ] **Step 4: Commit**

```bash
git add app/lib/core/widgets/heart_ripple.dart app/test/core/widgets/heart_ripple_test.dart
git commit -m "feat(ui): HeartRipple 涟漪空态元素(附录 A.3,纯静态)"
```

---

### Task 6: AppEmptyState 扩展(mark 参数,emoji 改可空)

**Files:**
- Modify: `app/lib/core/widgets/app_empty_state.dart`
- Test: `app/test/core/widgets/app_empty_state_test.dart`(追加;既有 2 用例不动)

**Interfaces:**
- Produces: `AppEmptyState({Widget? mark, String? emoji, required String title, String? description, Widget? action})`——渲染优先级 mark > emoji;两者皆空不渲染元素。Task 11 消费 mark 形态。
- 既有调用(`emoji:` 命名参数)零改动。

- [ ] **Step 1: 追加失败断言**

在 `app_empty_state_test.dart` 的 main 内追加(顶部补 `import 'package:chatapp_app/core/widgets/heart_ripple.dart';`):

```dart
  testWidgets('mark 优先于 emoji;两者皆空不崩', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(
        body: Center(
          child: AppEmptyState(
            mark: HeartRipple(size: 60),
            emoji: '✨',
            title: '空空如也',
          ),
        ),
      ),
    ));
    expect(find.byType(HeartRipple), findsOneWidget);
    expect(find.text('✨'), findsNothing);

    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: Center(child: AppEmptyState(title: '只有标题'))),
    ));
    expect(find.text('只有标题'), findsOneWidget);
  });
```

Run: `cd app && ../flutter/bin/flutter.bat test test/core/widgets/app_empty_state_test.dart`
Expected: 编译失败(`mark` 参数不存在 / `emoji` 仍 required)

- [ ] **Step 2: 实现**

`app_empty_state.dart` 构造与 build 改:

```dart
/// 「心跳」规则 §7 空态:大号彩色元素(mark 优先,emoji 备选)+ 标题 17/w600
/// + 说明 13 text2 + 可选按钮。禁止灰色图标占位。
class AppEmptyState extends StatelessWidget {
  const AppEmptyState({
    super.key,
    this.mark,
    this.emoji,
    required this.title,
    this.description,
    this.action,
  });

  /// 大号元素二选一:mark(自定义图形,优先)或 emoji。
  final Widget? mark;
  final String? emoji;
```

build 的 children 首两项改为:

```dart
          if (mark != null)
            mark!
          else if (emoji != null)
            Text(emoji!, style: AppText.emoji),
          const SizedBox(height: AppSpacing.md),
```

(其余不变。)

- [ ] **Step 3: 测试通过 + analyze**

Run: `../flutter/bin/flutter.bat test test/core/widgets/ && ../flutter/bin/flutter.bat analyze`
Expected: 全过(含既有 emoji 用例);`No issues found!`

- [ ] **Step 4: Commit**

```bash
git add app/lib/core/widgets/app_empty_state.dart app/test/core/widgets/app_empty_state_test.dart
git commit -m "feat(ui): AppEmptyState 支持 mark 自定义元素(emoji 改可选,零迁移)"
```

---

### Task 7: DeckSkeleton 卡片形骨架屏

**Files:**
- Create: `app/lib/features/discovery/widgets/deck_skeleton.dart`
- Test: `app/test/features/discovery/deck_skeleton_test.dart`

**Interfaces:**
- Consumes: `AppColors.divider/bgCard`、`AppRadius.discoveryCard`(Task 3)、`AppMotion.loop`、`AppSpacing`
- Produces: `DeckSkeleton({super.key})`——Task 11 页壳两处 loading 消费;**无限呼吸,测试只用有限 pump**

- [ ] **Step 1: 写失败测试**

`app/test/features/discovery/deck_skeleton_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/discovery/widgets/deck_skeleton.dart';

void main() {
  testWidgets('渲染卡片骨架并呼吸(有限 pump,禁 pumpAndSettle)', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: DeckSkeleton()),
    ));
    await tester.pump();

    expect(find.byType(DeckSkeleton), findsOneWidget);

    final opacityBefore = tester
        .widget<Opacity>(find.descendant(of: find.byType(DeckSkeleton), matching: find.byType(Opacity)))
        .opacity;
    await tester.pump(const Duration(milliseconds: 600));
    final opacityAfter = tester
        .widget<Opacity>(find.descendant(of: find.byType(DeckSkeleton), matching: find.byType(Opacity)))
        .opacity;
    expect(opacityAfter, isNot(opacityBefore)); // 呼吸中
  });
}
```

Run: `cd app && ../flutter/bin/flutter.bat test test/features/discovery/deck_skeleton_test.dart`
Expected: 编译失败(文件不存在)

- [ ] **Step 2: 实现 `deck_skeleton.dart`**

```dart
import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_motion.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';

/// 发现页加载骨架:与卡面等大的呼吸块 + 操作钮位。
/// 无限动画:可见状态的测试只用有限 pump,禁 pumpAndSettle。
class DeckSkeleton extends StatefulWidget {
  const DeckSkeleton({super.key});

  @override
  State<DeckSkeleton> createState() => _DeckSkeletonState();
}

class _DeckSkeletonState extends State<DeckSkeleton> with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: AppMotion.loop)..repeat(reverse: true);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _c,
        builder: (context, _) => Opacity(
          opacity: 0.5 + 0.5 * _c.value,
          child: Column(
            children: [
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(AppSpacing.pageH, AppSpacing.sm, AppSpacing.pageH, 0),
                  child: Container(
                    decoration: BoxDecoration(
                      color: AppColors.divider,
                      borderRadius: BorderRadius.circular(AppRadius.discoveryCard),
                    ),
                    child: Align(
                      alignment: Alignment.bottomLeft,
                      child: Padding(
                        padding: const EdgeInsets.all(AppSpacing.lg),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            _bar(0.62),
                            const SizedBox(height: 9),
                            _bar(0.38),
                            const SizedBox(height: 9),
                            _bar(0.84),
                            const SizedBox(height: AppSpacing.md),
                            const Row(children: [_Chip(), SizedBox(width: 6), _Chip()]),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ),
              const SizedBox(
                height: 88,
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    _Circle(44),
                    SizedBox(width: 44),
                    _Circle(44),
                  ],
                ),
              ),
              const SizedBox(height: AppSpacing.lg),
            ],
          ),
        ),
      );

  Widget _bar(double widthFactor) => FractionallySizedBox(
        alignment: Alignment.centerLeft,
        widthFactor: widthFactor,
        child: Container(
          height: 10,
          decoration: BoxDecoration(
            color: AppColors.bgCard.withValues(alpha: 0.75),
            borderRadius: BorderRadius.circular(5),
          ),
        ),
      );
}

class _Chip extends StatelessWidget {
  const _Chip();

  @override
  Widget build(BuildContext context) => Container(
        width: 44,
        height: 16,
        decoration: BoxDecoration(
          color: AppColors.bgCard.withValues(alpha: 0.75),
          borderRadius: BorderRadius.circular(AppRadius.chip),
        ),
      );
}

class _Circle extends StatelessWidget {
  const _Circle(this.size);

  final double size;

  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        decoration: const BoxDecoration(color: AppColors.divider, shape: BoxShape.circle),
      );
}
```

注意:`_Chip`/`_Circle` 必须 UpperCamelCase(analyze 的 camel_case_types 规则),构造函数为 const 才能进 const Row。

- [ ] **Step 3: 测试通过 + analyze**

Run: `../flutter/bin/flutter.bat test test/features/discovery/deck_skeleton_test.dart && ../flutter/bin/flutter.bat analyze`
Expected: 全过;`No issues found!`

- [ ] **Step 4: Commit**

```bash
git add app/lib/features/discovery/widgets/deck_skeleton.dart app/test/features/discovery/deck_skeleton_test.dart
git commit -m "feat(ui): DeckSkeleton 卡片形呼吸骨架屏(§7/附录 A)"
```

---

### Task 8: ProfileCard 重做(卡面)

**Files:**
- Modify: `app/lib/features/discovery/widgets/profile_card.dart`(整文件重写)
- Modify: `app/test/features/discovery/profile_card_test.dart`(2 处断言同步)

**Interfaces:**
- Consumes: `AppRadius.discoveryCard`(Task 3)、`AppColors.photoScrim`(Task 3)、`BreathingDot`(Task 4)
- Produces: 同名 `ProfileCard({required Candidate candidate, Presence? presence})`——API 不变;key `card.dots`/`card.prevPhoto`/`card.nextPhoto`/`ValueKey('card.photo.{id}')` 不变;新增 key `card.onlineDot`

- [ ] **Step 1: 更新既有测试断言(先改测试)**

`profile_card_test.dart` 两处:

1. 「一张照片都没有」用例:`expect(find.byIcon(Icons.person_outline), findsOneWidget);` → `expect(find.byIcon(Icons.person_rounded), findsOneWidget);`
2. 「在线」用例:原 `expect(find.text('● 在线'), findsOneWidget);` 改为:

```dart
    expect(find.byKey(const Key('card.onlineDot')), findsOneWidget);
    expect(find.text('在线'), findsOneWidget);
```

Run: `cd app && ../flutter/bin/flutter.bat test test/features/discovery/profile_card_test.dart`
Expected: 2 个用例 FAIL(旧实现仍是 `person_outline` 与「● 在线」)

- [ ] **Step 2: 重写 `profile_card.dart`**

```dart
import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/breathing_dot.dart';
import '../../presence/models.dart';
import '../models.dart';

/// 单张候选卡(附录 A「沉浸照片版」):照片全出血 + 底部 scrim 叠字;
/// 多张照片时点左右两侧切换 + 顶部胶囊点指示。
class ProfileCard extends StatefulWidget {
  const ProfileCard({super.key, required this.candidate, this.presence});

  final Candidate candidate;
  final Presence? presence;

  @override
  State<ProfileCard> createState() => _ProfileCardState();
}

class _ProfileCardState extends State<ProfileCard> {
  int _photoIndex = 0;

  @override
  void didUpdateWidget(covariant ProfileCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    // 换成另一个人的卡了,照片从第一张重新看起
    if (oldWidget.candidate.userId != widget.candidate.userId) _photoIndex = 0;
  }

  void _shiftPhoto(int delta) {
    final count = widget.candidate.photos.length;
    if (count < 2) return;
    setState(() => _photoIndex = (_photoIndex + delta + count) % count);
  }

  @override
  Widget build(BuildContext context) {
    final candidate = widget.candidate;
    final photos = candidate.photos;
    final photo = photos.isEmpty ? null : photos[_photoIndex];
    final online = widget.presence?.online ?? false;
    final statusLabel = presenceLabel(widget.presence);
    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(AppRadius.discoveryCard),
        boxShadow: AppShadows.card,
      ),
      child: Material(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.circular(AppRadius.discoveryCard),
        clipBehavior: Clip.antiAlias,
        child: Stack(
          fit: StackFit.expand,
          children: [
            if (photo == null)
              Container(
                color: AppColors.divider,
                child: const Center(
                  child: Icon(Icons.person_rounded, size: 64, color: AppColors.text3),
                ),
              )
            else
              Image.network(
                photo.url,
                key: ValueKey('card.photo.${photo.id}'),
                fit: BoxFit.cover,
                errorBuilder: (context, error, stack) => Container(
                  color: AppColors.divider,
                  child: const Center(
                    child: Icon(Icons.person_rounded, size: 64, color: AppColors.text3),
                  ),
                ),
              ),
            if (photos.length > 1) ...[
              Positioned(
                left: 0,
                top: 0,
                bottom: 0,
                width: 56,
                child: GestureDetector(
                  key: const Key('card.prevPhoto'),
                  behavior: HitTestBehavior.translucent,
                  onTap: () => _shiftPhoto(-1),
                ),
              ),
              Positioned(
                right: 0,
                top: 0,
                bottom: 0,
                width: 56,
                child: GestureDetector(
                  key: const Key('card.nextPhoto'),
                  behavior: HitTestBehavior.translucent,
                  onTap: () => _shiftPhoto(1),
                ),
              ),
              Positioned(
                top: 8,
                left: 0,
                right: 0,
                child: Row(
                  key: const Key('card.dots'),
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    for (var i = 0; i < photos.length; i++)
                      Container(
                        width: i == _photoIndex ? 18 : 6, // 当前张:18×6 胶囊
                        height: 6,
                        margin: const EdgeInsets.symmetric(horizontal: 2.5),
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(3),
                          color: i == _photoIndex
                              ? Colors.white
                              : Colors.white.withValues(alpha: 0.45),
                        ),
                      ),
                  ],
                ),
              ),
            ],
            Positioned(
              left: 0,
              right: 0,
              bottom: 0,
              child: Container(
                padding: const EdgeInsets.fromLTRB(AppSpacing.lg, 46, AppSpacing.lg, 14),
                decoration: const BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [Colors.transparent, AppColors.photoScrim],
                  ),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Row(
                      children: [
                        Flexible(
                          child: Text(
                            candidate.age == null
                                ? candidate.nickname
                                : '${candidate.nickname},${candidate.age}',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: AppText.display.copyWith(color: Colors.white),
                          ),
                        ),
                        if (online) ...[
                          const SizedBox(width: AppSpacing.sm),
                          const BreathingDot(
                            key: Key('card.onlineDot'),
                            size: 8,
                            borderColor: Colors.white,
                          ),
                          const SizedBox(width: AppSpacing.xs),
                          Text(
                            '在线',
                            style: AppText.micro.copyWith(
                                color: Colors.white.withValues(alpha: 0.88)),
                          ),
                        ] else if (statusLabel != null) ...[
                          const SizedBox(width: AppSpacing.sm),
                          Text(
                            statusLabel,
                            style: AppText.caption.copyWith(
                                color: Colors.white.withValues(alpha: 0.72)),
                          ),
                        ],
                      ],
                    ),
                    if (candidate.city.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.only(top: 2),
                        child: Text(
                          candidate.city,
                          style: AppText.caption.copyWith(
                              color: Colors.white.withValues(alpha: 0.72)),
                        ),
                      ),
                    if (candidate.bio.isNotEmpty) ...[
                      const SizedBox(height: 6),
                      Text(
                        candidate.bio,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: AppText.body.copyWith(
                            color: Colors.white.withValues(alpha: 0.93)),
                      ),
                    ],
                    if (candidate.tags.isNotEmpty) ...[
                      const SizedBox(height: AppSpacing.sm),
                      Wrap(
                        spacing: 6,
                        runSpacing: 6,
                        children: [
                          for (final tag in candidate.tags)
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                              decoration: BoxDecoration(
                                color: Colors.white.withValues(alpha: 0.22),
                                borderRadius: BorderRadius.circular(AppRadius.chip),
                              ),
                              child: Text(
                                tag.name,
                                style: AppText.micro.copyWith(color: Colors.white),
                              ),
                            ),
                        ],
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
```

注意:新代码引用了 `AppShadows.card`——文件顶部需 `import '../../../core/theme/app_shadows.dart';`(上面代码块请一并加上)。

- [ ] **Step 3: 定向测试 + 相邻全量**

Run: `../flutter/bin/flutter.bat test test/features/discovery/ && ../flutter/bin/flutter.bat analyze`
Expected: 全部通过(含更新后的 2 个用例;swipe_deck/match_overlay/page 用例不受卡面内部影响);`No issues found!`

- [ ] **Step 4: Commit**

```bash
git add app/lib/features/discovery/widgets/profile_card.dart app/test/features/discovery/profile_card_test.dart
git commit -m "feat(ui): 发现卡面重做——R24/scrim 叠字新排版/胶囊点指示/呼吸在线点(附录 A)"
```

---

### Task 9: SwipeDeck 操作区(圆形双钮 + 心跳脉冲)

**Files:**
- Modify: `app/lib/features/discovery/widgets/swipe_deck.dart`(仅操作区段 + 新增私有 `_DeckActionButton`;顶部加 `import 'dart:math' as math;`)
- Test: `app/test/features/discovery/swipe_deck_test.dart`(追加 1 用例;既有 4 用例不动)

**Interfaces:**
- Consumes: `AppGradients.heart`、`AppShadows.card/primaryButton`、`AppMotion`
- Produces: key `discovery.pass`/`discovery.like` 不变;新增 key `deck.pulse`(喜欢按钮脉冲 Transform,供测试读数)

- [ ] **Step 1: 追加失败测试**

`swipe_deck_test.dart` 的 main 内追加:

```dart
  testWidgets('点喜欢:按钮脉冲 1→1.25→1(base 220ms)', (tester) async {
    final decisions = <String>[];
    await tester.pumpWidget(_Host(decisions: decisions));
    await tester.pump();

    await tester.tap(find.byKey(const Key('discovery.like')));
    await tester.pump(); // ticker 基线帧(首帧不推进动画)
    await tester.pump(const Duration(milliseconds: 110)); // 220 的中点 = 峰值

    double scaleOfPulse() => tester
        .widget<Transform>(find.byKey(const Key('deck.pulse')))
        .transform
        .getMaxScaleOnAxis();

    expect(scaleOfPulse(), closeTo(1.25, 0.02));

    await tester.pump(const Duration(milliseconds: 110)); // 脉冲走完
    expect(scaleOfPulse(), closeTo(1.0, 0.02));
  });
```

Run: `cd app && ../flutter/bin/flutter.bat test test/features/discovery/swipe_deck_test.dart`
Expected: 新用例 FAIL(`deck.pulse` 不存在)

- [ ] **Step 2: 实现操作区**

`swipe_deck.dart` 底部按钮段(`Padding(top: 8, bottom: 24)` 包住的 `Row`)整段替换为:

```dart
        SizedBox(
          height: 88,
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              _DeckActionButton(
                buttonKey: const Key('discovery.pass'),
                icon: Icons.close_rounded,
                size: 56,
                foreground: AppColors.text3,
                background: AppColors.bgCard,
                borderColor: AppColors.divider,
                shadow: AppShadows.card,
                onPressed: _flying ? null : () => _flyOut(like: false),
              ),
              const SizedBox(width: 44),
              _DeckActionButton(
                buttonKey: const Key('discovery.like'),
                icon: Icons.favorite_rounded,
                size: 64,
                foreground: Colors.white,
                gradient: AppGradients.heart,
                shadow: AppShadows.primaryButton,
                pulse: true,
                onPressed: _flying ? null : () => _flyOut(like: true),
              ),
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.lg),
```

卡组区 padding 顶部 16→8、底部 8→0:`Padding(padding: const EdgeInsets.fromLTRB(AppSpacing.pageH, AppSpacing.sm, AppSpacing.pageH, 0), ...)`。

文件末尾追加私有组件:

```dart
/// 附录 A.1 滑卡操作钮:圆钮 + 按压 .96;喜欢钮带心跳脉冲 1→1.25→1。
class _DeckActionButton extends StatefulWidget {
  const _DeckActionButton({
    required this.buttonKey,
    required this.icon,
    required this.size,
    required this.foreground,
    this.background,
    this.gradient,
    this.borderColor,
    required this.shadow,
    this.pulse = false,
    this.onPressed,
  });

  final Key buttonKey;
  final IconData icon;
  final double size;
  final Color foreground;
  final Color? background;
  final Gradient? gradient;
  final Color? borderColor;
  final List<BoxShadow> shadow;
  final bool pulse;
  final VoidCallback? onPressed;

  @override
  State<_DeckActionButton> createState() => _DeckActionButtonState();
}

class _DeckActionButtonState extends State<_DeckActionButton>
    with SingleTickerProviderStateMixin {
  late final AnimationController _pulse =
      AnimationController(vsync: this, duration: AppMotion.base);
  var _pressed = false;

  @override
  void dispose() {
    _pulse.dispose();
    super.dispose();
  }

  void _handleTap() {
    if (widget.onPressed == null) return;
    if (widget.pulse) _pulse.forward(from: 0); // 与飞出并行,不阻塞
    widget.onPressed!();
  }

  @override
  Widget build(BuildContext context) {
    final enabled = widget.onPressed != null;
    return GestureDetector(
      key: widget.buttonKey,
      behavior: HitTestBehavior.opaque,
      onTapDown: enabled ? (_) => setState(() => _pressed = true) : null,
      onTapUp: enabled ? (_) => setState(() => _pressed = false) : null,
      onTapCancel: enabled ? () => setState(() => _pressed = false) : null,
      onTap: _handleTap,
      child: AnimatedScale(
        scale: _pressed ? 0.96 : 1,
        duration: AppMotion.fast,
        child: AnimatedBuilder(
          animation: _pulse,
          builder: (context, child) => Transform.scale(
            // key 只给脉冲钮:两个按钮都会 build 这个 Transform,无条件挂 key 会撞出
            // "Too many elements"(find.byKey 命中 2 个)
            key: widget.pulse ? const Key('deck.pulse') : null,
            scale: 1 + 0.25 * math.sin(math.pi * _pulse.value),
            child: child,
          ),
          child: Container(
            width: widget.size,
            height: widget.size,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: widget.background,
              gradient: widget.gradient,
              border: widget.borderColor == null
                  ? null
                  : Border.all(color: widget.borderColor!, width: 1.5),
              boxShadow: widget.shadow,
            ),
            child: Icon(widget.icon, size: 24, color: widget.foreground),
          ),
        ),
      ),
    );
  }
}
```

顶部 import 追加(其余 import 已有):

```dart
import 'dart:math' as math;

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_gradients.dart';
import '../../../core/theme/app_motion.dart';
import '../../../core/theme/app_shadows.dart';
import '../../../core/theme/app_spacing.dart';
```

注意:`_pulse` 控制器停在 value=1 时 `sin(π)=0` → scale 1,天然回落;无需 reverse。`deck.pulse` key 在 Transform 上,与 AnimatedScale(按压)互不干扰。

- [ ] **Step 3: 测试 + analyze**

Run: `../flutter/bin/flutter.bat test test/features/discovery/ && ../flutter/bin/flutter.bat analyze`
Expected: 全过(既有 4 用例的 `discovery.like/pass` tap 继续可用);`No issues found!`

- [ ] **Step 4: Commit**

```bash
git add app/lib/features/discovery/widgets/swipe_deck.dart app/test/features/discovery/swipe_deck_test.dart
git commit -m "feat(ui): 滑卡圆钮操作区(56/64)与心跳脉冲(附录 A.1)"
```

---

### Task 10: 配对情感时刻(完整 cinematic + 粒子)

**Files:**
- Create: `app/lib/features/discovery/widgets/match_particles.dart`
- Modify: `app/lib/features/discovery/widgets/match_overlay.dart`(整文件重写)
- Modify: `app/test/features/discovery/match_overlay_test.dart`(1 处断言同步 + 追加 3 用例)

**Interfaces:**
- Consumes: `AppAvatar(halo)`、`AppButton`、`AppColors.text1`(遮罩派生)、`AppText`
- Produces: `MatchOverlay({candidate, myAvatarUrl, onClose, onGoChat})` 与 `showMatchOverlay(context, {candidate, myAvatarUrl, onGoChat})` **签名不变**;key `match.goChat`/`match.continue` 不变;无循环动画

- [ ] **Step 1: 更新/追加测试(先改测试)**

`match_overlay_test.dart`:

1. 第 24 行 `expect(find.byIcon(Icons.person), findsOneWidget); // 我没头像时的占位` 改为(顶部补 `import 'package:chatapp_app/core/widgets/app_avatar.dart';`):

```dart
    expect(find.byType(AppAvatar), findsNWidgets(2)); // 双头像在位(无头像侧回退占位)
```

2. main 内追加:

```dart
  testWidgets('编排结束后完成帧可见', (tester) async {
    final candidate = Candidate.fromJson(candidateJson(nickname: '小红'));
    await tester.pumpWidget(
      MaterialApp(home: MatchOverlay(candidate: candidate, onClose: () {})),
    );
    await tester.pumpAndSettle();

    expect(_textOpacity(tester), 1);
  });

  testWidgets('点击任意处直达完成帧', (tester) async {
    final candidate = Candidate.fromJson(candidateJson(nickname: '小红'));
    await tester.pumpWidget(
      MaterialApp(home: MatchOverlay(candidate: candidate, onClose: () {})),
    );
    await tester.pump();
    expect(_textOpacity(tester), lessThan(1)); // 首帧还没走完编排

    await tester.tapAt(const Offset(20, 20));
    await tester.pump();
    expect(_textOpacity(tester), 1);
  });

  testWidgets('减弱动态效果 → 初始即完成帧', (tester) async {
    final candidate = Candidate.fromJson(candidateJson(nickname: '小红'));
    await tester.pumpWidget(MaterialApp(
      home: MediaQuery(
        data: const MediaQueryData(disableAnimations: true),
        child: MatchOverlay(candidate: candidate, onClose: () {}),
      ),
    ));
    expect(_textOpacity(tester), 1);
  });
```

并在 main 外(文件底部)加工具函数:

```dart
double _textOpacity(WidgetTester tester) => tester
    .widget<Opacity>(
      find.ancestor(of: find.text('你们已互相喜欢'), matching: find.byType(Opacity)).first,
    )
    .opacity;
```

Run: `cd app && ../flutter/bin/flutter.bat test test/features/discovery/match_overlay_test.dart`
Expected: 新用例 FAIL(占位图标断言/完成帧控制不存在)

- [ ] **Step 2: 实现 `match_particles.dart`**

```dart
import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';

/// 附录 A.5 配对粒子:progress 0→1 = 自碰撞点向四周飘散渐隐。
/// 固定随机种子:轨迹每次一致,测试与手测可复现。
class MatchParticlesPainter extends CustomPainter {
  MatchParticlesPainter({required this.progress}) : _particles = _build();

  final double progress;
  final List<_Particle> _particles;

  static const _palette = [
    AppColors.brand,
    AppColors.heartOrange,
    AppColors.amber,
    Colors.white,
  ];

  static List<_Particle> _build() {
    final random = math.Random(7);
    return [
      for (var i = 0; i < 24; i++)
        _Particle(
          angle: i / 24 * 2 * math.pi + (random.nextDouble() - 0.5) * 0.5,
          speed: 60 + random.nextDouble() * 80,
          size: 2 + random.nextDouble() * 3,
          color: _palette[random.nextInt(_palette.length)],
          delay: random.nextDouble() * 0.25,
        ),
    ];
  }

  @override
  void paint(Canvas canvas, Size size) {
    if (progress <= 0) return;
    final center = Offset(size.width / 2, size.height / 2);
    for (final particle in _particles) {
      final t = ((progress - particle.delay) / (1 - particle.delay)).clamp(0.0, 1.0);
      if (t <= 0) continue;
      final eased = Curves.easeOutCubic.transform(t);
      final offset = center +
          Offset(math.cos(particle.angle), math.sin(particle.angle)) *
              particle.speed *
              eased;
      final paint = Paint()..color = particle.color.withValues(alpha: (1 - t) * 0.85);
      canvas.drawCircle(offset, particle.size * (1 - 0.3 * t), paint);
    }
  }

  @override
  bool shouldRepaint(MatchParticlesPainter oldDelegate) =>
      oldDelegate.progress != progress;
}

class _Particle {
  const _Particle({
    required this.angle,
    required this.speed,
    required this.size,
    required this.color,
    required this.delay,
  });

  final double angle;
  final double speed;
  final double size;
  final Color color;
  final double delay;
}
```

- [ ] **Step 3: 重写 `match_overlay.dart`**

```dart
import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_motion.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/app_avatar.dart';
import '../../../core/widgets/app_button.dart';
import '../models.dart';
import 'match_particles.dart';

/// 配对成功动效(§6.2 情感时刻,附录 A.5):光晕扩散 → 双头像相向碰撞 →
/// 粒子飘散 → 文案按钮。全程 ~1100ms 有限动画;点击任意处直达完成帧;
/// 「减弱动态效果」直接呈现完成帧。无循环动画(pumpAndSettle 可 settle)。
class MatchOverlay extends StatefulWidget {
  const MatchOverlay({
    super.key,
    required this.candidate,
    this.myAvatarUrl,
    required this.onClose,
    this.onGoChat,
  });

  final Candidate candidate;
  final String? myAvatarUrl;
  final VoidCallback onClose;

  /// 有值才显示「去聊天」按钮。
  final VoidCallback? onGoChat;

  @override
  State<MatchOverlay> createState() => _MatchOverlayState();
}

class _MatchOverlayState extends State<MatchOverlay> with SingleTickerProviderStateMixin {
  static const _total = Duration(milliseconds: 1100);

  late final AnimationController _c = AnimationController(vsync: this, duration: _total);
  bool _started = false;

  // 分段(0–1 比例 × 1100ms:0–550 光晕 / 150–550 头像 / 500–800 爆发 /
  // 500–750 心形 / 600–1100 粒子 / 800–1100 文案按钮)
  late final Animation<double> _halo =
      CurvedAnimation(parent: _c, curve: const Interval(0, .5, curve: Curves.easeOutCubic));
  late final Animation<double> _avatars =
      CurvedAnimation(parent: _c, curve: const Interval(.136, .5, curve: Curves.easeOutCubic));
  late final Animation<double> _burst =
      CurvedAnimation(parent: _c, curve: const Interval(.455, .73));
  late final Animation<double> _heart =
      CurvedAnimation(parent: _c, curve: const Interval(.455, .68, curve: Curves.easeOutBack));
  late final Animation<double> _particles =
      CurvedAnimation(parent: _c, curve: const Interval(.545, 1));
  late final Animation<double> _text =
      CurvedAnimation(parent: _c, curve: const Interval(.727, 1, curve: Curves.easeOutCubic));

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_started) return;
    _started = true;
    if (MediaQuery.disableAnimationsOf(context)) {
      _c.value = 1;
    } else {
      _c.forward();
    }
  }

  void _skip() => _c.value = 1; // value setter 内部会 stop

  @override
  Widget build(BuildContext context) {
    final theirAvatarUrl =
        widget.candidate.photos.isEmpty ? null : widget.candidate.photos.first.url;
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: _skip,
        child: AnimatedBuilder(
          animation: _c,
          builder: (context, _) => Stack(
            children: [
              Center(
                child: SizedBox.square(
                  dimension: 280,
                  child: Stack(
                    alignment: Alignment.center,
                    clipBehavior: Clip.none,
                    children: [
                      // 光晕(从双头像位置扩散)
                      Opacity(
                        opacity: _halo.value * 0.9,
                        child: Container(
                          width: 130 + 150 * _halo.value,
                          height: 130 + 150 * _halo.value,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            gradient: RadialGradient(
                              colors: [
                                AppColors.brand.withValues(alpha: 0.55),
                                AppColors.heartOrange.withValues(alpha: 0.28),
                                Colors.transparent,
                              ],
                            ),
                          ),
                        ),
                      ),
                      // 碰撞爆发环
                      Opacity(
                        opacity: 1 - _burst.value,
                        child: Container(
                          width: 120 + 140 * _burst.value,
                          height: 120 + 140 * _burst.value,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            border: Border.all(
                              color: AppColors.brand.withValues(alpha: 0.65),
                              width: 2,
                            ),
                          ),
                        ),
                      ),
                      // 粒子飘散
                      Positioned.fill(
                        child: CustomPaint(
                          painter: MatchParticlesPainter(progress: _particles.value),
                        ),
                      ),
                      // 双头像相向滑入(定格圆心间距 66)
                      Transform.translate(
                        offset: Offset(-33 - 56 * (1 - _avatars.value), 0),
                        child: AppAvatar(imageUrl: widget.myAvatarUrl, size: 96, halo: true),
                      ),
                      Transform.translate(
                        offset: Offset(33 + 56 * (1 - _avatars.value), 0),
                        child: AppAvatar(imageUrl: theirAvatarUrl, size: 96, halo: true),
                      ),
                      // 心形弹出(0.6 → 1,easeOutBack 自带过冲 ~1.1)
                      Transform.scale(
                        scale: 0.6 + 0.4 * _heart.value,
                        child: Icon(
                          Icons.favorite_rounded,
                          size: 30,
                          color: AppColors.brand,
                          shadows: [
                            Shadow(
                              color: AppColors.brand.withValues(alpha: 0.8),
                              blurRadius: 18,
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              Align(
                alignment: Alignment.bottomCenter,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(
                      AppSpacing.xxl, 0, AppSpacing.xxl, 48),
                  child: Opacity(
                    opacity: _text.value,
                    child: Transform.translate(
                      offset: Offset(0, 8 * (1 - _text.value)),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            '你们已互相喜欢',
                            style: AppText.title.copyWith(color: Colors.white),
                          ),
                          const SizedBox(height: AppSpacing.sm),
                          Text(
                            '和 ${widget.candidate.nickname} 打个招呼吧',
                            style: AppText.caption.copyWith(
                                color: Colors.white.withValues(alpha: 0.72)),
                          ),
                          const SizedBox(height: AppSpacing.xxl),
                          Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              if (widget.onGoChat != null) ...[
                                AppButton(
                                  key: const Key('match.goChat'),
                                  label: '去聊天',
                                  onPressed: widget.onGoChat,
                                ),
                                const SizedBox(width: AppSpacing.md),
                              ],
                              AppButton(
                                key: const Key('match.continue'),
                                label: '继续滑卡',
                                variant: AppButtonVariant.secondary,
                                onPressed: widget.onClose,
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 弹配对动效;等它关闭后 future 才完成。
Future<void> showMatchOverlay(
  BuildContext context, {
  required Candidate candidate,
  String? myAvatarUrl,
  VoidCallback? onGoChat,
}) =>
    showGeneralDialog<void>(
      context: context,
      barrierDismissible: false,
      barrierLabel: '配对成功',
      barrierColor: AppColors.text1.withValues(alpha: 0.94),
      transitionDuration: AppMotion.base,
      pageBuilder: (dialogContext, animation, secondary) => MatchOverlay(
        candidate: candidate,
        myAvatarUrl: myAvatarUrl,
        onClose: () => Navigator.of(dialogContext).pop(),
        // 先关弹层再跳,不然路由推在弹层下面
        onGoChat: onGoChat == null
            ? null
            : () {
                Navigator.of(dialogContext).pop();
                onGoChat();
              },
      ),
      transitionBuilder: (context, animation, secondary, child) =>
          FadeTransition(opacity: animation, child: child),
    );
```

- [ ] **Step 4: 测试 + analyze**

Run: `../flutter/bin/flutter.bat test test/features/discovery/ && ../flutter/bin/flutter.bat analyze`
Expected: 全过(含 `discovery_page_test` 的「互相喜欢 → 弹配对动效」——有限编排 + pumpAndSettle 可达完成帧);`No issues found!`

- [ ] **Step 5: Commit**

```bash
git add app/lib/features/discovery/widgets/match_particles.dart app/lib/features/discovery/widgets/match_overlay.dart app/test/features/discovery/match_overlay_test.dart
git commit -m "feat(ui): 配对情感时刻完整编排——光晕/碰撞/粒子/可跳过(§6.2,附录 A.5)"
```

---

### Task 11: DiscoveryPage 页壳(大标题/骨架/错误/空态/引导)+ AppButton 内边距

**Files:**
- Modify: `app/lib/core/widgets/app_button.dart`(补水平内边距,1 行)
- Modify: `app/lib/features/discovery/discovery_page.dart`(整文件重写)
- Test: `app/test/features/discovery/discovery_page_test.dart`(追加 2 用例;既有 5 用例不动)
- 检查: `app/test/core/widgets/app_button_test.dart`(不动,确认仍绿)

**Interfaces:**
- Consumes: `DeckSkeleton`(Task 7)、`HeartRipple`(Task 5)、`AppEmptyState.mark`(Task 6)、`AppButton.secondary`、`ApiException`
- Produces: 页面无 AppBar;标题文案「发现」;key `discovery.refresh`/`discovery.goOnboarding` 不变;「重试」文案不变

- [ ] **Step 1: AppButton 补水平内边距(独立小组件修复)**

`app_button.dart` 的 `Container(height: 52, alignment: Alignment.center, decoration: decoration, child: Text(...))` 构造函数加一行参数:

```dart
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xxl),
```

(顶部补 `import '../theme/app_spacing.dart';`。原因:无内边距时按钮在宽松约束下宽=文字宽,贴字难看;组件级修复,既有测试无宽度断言。)

Run: `cd app && ../flutter/bin/flutter.bat test test/core/widgets/app_button_test.dart && ../flutter/bin/flutter.bat analyze`
Expected: 全过;`No issues found!`

- [ ] **Step 2: 追加页面失败测试**

`discovery_page_test.dart` main 内追加(顶部补 import:`package:chatapp_app/core/widgets/heart_ripple.dart`):

```dart
  testWidgets('空态用涟漪元素与主按钮「刷新」', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /discovery/candidates': (options) => ok([]),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(find.byType(HeartRipple), findsOneWidget);
    expect(find.text('附近暂时没有新的人了'), findsOneWidget);
    expect(find.byKey(const Key('discovery.refresh')), findsOneWidget);
  });

  testWidgets('资料未完善 → 引导态展示欠缺项与「去完善」', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) =>
          ok(profileJson(missing: ['nickname', 'birthday'])),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(find.text('完善资料后就能开始滑卡'), findsOneWidget);
    expect(find.textContaining('还差:'), findsOneWidget);
    expect(find.byKey(const Key('discovery.goOnboarding')), findsOneWidget);
  });
```

Run: `../flutter/bin/flutter.bat test test/features/discovery/discovery_page_test.dart`
Expected: 第一个新用例 FAIL(`HeartRipple` 尚未接入);第二个用例此时可能即过(旧实现已有该文案与 key),它作为改写后的回归护栏保留。

- [ ] **Step 3: 重写 `discovery_page.dart`**

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_empty_state.dart';
import '../../core/widgets/heart_ripple.dart';
import '../chat/match_cache.dart';
import '../presence/presence_controller.dart';
import '../profile/models.dart';
import '../profile/profile_controller.dart';
import 'discovery_controller.dart';
import 'models.dart';
import 'widgets/deck_skeleton.dart';
import 'widgets/match_overlay.dart';
import 'widgets/swipe_deck.dart';

/// 错误统一取 ApiException 的中文 message(不显示裸异常串)。
String _messageOf(Object error) =>
    error is ApiException ? error.message : '加载失败,稍后再试';

class DiscoveryPage extends ConsumerWidget {
  const DiscoveryPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profile = ref.watch(profileProvider);
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.pageH, AppSpacing.lg, AppSpacing.pageH, AppSpacing.md),
              child: Text('发现', style: AppText.display.copyWith(color: AppColors.text1)),
            ),
            Expanded(
              child: profile.when(
                loading: () => const DeckSkeleton(),
                error: (error, _) => _ErrorView(
                  message: _messageOf(error),
                  onRetry: () => ref.read(profileProvider.notifier).reload(),
                ),
                data: (data) => data.isComplete
                    ? const _DeckView()
                    : _IncompleteView(profile: data),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 资料不全时不能滑卡,先把人引去向导。
class _IncompleteView extends StatelessWidget {
  const _IncompleteView({required this.profile});

  final Profile profile;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xxl),
        child: AppEmptyState(
          mark: const HeartRipple(),
          title: '完善资料后就能开始滑卡',
          description: '还差:${profile.missingFields.map(missingFieldLabel).join('、')}',
          action: AppButton(
            key: const Key('discovery.goOnboarding'),
            label: '去完善',
            onPressed: () => context.go('/onboarding'),
          ),
        ),
      ),
    );
  }
}

class _DeckView extends ConsumerWidget {
  const _DeckView();

  Future<bool> _decide(BuildContext context, WidgetRef ref, Candidate candidate,
      {required bool like}) async {
    try {
      final matched =
          await ref.read(discoveryProvider.notifier).decide(candidate, like: like);
      if (matched && context.mounted) {
        final me = ref.read(profileProvider).value;
        ref.invalidate(matchCacheProvider); // 刚配对的人,昵称/头像要立刻能显示
        await showMatchOverlay(
          context,
          candidate: candidate,
          myAvatarUrl: me?.avatar?.url,
          onGoChat: () => context.push('/chat/u${candidate.userId}'),
        );
      }
      return matched;
    } on ApiException catch (error) {
      if (context.mounted) {
        ScaffoldMessenger.of(context)
          ..hideCurrentSnackBar()
          ..showSnackBar(SnackBar(content: Text(error.message)));
      }
      return false;
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final deck = ref.watch(discoveryProvider);
    final presenceById = ref.watch(presenceProvider);
    return deck.when(
      loading: () => const DeckSkeleton(),
      error: (error, _) => _ErrorView(
        message: _messageOf(error),
        onRetry: () => ref.read(discoveryProvider.notifier).reload(),
      ),
      data: (candidates) {
        ref.read(presenceProvider.notifier).track(
            'discovery', [for (final candidate in candidates) candidate.userId]);
        return candidates.isEmpty
            ? _EmptyView(
                onRefresh: () => ref.read(discoveryProvider.notifier).reload())
            : SwipeDeck(
                candidates: candidates,
                presenceById: presenceById,
                onDecide: (candidate, {required like}) =>
                    _decide(context, ref, candidate, like: like),
              );
      },
    );
  }
}

class _EmptyView extends StatelessWidget {
  const _EmptyView({required this.onRefresh});

  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xxl),
        child: AppEmptyState(
          mark: const HeartRipple(),
          title: '附近暂时没有新的人了',
          description: '过会儿再来看看吧',
          action: AppButton(
            key: const Key('discovery.refresh'),
            label: '刷新',
            onPressed: onRefresh,
          ),
        ),
      ),
    );
  }
}

/// 加载失败:中文提示 + 次按钮重试(不显示裸异常串)。
class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xxl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('没能加载出来', style: AppText.subtitle.copyWith(fontSize: 17)),
            const SizedBox(height: AppSpacing.sm),
            Text(
              message,
              textAlign: TextAlign.center,
              style: AppText.caption.copyWith(color: AppColors.text2),
            ),
            const SizedBox(height: AppSpacing.lg),
            AppButton(
              label: '重试',
              variant: AppButtonVariant.secondary,
              onPressed: onRetry,
            ),
          ],
        ),
      ),
    );
  }
}
```

- [ ] **Step 4: 测试 + analyze**

Run: `../flutter/bin/flutter.bat test test/features/discovery/ && ../flutter/bin/flutter.bat test test/features/shell/ && ../flutter/bin/flutter.bat analyze`
Expected: 全过(既有 5 用例:卡片文字/空态文案/重试/配对/滑卡失败均保持;shell 用例的 navTab 不受标题影响);`No issues found!`

- [ ] **Step 5: Commit**

```bash
git add app/lib/core/widgets/app_button.dart app/lib/features/discovery/discovery_page.dart app/test/features/discovery/discovery_page_test.dart
git commit -m "feat(ui): 发现页页壳——大标题/骨架屏/涟漪空态/错误态/引导态(§5.2/§7)"
```

---

### Task 12: 全量回归 + 手测 + 合并收尾

**Files:** 无(验证与收尾;可能微调观感参数)

- [ ] **Step 1: 全量回归**

Run: `cd app && ../flutter/bin/flutter.bat analyze && ../flutter/bin/flutter.bat test`
Expected: 零告警 + 全量绿(220 基线 + 新增/更新用例)。

- [ ] **Step 2: 模拟器手测(先与用户确认模拟器状态)**

```bash
cd app && ../flutter/bin/flutter.bat run -d emulator-5554 --dart-define=API_BASE=http://<SERVER_IP>/api/v1
```

(连测试服务器;若模拟器状态不佳参考 `docs/pitfalls/android-emulator.md`,冷启动前先问用户。)

检查清单(开发侧先过一遍,再请用户亲测):
- 页壳:冷启动骨架屏 → 卡片;大标题「发现」位置与字号
- 卡面:胶囊点指示(点左右切照片,当前张拉长);在线绿点呼吸;离线显示「x 分钟前在线」;标签/简介叠字对比度;浅色照片下的可读性
- 操作区:两圆钮样式;点喜欢按钮脉冲;滑卡拖拽/飞出/第二张缩放
- 配对:双模拟器互喜触发完整编排(光晕/碰撞/粒子/文案);动画中任意点击直达完成帧;「去聊天」/「继续滑卡」行为不变
- 错误态:把 `--dart-define=API_BASE` 指到一个不通的地址(如 `http://10.0.2.2:8000/api/v1`)看错误态文案与「重试」
- 空态:把候选人划完(或临时用小号)看涟漪空态与「刷新」
- 资料未完善:新号登录看引导态
- 系统开发者选项「移除动画」开启时:配对弹层直接呈现完成帧

截图留存:`"$LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe" -s emulator-5554 exec-out screencap -p > shot_xxx.png`

- [ ] **Step 3: 观感微调(如需)**

若手测发现间距/字号/对比度问题:只调本批文件的 token 使用与常量,不动规则文档;改后重跑 Step 1。

- [ ] **Step 4: 合并收尾**

```bash
git checkout master && git merge --ff-only ui/batch2 && git branch -d ui/batch2 && git push origin master
```

- [ ] **Step 5: 更新 CLAUDE.md**

- 里程碑表追加一行:`| 2026-09-19 | UI 整改批次②「发现页」交付(页壳/卡面/圆钮/配对情感时刻;测试数更新) |`
- 「UI 设计规则」节的批次顺序句更新:②发现 已交付,下一批 ③消息/聊天。
提交推送。

---

## 完成后状态(供验收对照)

- 发现页:大标题页壳 + 四态(骨架/空态/错误/引导)全部走「心跳」组件与 token
- 卡面:R24 + scrim 叠字 + 胶囊点 + 呼吸在线点 + 新排版
- 操作区:56/64 圆钮 + 按压 .96 + 喜欢脉冲
- 配对:完整五段编排 + 粒子 + 点击跳过 + 减弱动效直达完成帧
- core 层:+2 token、+BreathingDot(提炼)、+HeartRipple、+DeckSkeleton、AppEmptyState.mark、AppButton 内边距
- 规则文档 v1.1 附录 A 落笔;测试全绿 + analyze 零告警;其他页面零改动
