# UI 整改批次①(底座 + 底栏)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按「心跳」设计规则落地主题底座(token/theme/通用组件)+ 字体 + 悬浮胶囊底栏,页面内部布局不动。

**Architecture:** 新增 `app/lib/core/theme/`(常量类)与 `app/lib/core/widgets/`(通用组件);`app.dart` 接入 `buildAppTheme()`;`home_shell` 的 Material `NavigationBar` 换成自绘 `AppBottomBar`(仍占 `bottomNavigationBar` 槽位,页面零改动)。

**Tech Stack:** Flutter 3.47(`../flutter/bin/flutter.bat`)、Riverpod、现有 widget 测试体系(真实 provider + 假网络)。

**Spec:** `docs/superpowers/specs/2026-09-18-ui-revamp-batch1-design.md`;视觉细节一律以「心跳」规则 `docs/superpowers/specs/2026-09-15-ui-design-language-design.md` 为准。

## Global Constraints

- 所有 flutter 命令 cwd = `app/`,用 `../flutter/bin/flutter.bat`(Windows)。
- 新代码**禁止裸 hex / 裸字号 / 裸间距 / 裸圆角**,一律从 `core/theme` token 取(规则 §1 铁律 3;token 文件本身除外)。
- 除 `home_shell.dart` 外,**不改任何页面代码**;不迁移页面既有 SnackBar/空态/骨架屏用法。
- 每步全绿再进下一步:改完必跑 `flutter analyze`(零告警)+ 相关测试;标了「全量」的步骤跑全量 `flutter test`。
- 含无限动画的组件(骨架屏/在线点呼吸)测试**不用 `pumpAndSettle`**,用有限 `pump`(见 `docs/pitfalls/testing.md`)。
- 代码提交在分支 `ui/batch1`;完成手测后 ff 合并 master、删分支、push origin(计划文档本身直接提交 master)。
- 手测连服务器 `http://<SERVER_IP>/api/v1`(不用起本地后端);**动模拟器前先与用户确认**。

---

### Task 1: 基线确认 + 建分支

**Files:** 无(仅环境)

- [x] **Step 1: 确认 analyze 基线**

Run: `cd app && ../flutter/bin/flutter.bat analyze`
Expected: `No issues found!`

- [x] **Step 2: 跑全量测试基线并记录数量**

Run: `../flutter/bin/flutter.bat test`
Expected: 全部通过;记录 `All tests passed` 前的用例数,作为本批对照基准。

- [x] **Step 3: 建分支**

Run: `git checkout -b ui/batch1`
(在仓库根:工作目录 `app/` 的上一级)

---

### Task 2: 字体资源 + pubspec

**Files:**
- Create: `app/assets/fonts/SpaceGrotesk-Regular.ttf`、`SpaceGrotesk-Medium.ttf`、`SpaceGrotesk-Bold.ttf`、`OFL.txt`
- Modify: `app/pubspec.yaml`

**Interfaces:**
- Produces: 字体族名 `SpaceGrotesk`(w400/500/700),供 Task 4 全局字体使用。

- [x] **Step 1: 下载字体(4 个文件,来源已验证 200)**

```bash
cd app && mkdir -p assets/fonts && cd assets/fonts
BASE="https://cdn.jsdelivr.net/gh/floriankarsten/space-grotesk@master"
curl -fL -o SpaceGrotesk-Regular.ttf "$BASE/fonts/ttf/static/SpaceGrotesk-Regular.ttf"
curl -fL -o SpaceGrotesk-Medium.ttf  "$BASE/fonts/ttf/static/SpaceGrotesk-Medium.ttf"
curl -fL -o SpaceGrotesk-Bold.ttf    "$BASE/fonts/ttf/static/SpaceGrotesk-Bold.ttf"
curl -fL -o OFL.txt                  "$BASE/OFL.txt"
ls -la   # 三个 ttf 各 ~90–110KB,OFL.txt 非空
```

- [x] **Step 2: pubspec 声明字体与资源**

`app/pubspec.yaml` 的 `flutter:` 节(`uses-material-design: true` 之后)追加:

```yaml
  fonts:
    - family: SpaceGrotesk
      fonts:
        - asset: assets/fonts/SpaceGrotesk-Regular.ttf
          weight: 400
        - asset: assets/fonts/SpaceGrotesk-Medium.ttf
          weight: 500
        - asset: assets/fonts/SpaceGrotesk-Bold.ttf
          weight: 700
  assets:
    - assets/fonts/OFL.txt
```

- [x] **Step 3: 验证**

Run: `cd app && ../flutter/bin/flutter.bat pub get && ../flutter/bin/flutter.bat analyze`
Expected: pub get 成功、`No issues found!`(字体视觉验证在 Task 9 手测)

- [x] **Step 4: Commit**

```bash
git add app/assets/fonts app/pubspec.yaml
git commit -m "feat(ui): 打包 Space Grotesk 字体(400/500/700 + OFL)"
```

---

### Task 3: token 常量文件(色/渐变/间距/圆角/动效/阴影)

**Files:**
- Create: `app/lib/core/theme/app_colors.dart`、`app_gradients.dart`、`app_spacing.dart`、`app_radius.dart`、`app_motion.dart`、`app_shadows.dart`
- Test: `app/test/core/theme/tokens_test.dart`

**Interfaces:**
- Produces: `AppColors.*`、`AppGradients.heart/.system`、`AppSpacing.*`、`AppRadius.*`、`AppMotion.*`、`AppShadows.card/.floatingBar/.primaryButton` —— 后续所有任务消费。

- [x] **Step 1: 先写断言测试(fail)**

`app/test/core/theme/tokens_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_colors.dart';
import 'package:chatapp_app/core/theme/app_gradients.dart';
import 'package:chatapp_app/core/theme/app_motion.dart';
import 'package:chatapp_app/core/theme/app_radius.dart';

void main() {
  test('色板与规则 §2.1 一致', () {
    expect(AppColors.brand, const Color(0xFFFF2C55));
    expect(AppColors.text1, const Color(0xFF16181D));
    expect(AppColors.bgPage, const Color(0xFFF6F7FB));
    expect(AppColors.divider, const Color(0xFFEEF0F4));
  });

  test('心跳渐变 135° 双色', () {
    expect(AppGradients.heart.colors, [AppColors.brand, AppColors.heartOrange]);
    expect(AppGradients.heart.begin, Alignment.topLeft);
    expect(AppGradients.heart.end, Alignment.bottomRight);
  });

  test('圆角与动效档位', () {
    expect(AppRadius.card, 20);
    expect(AppRadius.sheet, 24);
    expect(AppMotion.fast.inMilliseconds, 150);
    expect(AppMotion.medium.inMilliseconds, 320);
  });
}
```

Run: `cd app && ../flutter/bin/flutter.bat test test/core/theme/tokens_test.dart`
Expected: 编译失败(`app_colors.dart` 不存在)

- [x] **Step 2: 实现六个 token 文件**

`app_colors.dart`:

```dart
import 'package:flutter/material.dart';

/// 「心跳」规则 §2.1 色板。新代码禁止裸 hex,一律从这里取。
abstract final class AppColors {
  static const brand = Color(0xFFFF2C55);
  static const violet = Color(0xFF7C5CFF);
  static const green = Color(0xFF12C48B);
  static const amber = Color(0xFFFFB020);
  static const text1 = Color(0xFF16181D);
  static const text2 = Color(0xFF8A8F9E);
  static const text3 = Color(0xFFB3B7C0);
  static const divider = Color(0xFFEEF0F4);
  static const bgPage = Color(0xFFF6F7FB);
  static const bgCard = Color(0xFFFFFFFF);
  static const danger = Color(0xFFFA5151);
  static const success = green;
  static const warning = amber;
  static const heartOrange = Color(0xFFFF7A45); // 渐变终点(§2.2 可微调)
  static const systemBlue = Color(0xFF4F8CFF);
}
```

`app_gradients.dart`:

```dart
import 'package:flutter/material.dart';

import 'app_colors.dart';

/// 「心跳」规则 §2.1 渐变(135° = 左上→右下)。
abstract final class AppGradients {
  static const heart = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [AppColors.brand, AppColors.heartOrange],
  );
  static const system = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [AppColors.violet, AppColors.systemBlue],
  );
}
```

`app_spacing.dart` / `app_radius.dart`:

```dart
/// 「心跳」规则 §5.1 间距(全为 4 的倍数)。
abstract final class AppSpacing {
  static const xs = 4.0;
  static const sm = 8.0;
  static const md = 12.0;
  static const lg = 16.0;
  static const xl = 20.0;
  static const xxl = 24.0;
  static const pageH = 16.0;    // 页面水平内边距
  static const cardGap = 12.0;  // 卡片之间
  static const sectionGap = 24.0; // 区块之间
}

/// 「心跳」规则 §5.1 圆角。
abstract final class AppRadius {
  static const card = 20.0;
  static const input = 16.0;
  static const chip = 8.0;
  static const sheet = 24.0;
  static const full = 999.0;
}
```

`app_motion.dart`:

```dart
import 'package:flutter/material.dart';

/// 「心跳」规则 §6.1 时长/曲线。
abstract final class AppMotion {
  static const fast = Duration(milliseconds: 150);
  static const base = Duration(milliseconds: 220);
  static const medium = Duration(milliseconds: 320);
  static const hero = Duration(milliseconds: 380);
  static const cinematic = Duration(milliseconds: 1200); // 900–1400 取中值
  static const loop = Duration(milliseconds: 1200);      // 呼吸循环
  static const easeOut = Curves.easeOutCubic;
  static const easeOutBack = Curves.easeOutBack;
}
```

`app_shadows.dart`(rgba 已折算为 0x 透明度):

```dart
import 'package:flutter/material.dart';

import 'app_colors.dart';

/// 「心跳」规则 §5.1 阴影预设。
abstract final class AppShadows {
  static const card = [
    BoxShadow(color: Color(0x0F16181D), offset: Offset(0, 6), blurRadius: 18), // rgba(22,24,29,.06)
  ];
  static const floatingBar = [
    BoxShadow(color: Color(0x1A16181D), offset: Offset(0, 10), blurRadius: 24), // rgba(22,24,29,.10)
  ];
  static const primaryButton = [
    BoxShadow(color: Color(0x59FF2C55), offset: Offset(0, 10), blurRadius: 24), // rgba(255,44,85,.35)
  ];
}
```

- [x] **Step 3: 测试通过**

Run: `cd app && ../flutter/bin/flutter.bat test test/core/theme/tokens_test.dart && ../flutter/bin/flutter.bat analyze`
Expected: 3 个用例过;`No issues found!`

- [x] **Step 4: Commit**

```bash
git add app/lib/core/theme app/test/core/theme/tokens_test.dart
git commit -m "feat(ui): 主题 token 底座——色板/渐变/间距/圆角/动效/阴影(规则 §2/§5/§6)"
```

---

### Task 4: 字阶 + 主题组装 + 全局接入

**Files:**
- Create: `app/lib/core/theme/app_typography.dart`、`app_theme.dart`
- Modify: `app/lib/app.dart`
- Test: `app/test/core/theme/app_theme_test.dart`

**Interfaces:**
- Consumes: `AppColors`/`AppRadius`/`AppShadows`(Task 3)
- Produces: `AppText.display/.title/.subtitle/.body/.caption/.micro/.badge/.navLabel/.navLabelSelected`;`buildAppTheme()` —— 后续组件与底栏消费。

- [x] **Step 1: 写主题测试(fail)**

`app/test/core/theme/app_theme_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_colors.dart';
import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/core/theme/app_typography.dart';

void main() {
  test('主题:全局 SpaceGrotesk + 页面底色 + SnackBar 深色浮层', () {
    final theme = buildAppTheme();
    expect(theme.scaffoldBackgroundColor, AppColors.bgPage);
    expect(theme.textTheme.bodyMedium?.fontFamily, 'SpaceGrotesk');
    expect(AppText.body.fontFamily, 'SpaceGrotesk');
    expect(AppText.body.fontFamilyFallback, contains('PingFang SC'));
    expect(theme.snackBarTheme.backgroundColor, const Color(0xEB16181D));
  });

  test('colorScheme 从 brand 派生', () {
    final theme = buildAppTheme();
    expect(theme.colorScheme.brightness, Brightness.light);
    // fromSeed 的 primary 是 brand 的色调派生,不是原值;只断言可区分于默认紫
    expect(theme.colorScheme.primary, isNot(equals(Colors.deepPurple)));
  });
}
```
(需要 `import 'package:flutter/material.dart';` 供 `Color`/`Colors`。)

Run: `cd app && ../flutter/bin/flutter.bat test test/core/theme/app_theme_test.dart`
Expected: 编译失败(`app_theme.dart` 不存在)

- [x] **Step 2: 实现 app_typography.dart**

```dart
import 'package:flutter/material.dart';

/// 「心跳」规则 §3:中文走系统字体 fallback,拉丁/数字走 Space Grotesk。
const kFontFallback = ['PingFang SC', 'MiSans', 'HarmonyOS Sans', 'sans-serif'];

TextStyle _sg({
  required double size,
  required FontWeight weight,
  double? spacing,
  double? height,
}) =>
    TextStyle(
      fontFamily: 'SpaceGrotesk',
      fontFamilyFallback: kFontFallback,
      fontSize: size,
      fontWeight: weight,
      letterSpacing: spacing,
      height: height,
    );

/// 规则 §3.2 字阶。
abstract final class AppText {
  static final display = _sg(size: 32, weight: FontWeight.w800, spacing: -0.64, height: 1.2); // -0.02em
  static final title = _sg(size: 20, weight: FontWeight.w700, spacing: -0.2, height: 1.2);    // -0.01em
  static final subtitle = _sg(size: 16, weight: FontWeight.w600, height: 1.2);
  static final body = _sg(size: 15, weight: FontWeight.w500, height: 1.45);
  static final caption = _sg(size: 13, weight: FontWeight.w400, height: 1.45);
  static final micro = _sg(size: 12, weight: FontWeight.w400);
  static final badge = _sg(size: 11, weight: FontWeight.w700);          // 角标专用
  static final navLabel = _sg(size: 10, weight: FontWeight.w400);       // 底栏未选中(§7)
  static final navLabelSelected = _sg(size: 10, weight: FontWeight.w700); // 底栏选中(§7)
}
```

- [x] **Step 3: 实现 app_theme.dart**

```dart
import 'package:flutter/material.dart';

import 'app_colors.dart';
import 'app_radius.dart';
import 'app_typography.dart';

/// 组装全局主题(规则 §8):colorScheme 从 brand 派生;全局字体;SnackBar 贴近 §7 Toast。
ThemeData buildAppTheme() {
  final base = ThemeData(
    colorScheme: ColorScheme.fromSeed(seedColor: AppColors.brand),
    useMaterial3: true,
    fontFamily: 'SpaceGrotesk',
    fontFamilyFallback: kFontFallback,
  );
  return base.copyWith(
    scaffoldBackgroundColor: AppColors.bgPage,
    snackBarTheme: SnackBarThemeData(
      backgroundColor: const Color(0xEB16181D), // rgba(22,24,29,.92)
      contentTextStyle: AppText.caption.copyWith(color: Colors.white),
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.input),
      ),
    ),
  );
}
```

- [x] **Step 4: app.dart 接入**

`app/lib/app.dart`:`theme: ThemeData(colorSchemeSeed: Colors.pink, useMaterial3: true),` 整行替换为 `theme: buildAppTheme(),`;文件头加 `import 'core/theme/app_theme.dart';`。

- [x] **Step 5: 新用例过 + 全量测试**

Run: `cd app && ../flutter/bin/flutter.bat test test/core/theme/ && ../flutter/bin/flutter.bat test`
Expected: 新增用例过;**全量绿**(主题变更影响所有 widget 测试,必须全量)。

- [x] **Step 6: Commit**

```bash
git add app/lib/core/theme app/lib/app.dart app/test/core/theme/app_theme_test.dart
git commit -m "feat(ui): 字阶 + buildAppTheme 组装并全局接入(§3/§8)"
```

---

### Task 5: 组件三件套 AppButton / AppCard / GradientIcon

**Files:**
- Create: `app/lib/core/widgets/app_button.dart`、`app_card.dart`、`gradient_icon.dart`
- Test: `app/test/core/widgets/app_button_test.dart`、`app_card_test.dart`、`gradient_icon_test.dart`

**Interfaces:**
- Consumes: Task 3/4 全部 token
- Produces: `AppButton(label:, onPressed:, variant:)`、`AppCard(child:, onTap:)`、`GradientIcon(icon:, size:, gradient:)`

- [x] **Step 1: 写测试(fail)**

`app_button_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_button.dart';

void main() {
  testWidgets('主按钮可点且回调触发', (tester) async {
    var taps = 0;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: AppButton(label: '开始', onPressed: () => taps++)),
    ));
    await tester.tap(find.text('开始'));
    expect(taps, 1);
  });

  testWidgets('onPressed 为 null → 禁用不可点', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: AppButton(label: '禁用', onPressed: null)),
    ));
    final bt = tester.widget<AppButton>(find.byType(AppButton));
    expect(bt.onPressed, isNull);
  });
}
```

`app_card_test.dart`:白底 R20、onTap 触发;
`gradient_icon_test.dart`:渲染 `find.byType(GradientIcon)` 且内部有 Icon。

(三个文件写法同构,断言"渲染 + 关键交互",不测像素。)

Run: `cd app && ../flutter/bin/flutter.bat test test/core/widgets/`
Expected: 编译失败(组件不存在)

- [x] **Step 2: 实现三组件**

`app_button.dart`(要点:高 52、按压 scale .96 用 `AnimatedScale`(fast)、四型样式、禁用态):

```dart
import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_gradients.dart';
import '../theme/app_motion.dart';
import '../theme/app_radius.dart';
import '../theme/app_shadows.dart';
import '../theme/app_typography.dart';

enum AppButtonVariant { primary, secondary, text, danger }

/// 「心跳」规则 §7 按钮:高 52 胶囊;按压 scale .96。
class AppButton extends StatefulWidget {
  const AppButton({super.key, required this.label, this.onPressed, this.variant = AppButtonVariant.primary});

  final String label;
  final VoidCallback? onPressed;
  final AppButtonVariant variant;

  @override
  State<AppButton> createState() => _AppButtonState();
}

class _AppButtonState extends State<AppButton> {
  var _pressed = false;

  @override
  Widget build(BuildContext context) {
    final disabled = widget.onPressed == null;
    var (decoration, textStyle) = switch (widget.variant) {
      AppButtonVariant.primary => (
          BoxDecoration(
            gradient: disabled ? null : AppGradients.heart,
            color: disabled ? AppColors.divider : null,
            borderRadius: BorderRadius.circular(AppRadius.full),
            boxShadow: disabled ? null : AppShadows.primaryButton,
          ),
          AppText.body.copyWith(color: Colors.white, fontWeight: FontWeight.w700),
        ),
      AppButtonVariant.secondary => (
          BoxDecoration(
            color: AppColors.bgCard,
            borderRadius: BorderRadius.circular(AppRadius.full),
            border: Border.all(color: AppColors.divider),
          ),
          AppText.body.copyWith(color: AppColors.text1, fontWeight: FontWeight.w600),
        ),
      AppButtonVariant.text => (
          const BoxDecoration(),
          AppText.body.copyWith(color: AppColors.brand, fontWeight: FontWeight.w600),
        ),
      AppButtonVariant.danger => (
          BoxDecoration(
            borderRadius: BorderRadius.circular(AppRadius.full),
            border: Border.all(color: AppColors.danger),
          ),
          AppText.body.copyWith(color: AppColors.danger, fontWeight: FontWeight.w600),
        ),
    };
    if (disabled) textStyle = textStyle.copyWith(color: AppColors.text3);

    return GestureDetector(
      onTapDown: disabled ? null : (_) => setState(() => _pressed = true),
      onTapUp: disabled ? null : (_) => setState(() => _pressed = false),
      onTapCancel: disabled ? null : () => setState(() => _pressed = false),
      onTap: widget.onPressed,
      child: AnimatedScale(
        scale: _pressed ? 0.96 : 1,
        duration: AppMotion.fast,
        child: Container(
          height: 52,
          alignment: Alignment.center,
          decoration: decoration,
          child: Text(widget.label, style: textStyle),
        ),
      ),
    );
  }
}
```
注意:禁用态在解构后用 `textStyle = textStyle.copyWith(color: AppColors.text3);` 覆写(故用 `var` 解构)。

`app_card.dart`(白底 R20 内边距 16 + 浮卡阴影 + 可选 onTap scale .98):
结构同 AppButton:GestureDetector + AnimatedScale(.98) + Container(decoration: BoxDecoration(color: bgCard, borderRadius: card, boxShadow: AppShadows.card), padding: EdgeInsets.all(AppSpacing.lg), child)。

`gradient_icon.dart`:

```dart
class GradientIcon extends StatelessWidget {
  const GradientIcon(this.icon, {super.key, this.size = 22, this.gradient = AppGradients.heart});
  final IconData icon;
  final double size;
  final Gradient gradient;

  @override
  Widget build(BuildContext context) => ShaderMask(
        blendMode: BlendMode.srcIn,
        shaderCallback: (rect) => gradient.createShader(rect),
        child: Icon(icon, size: size, color: Colors.white),
      );
}
```

- [x] **Step 3: 测试过 + analyze**

Run: `cd app && ../flutter/bin/flutter.bat test test/core/widgets/ && ../flutter/bin/flutter.bat analyze`

- [x] **Step 4: Commit**

```bash
git add app/lib/core/widgets app/test/core/widgets
git commit -m "feat(ui): 通用组件 AppButton/AppCard/GradientIcon(§7)"
```

---

### Task 6: AppAvatar / AppBadge

**Files:**
- Create: `app/lib/core/widgets/app_avatar.dart`、`app_badge.dart`
- Test: `app/test/core/widgets/app_avatar_test.dart`、`app_badge_test.dart`

**Interfaces:**
- Produces: `AppAvatar(imageUrl:, size:, halo:, showOnlineDot:, dotBorderColor:)`、`AppBadge(count:)`(count≤0 不渲染任何东西)——Task 8 底栏消费 AppBadge。

- [x] **Step 1: 写测试(fail)**

`app_badge_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:chatapp_app/core/widgets/app_badge.dart';

Widget wrap(Widget child) => MaterialApp(home: Scaffold(body: Center(child: child)));

void main() {
  testWidgets('显示数字;≥100 显示 99+', (tester) async {
    await tester.pumpWidget(wrap(const AppBadge(count: 3)));
    expect(find.text('3'), findsOneWidget);

    await tester.pumpWidget(wrap(const AppBadge(count: 120)));
    expect(find.text('99+'), findsOneWidget);
  });

  testWidgets('count≤0 不渲染内容', (tester) async {
    await tester.pumpWidget(wrap(const AppBadge(count: 0)));
    expect(find.byType(Text), findsNothing);
  });
}
```

`app_avatar_test.dart`:圆形渲染;`showOnlineDot: true` 时出现在线点(find.byKey(const Key('avatar.onlineDot')));**用 `pump()` 有限推进,禁止 pumpAndSettle**(呼吸动画)。

Run: `cd app && ../flutter/bin/flutter.bat test test/core/widgets/`
Expected: 编译失败(组件不存在)

- [x] **Step 2: 实现 app_badge.dart**

```dart
import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_gradients.dart';
import '../theme/app_shadows.dart';
import '../theme/app_typography.dart';

/// 「心跳」规则 §7 角标:渐变胶囊;min 18×18;≥100 → 99+。
class AppBadge extends StatelessWidget {
  const AppBadge({super.key, required this.count});
  final int count;

  @override
  Widget build(BuildContext context) {
    if (count <= 0) return const SizedBox.shrink();
    return Container(
      constraints: const BoxConstraints(minWidth: 18, minHeight: 18),
      padding: const EdgeInsets.symmetric(horizontal: 5),
      alignment: Alignment.center,
      decoration: BoxDecoration(
        gradient: AppGradients.heart,
        borderRadius: BorderRadius.circular(9),
        boxShadow: AppShadows.primaryButton,
      ),
      child: Text(
        count >= 100 ? '99+' : '$count',
        style: AppText.badge.copyWith(color: Colors.white),
      ),
    );
  }
}
```

- [x] **Step 3: 实现 app_avatar.dart**

要点:圆形(ClipOval)尺寸档 28/32/40/48/56/96;`imageUrl` 为空或加载失败 → `divider` 底 + `person_rounded` 占位(必须带 `errorBuilder`,假网络对图片一律 400,见 pitfalls/testing);`halo` 光晕环 = 渐变圆底 + 2.5px 间隙(间隙色 `dotBorderColor`,默认白);在线点:

```dart
class _BreathingDot extends StatefulWidget {
  const _BreathingDot({required this.size, required this.borderColor});
  final double size;
  final Color borderColor;
  @override
  State<_BreathingDot> createState() => _BreathingDotState();
}

class _BreathingDotState extends State<_BreathingDot> with SingleTickerProviderStateMixin {
  late final _c = AnimationController(vsync: this, duration: AppMotion.loop)..repeat(reverse: true);

  @override
  void dispose() { _c.dispose(); super.dispose(); }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _c,
        builder: (context, _) => Opacity(
          opacity: 0.55 + 0.45 * _c.value, // 呼吸:透明度 .55↔1
          child: Container(
            key: const Key('avatar.onlineDot'),
            width: widget.size, height: widget.size,
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

组件签名:

```dart
class AppAvatar extends StatelessWidget {
  const AppAvatar({super.key, this.imageUrl, this.size = 48, this.halo = false,
      this.showOnlineDot = false, this.dotBorderColor = Colors.white});
  ...
}
```
布局:`Stack`(头像 + `Positioned(right: 0, bottom: 0, child: dot)`);halo 时外层再包 `Container(padding: 2.5, decoration: 渐变圆, child: Container(padding: 2, decoration: 圆(色=dotBorderColor), child: 头像))`。在线点尺寸:size ≥ 48 → 11,否则 8(§5.3)。

- [x] **Step 4: 测试过 + analyze**

Run: `cd app && ../flutter/bin/flutter.bat test test/core/widgets/ && ../flutter/bin/flutter.bat analyze`

- [x] **Step 5: Commit**

```bash
git add app/lib/core/widgets app/test/core/widgets
git commit -m "feat(ui): AppAvatar(光晕环/在线点)与 AppBadge(§5.3/§7)"
```

---

### Task 7: AppSkeleton / AppEmptyState / AppToast

**Files:**
- Create: `app/lib/core/widgets/app_skeleton.dart`、`app_empty_state.dart`、`app_toast.dart`
- Test: `app/test/core/widgets/app_skeleton_test.dart`、`app_empty_state_test.dart`、`app_toast_test.dart`

**Interfaces:**
- Produces: `AppSkeleton(width:, height:, radius:)`、`AppEmptyState(emoji:, title:, description:, action:)`、`AppToast.show(context, message)`

- [x] **Step 1: 写测试(fail)**

`app_skeleton_test.dart`:渲染 `AppSkeleton(width: 100, height: 12)` 出现;透明度随时间变化——用 `pump(Duration(milliseconds: 600))` 两次比较 Opacity 值不同(**禁 pumpAndSettle**)。

`app_empty_state_test.dart`:emoji/标题/说明/主按钮四要素渲染;有 `action` 时按钮可点。

`app_toast_test.dart`:

```dart
testWidgets('Toast 出现后 2s 自动消失', (tester) async {
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(body: Builder(builder: (context) => TextButton(
      onPressed: () => AppToast.show(context, '已保存'),
      child: const Text('show'),
    ))),
  ));
  await tester.tap(find.text('show'));
  await tester.pump(const Duration(milliseconds: 300)); // 入场
  expect(find.text('已保存'), findsOneWidget);
  await tester.pump(const Duration(seconds: 3));        // 超时自动移除
  expect(find.text('已保存'), findsNothing);
});
```

Run: `cd app && ../flutter/bin/flutter.bat test test/core/widgets/`
Expected: 编译失败(组件不存在)

- [x] **Step 2: 实现三组件**

要点:
- `AppSkeleton`:`AnimationController(loop)..repeat(reverse: true)`,色 `AppColors.divider`,透明度 `.5 + .5*value`;形状参数(宽/高/圆角,默认 `AppRadius.chip`)。
- `AppEmptyState`:大号 emoji(Text,fontSize 72)+ 标题(`AppText.subtitle` 17?用 title 的 20 还是自定义——按规则 §7 空态:标题 17/w600、说明 13 `text2` → 标题用 `AppText.subtitle.copyWith(fontSize: 17)`,说明 `AppText.caption.copyWith(color: AppColors.text2)`)+ 可选 `AppButton`。**禁灰色图标占位**(规则 §7)。
- `AppToast.show`:Overlay 插入;深色 `rgba(22,24,29,.92)` R16 白字 13;入场用 `AppMotion.base` 淡入+上移 8px;`Future.delayed(_showFor)` 后 `entry.remove()`(定义 `static const _showFor = Duration(seconds: 2);`)。

- [x] **Step 3: 测试过 + analyze**

Run: `cd app && ../flutter/bin/flutter.bat test test/core/widgets/ && ../flutter/bin/flutter.bat analyze`

- [x] **Step 4: Commit**

```bash
git add app/lib/core/widgets app/test/core/widgets
git commit -m "feat(ui): AppSkeleton/AppEmptyState/AppToast(§7)"
```

---

### Task 8: AppBottomBar + home_shell 接入 + 存量测试更新

**Files:**
- Create: `app/lib/features/shell/app_bottom_bar.dart`
- Modify: `app/lib/features/shell/home_shell.dart`
- Modify(选择器):`app/test/support/harness.dart`、`app/test/features/shell/home_shell_test.dart`、`app/test/features/auth/kicked_offline_test.dart`、`app/test/features/auth/login_page_test.dart`
- Test: `app/test/features/shell/app_bottom_bar_test.dart`

**Interfaces:**
- Consumes: `AppBadge`(Task 6)、`AppGradients/AppText/AppMotion/AppShadows/AppRadius`(Task 3/4)、已确认存在的图标字形
- Produces: `AppBottomBar({required currentIndex, required onTap, unreadCount = 0})`

- [x] **Step 1: 写 AppBottomBar 行为测试(fail)**

`app/test/features/shell/app_bottom_bar_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_badge.dart';
import 'package:chatapp_app/features/shell/app_bottom_bar.dart';

Widget wrap(Widget bar, {bool disableAnimations = false}) => MaterialApp(
      home: MediaQuery(
        data: MediaQueryData(disableAnimations: disableAnimations),
        child: Scaffold(bottomNavigationBar: bar),
      ),
    );

void main() {
  testWidgets('四个 Tab 渲染,点击回调索引', (tester) async {
    final taps = <int>[];
    await tester.pumpWidget(wrap(AppBottomBar(currentIndex: 0, onTap: taps.add)));
    for (final label in ['发现', '广场', '消息', '我的']) {
      expect(find.text(label), findsOneWidget);
    }
    await tester.tap(find.text('广场'));
    expect(taps, [1]);
  });

  testWidgets('未读角标:0 不显示,3 显示数字,120 显示 99+', (tester) async {
    await tester.pumpWidget(wrap(AppBottomBar(currentIndex: 2, onTap: (_) {}, unreadCount: 0)));
    expect(find.byType(AppBadge), findsNothing);

    await tester.pumpWidget(wrap(AppBottomBar(currentIndex: 2, onTap: (_) {}, unreadCount: 3)));
    expect(find.text('3'), findsOneWidget);

    await tester.pumpWidget(wrap(AppBottomBar(currentIndex: 2, onTap: (_) {}, unreadCount: 120)));
    expect(find.text('99+'), findsOneWidget);
  });

  testWidgets('减弱动态效果下切换正常', (tester) async {
    await tester.pumpWidget(wrap(
      AppBottomBar(currentIndex: 0, onTap: (_) {}), disableAnimations: true));
    await tester.tap(find.text('我的'));
    await tester.pump(const Duration(milliseconds: 400)); // 有限推进即可
    expect(find.text('我的'), findsOneWidget);
  });
}
```

Run: `cd app && ../flutter/bin/flutter.bat test test/features/shell/app_bottom_bar_test.dart`
Expected: 编译失败(`app_bottom_bar.dart` 不存在)

- [x] **Step 2: 实现 app_bottom_bar.dart**

要点(§7 底栏 + §6 动效 + §4 图标):

```dart
import 'package:flutter/material.dart';

import '../../core/theme/app_colors.dart';
import '../../core/theme/app_gradients.dart';
import '../../core/theme/app_motion.dart';
import '../../core/theme/app_radius.dart';
import '../../core/theme/app_shadows.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_badge.dart';

/// 「心跳」规则 §7 悬浮胶囊底栏(4 tab)。
class AppBottomBar extends StatelessWidget {
  const AppBottomBar({super.key, required this.currentIndex, required this.onTap, this.unreadCount = 0});

  final int currentIndex;
  final ValueChanged<int> onTap;
  final int unreadCount;

  static const _labels = ['发现', '广场', '消息', '我的'];
  static const _icons = [Icons.style_rounded, Icons.grid_view_rounded, Icons.chat_bubble_rounded, Icons.person_rounded];
  static const _outlines = [Icons.style_outlined, Icons.grid_view_outlined, Icons.chat_bubble_outlined, Icons.person_outlined];
  static const _capsuleWidth = 68.0;
  static const _capsuleHeight = 40.0;

  @override
  Widget build(BuildContext context) {
    final reduceMotion = MediaQuery.disableAnimationsOf(context);
    final moveDuration = reduceMotion ? Duration.zero : AppMotion.medium;
    final popDuration = reduceMotion ? Duration.zero : AppMotion.base;

    return SafeArea(
      top: false,
      child: Container(
        height: 64,
        margin: const EdgeInsets.fromLTRB(12, 0, 12, 10),
        decoration: BoxDecoration(
          color: AppColors.bgCard,
          borderRadius: BorderRadius.circular(22),
          boxShadow: AppShadows.floatingBar,
        ),
        child: LayoutBuilder(builder: (context, c) {
          final slot = c.maxWidth / _labels.length;
          return Stack(children: [
            AnimatedPositioned(
              duration: moveDuration,
              curve: AppMotion.easeOut,
              left: currentIndex * slot + (slot - _capsuleWidth) / 2,
              top: (64 - _capsuleHeight) / 2,
              child: Container(
                width: _capsuleWidth,
                height: _capsuleHeight,
                decoration: BoxDecoration(
                  gradient: AppGradients.heart,
                  borderRadius: BorderRadius.circular(20),
                ),
              ),
            ),
            Row(children: [
              for (var i = 0; i < _labels.length; i++)
                Expanded(child: _BarItem(
                  label: _labels[i],
                  icon: _icons[i],
                  outline: _outlines[i],
                  selected: i == currentIndex,
                  popDuration: popDuration,
                  badgeCount: i == 2 ? unreadCount : 0,
                  onTap: () => onTap(i),
                )),
            ]),
          ]);
        }),
      ),
    );
  }
}
```

`_BarItem`(私有):`Column`(图标 `AnimatedScale`(选中 1.12 弹跳,用 `AppMotion.easeOutBack`)+ `Text`);选中:白图标 20 + `navLabelSelected` 白字;未选中:outline 图标 22 `text3` + `navLabel` `text3`;消息 tab 且 `badgeCount > 0`:`Stack` 角标 `Positioned(top: -4, right: 8, child: AppBadge(count: badgeCount))`;整项包 `GestureDetector(behavior: HitTestBehavior.opaque, onTap: onTap)`。

注意:容器高 64 与 margin 10 的口径——`Container(height: 64)` 在 `SafeArea` 里;首版以实际观感微调 margin(不影响测试)。

- [x] **Step 3: home_shell 换底栏 + 清硬编码**

`home_shell.dart`:`bottomNavigationBar:` 段整体替换

```dart
      bottomNavigationBar: AppBottomBar(
        currentIndex: _index,
        onTap: (index) => setState(() => _index = index),
        unreadCount: unread,
      ),
```

删掉 `NavigationBar(...)` 整段与 `Badge.count`(连带 `const Color(0xFFFF2C55)` 硬编码,§2.3);加 `import 'app_bottom_bar.dart';`。

- [x] **Step 4: 更新存量测试选择器**

1. `test/support/harness.dart`:
   - `import 'package:chatapp_app/features/shell/app_bottom_bar.dart';`
   - `navTab` 改为 `find.descendant(of: find.byType(AppBottomBar), matching: find.text(label));`
2. `home_shell_test.dart`:
   - L25 `find.byType(NavigationBar)` → `find.byType(AppBottomBar)`;
   - L67–69 角标断言改为:
     ```dart
     expect(find.text('3'), findsWidgets); // 角标数字
     expect(find.byType(AppBadge), findsOneWidget);
     ```
     (删 `Badge.backgroundColor` 断言——渐变样式由 `app_badge_test.dart` 覆盖;需 import `app_badge.dart`/`app_bottom_bar.dart`,去掉不再需要的 material `Badge` 依赖)
3. `kicked_offline_test.dart` L26/L32、`login_page_test.dart` L55/L77:`find.byType(NavigationBar)` → `find.byType(AppBottomBar)`(+ import)。

- [x] **Step 5: 定向测试 → 全量测试**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/shell/ test/features/auth/ && ../flutter/bin/flutter.bat test`
Expected: 全量绿(含 chats_page_test 等所有 `navTab` 调用方——它们不改代码,靠 harness 生效)。

- [x] **Step 6: analyze + Commit**

Run: `../flutter/bin/flutter.bat analyze` → `No issues found!`

```bash
git add app/lib app/test
git commit -m "feat(ui): AppBottomBar 悬浮胶囊底栏替换 NavigationBar;测试选择器同步"
```

---

### Task 9: 模拟器手测 + 最终回归 + 合并

**Files:** 无(验证与收尾;可能微调 `app_bottom_bar.dart` 观感参数)

- [x] **Step 1: 全量回归**

Run: `cd app && ../flutter/bin/flutter.bat analyze && ../flutter/bin/flutter.bat test`
Expected: 零告警 + 全量绿

- [x] **Step 2: 模拟器手测(先与用户确认模拟器状态)**

```bash
cd app && ../flutter/bin/flutter.bat run -d emulator-5554 --dart-define=API_BASE=http://<SERVER_IP>/api/v1
```

(连测试服务器,不需要本地后端;若模拟器状态不佳参考 `docs/pitfalls/android-emulator.md`,冷启动前先问用户。)

截图留存:`"$LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe" -s emulator-5554 exec-out screencap -p > shot_bar.png`(四个 tab 各一张)。

检查清单(开发侧先过一遍,再请用户亲测):
- 四 tab 切换:胶囊位移 + 图标弹跳;选中白图标/白字;未选中描边 `text3`
- 消息 tab 未读角标(有未读时出现渐变角标)
- 全局字体:数字/拉丁变 Space Grotesk(如"第 1 步"数字、昵称字母)
- 四页面(发现/广场/消息/我的)正常进出,不崩
- 系统开发者选项「移除动画」开启时切换无异常

- [x] **Step 3: 观感微调(如需)**

若手测发现间距/胶囊宽度/字重问题:只调 `app_bottom_bar.dart` 内常量与 token,不动规则文档;改后重跑 Step 1。

- [x] **Step 4: 合并收尾**

```bash
git checkout master && git merge --ff-only ui/batch1 && git branch -d ui/batch1 && git push origin master
```

- [x] **Step 5: 更新 CLAUDE.md 里程碑**

「UI 设计规则」相关行补一句:`批次①(底座+底栏)已于 2026-09-18 交付`。提交推送。

---

## 完成后状态(供验收对照)

- `core/theme/` 8 文件 + `core/widgets/` 8 组件 + 组件级测试齐备
- 全局:Space Grotesk + 新主色派生 + `bgPage` 底 + SnackBar 深色浮层
- 底栏:悬浮胶囊 + 渐变选中 + 角标 + 减弱动效降级
- 测试:存量全绿(仅选择器更新)+ 新增组件/底栏用例;analyze 零告警
- 页面内部布局未动(过渡态,后续批次)

---

## 执行记录(2026-09-18,九任务全部完成)

- 分支 `ui/batch1`,7 个提交后 ff 合并 master(43775c7)并推送;基线 198 用例 → **220 用例全绿**,`flutter analyze` 零告警。
- 手测:release 包(连测试服务器)覆盖安装两台模拟器,用户亲测通过——底栏/字体/切换动画/无未读角标均正常。
- 截图留存:`%TEMP%\ui_shots\`(01_discovery / 03_phone_typed / 04_after_login)。
- 观察(未定性,非本批引入):adb 手测时 u8 登录成功后的落点是「编辑资料」页而非发现页;路由/登录逻辑不在本批改动范围,登录后落点欢迎时再查证。
