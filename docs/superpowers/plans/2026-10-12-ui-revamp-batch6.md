# UI 整改批次⑥:二级页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task(全局约定:superpowers 类任务一律内联执行,不派发子 agent)。Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按「心跳」规则整改 10 个二级页(登录/启动/引导/设置/黑名单/编辑资料/想找的人/发动态/协议/封禁),一次性定死「表单控件规范」(14 个 core 组件 + 2 个 feature 组件),并把 `AlertDialog`→`AppDialog`、`SnackBar`→`AppToast` 两条横切口径统一;296 既有测试适配后全绿 + analyze 零告警 + 模拟器手测。

**Architecture:** 纯视觉层迁移 + 一次共享抽取。先建组件(Task 1–8,每个组件 TDD 独立交付),再逐页替换(Task 9–17),最后文档同步(Task 18)。**行为、provider、接口、路由路径、文案零变化**;不新增视觉 token(聚焦光晕/淡底一律 `AppColors.x.withValues(alpha: …)` 派生,与 `app_avatar.dart:98` / `post_detail_page.dart:410` / `more_panel.dart:35` 同口径),故 **不动 `tokens.css`、不动 `app_colors.dart`**。

**Tech Stack:** Flutter 3.47(`../flutter/bin/flutter.bat`)、Riverpod、go_router、flutter_test(真实 provider + 假网络 `ScriptedAdapter` + 假 IM `FakeImClient`)。

**Spec:** `docs/superpowers/specs/2026-10-12-ui-revamp-batch6-design.md`(一切视觉细节以它 + 规则文档 `2026-09-15-ui-design-language-design.md` 为准)

## Global Constraints

- 所有视觉值走 token,**禁止新代码出现裸 hex / 裸字号 / 裸间距 / 裸圆角**(§1 铁律 3);确需新值先在组件内定义具名常量并注明附录条款。
- **行为与文案逐字零变化**;既有 key 全部保留,只新增 key。
- **常驻无限动画禁令**:登录页 / 启动页 / 协议弹窗路径上**不得**引入 `HeartRipple` / 呼吸类常驻动画——`login_page_test` / `startup_flow_test` / `account_switch_test` / `kicked_offline_test` / `agreement_gate_test` 用 `pumpAndSettle`,常驻动画会让它们永不收敛(批次⑤实测坑)。骨架屏只在 loading 态短暂出现,可用。
- **`AppToast` Timer 纪律**:`AppToast` 2s 自动消失的 Timer 会让 `testWidgets` 以 *A Timer is still pending* 失败——触发过 Toast 的用例收尾必须 `await drainToast(tester)`(harness 已提供)。本批波及 **8 文件 13 用例**,逐任务处理。
- **`enterText` 与 key 的关系**:`tester.enterText(finder, text)` 内部走 `find.descendant(of: finder, matching: find.byType(EditableText), matchRoot: true)`,所以 key 挂在 `AppTextField`(包装件)上即可,不必挂到内部 `TextField`;但**同一个 key 不能同时出现在包装件和内部 `TextField`**(`find.byKey` 会命中两个)。
- **不要用 Material 的 `InputDecoration.counterText`**:计数自己画(`AppTextField` 内置),避免样式被主题接管。
- 每任务收尾必须:全量 `../flutter/bin/flutter.bat analyze` 零告警 + 全量 `../flutter/bin/flutter.bat test` 绿 + 提交;所有 flutter/dart 命令 cwd = `app/`。
- **key 契约(既有,不得改名/不得删)**:`login.phone`、`login.code`、`login.sendCode`、`login.submit`、`splash.reread`、`onboarding.next`、`edit.nickname`、`edit.birthday`、`edit.city`、`edit.bio`、`edit.save`、`preference.city`、`preference.save`、`unblock.{id}`、`unblock.confirm`、`photo.add`、`photo.delete.{id}`、`compose.text`、`compose.submit`、`compose.add`、`compose.picked.{i}`、`banned.logout`、`agreement.accept`、`agreement.decline`、`post.delete.confirm`、`myPosts.back`、`post.back`。
- **新增 key**:`login.brand`、`splash.brand`、`splash.retry`、`onboarding.progress`、`onboarding.retry`、`edit.skeleton`、`edit.retry`、`preference.skeleton`、`preference.retry`、`settings.row.blocks`、`settings.row.agreement`、`settings.row.privacy`、`settings.logout`、`blocked.skeleton`、`blocked.empty`、`blocked.retry`、`compose.counter`、`legal.back`。
- **被删除的私有类**:`my_posts_page.dart::_SubPageBar`、`post_detail_page.dart::_DetailBar`(抽为 `AppSubPageBar`)、`post_compose_page.dart::_PickedTile`(抽为 `ComposePhotoGrid` 内部件)。
- 提交信息中文,前缀沿用仓库风格(`feat(ui):` / `refactor(ui):` / `test(ui):` / `docs:`),尾行 `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`。
- 分支 `ui/batch6`(spec 提交 `7f18181` 已在 master,切分支即含)。
- 本批**不动 `tokens.css` / `app_colors.dart` / `app_theme.dart`**;若实现中发现必须新增视觉 token,停下来先升规则文档再继续,并同步 web 侧跑双向比对。

---

### Task 0: 基线与分支

**Files:** 无代码改动

**Interfaces:**
- Produces: 分支 `ui/batch6`(后续全部任务在此分支提交)

- [ ] **Step 1: 建分支**

```bash
git checkout master && git merge --ff-only origin/master
git checkout -b ui/batch6
git log --oneline -2   # 应含 7f18181(spec)
```

- [ ] **Step 2: 基线全绿**

```bash
cd app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
```

Expected: analyze 零告警;296 全绿。红了先停下排查,别带病开工。

---

### Task 1: `AppSubPageBar`(二级页顶栏抽共享)

**Files:**
- Create: `app/lib/core/widgets/app_sub_page_bar.dart`
- Test: `app/test/core/widgets/app_sub_page_bar_test.dart`
- Modify: `app/lib/features/square/my_posts_page.dart`(替换 `_SubPageBar` 用法 + 删私有类)
- Modify: `app/lib/features/square/post_detail_page.dart`(替换 `_DetailBar` 用法 + 删私有类)

**Interfaces:**
- Consumes: `AppText` / `AppColors`
- Produces: `class AppSubPageBar extends StatelessWidget`,构造 `const AppSubPageBar({super.key, required String title, Key? backKey, VoidCallback? onBack, Widget? trailing, bool showBack = true})`;静态常量 `AppSubPageBar.height = 52.0`。Task 9–17 的全部二级页依赖这个签名。

- [ ] **Step 1: 写失败测试**

```dart
// app/test/core/widgets/app_sub_page_bar_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_sub_page_bar.dart';

Widget _wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

void main() {
  testWidgets('标题 + 返回键;点返回触发回调', (tester) async {
    var popped = 0;
    await tester.pumpWidget(_wrap(AppSubPageBar(
      title: '设置',
      backKey: const Key('bar.back'),
      onBack: () => popped++,
    )));

    expect(find.text('设置'), findsOneWidget);
    expect(find.byKey(const Key('bar.back')), findsOneWidget);
    expect(tester.getSize(find.byType(AppSubPageBar)).height, 52);

    await tester.tap(find.byKey(const Key('bar.back')));
    expect(popped, 1);
  });

  testWidgets('showBack=false 不渲染返回键', (tester) async {
    await tester.pumpWidget(_wrap(const AppSubPageBar(
      title: '设置',
      backKey: Key('bar.back'),
      showBack: false,
    )));
    expect(find.byKey(const Key('bar.back')), findsNothing);
  });

  testWidgets('trailing 槽渲染在右侧', (tester) async {
    await tester.pumpWidget(_wrap(const AppSubPageBar(
      title: '编辑资料',
      trailing: Text('保存', key: Key('bar.trailing')),
    )));
    expect(find.byKey(const Key('bar.trailing')), findsOneWidget);
    final titleX = tester.getCenter(find.text('编辑资料')).dx;
    final trailingX = tester.getCenter(find.byKey(const Key('bar.trailing'))).dx;
    expect(trailingX, greaterThan(titleX));
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/core/widgets/app_sub_page_bar_test.dart
```

Expected: FAIL,`app_sub_page_bar.dart` 不存在(编译错误)。

- [ ] **Step 3: 写实现**

```dart
// app/lib/core/widgets/app_sub_page_bar.dart
import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_typography.dart';

/// 「心跳」规则 §5.2 二级页顶栏:高 52,返回箭头 22 `text1`,标题 17/w600 居中。
///
/// [trailing] 是右侧动作槽(文字按钮等),用 Stack 定位所以不影响标题居中。
/// 批次⑤ 曾在我的动态页与详情页各留一份私有副本,本批抽共享(附录 E.2)。
class AppSubPageBar extends StatelessWidget {
  const AppSubPageBar({
    super.key,
    required this.title,
    this.backKey,
    this.onBack,
    this.trailing,
    this.showBack = true,
  });

  final String title;
  final Key? backKey;

  /// 默认 `Navigator.of(context).maybePop()`。
  final VoidCallback? onBack;
  final Widget? trailing;
  final bool showBack;

  static const height = 52.0;

  @override
  Widget build(BuildContext context) => SizedBox(
        height: height,
        child: Stack(
          alignment: Alignment.center,
          children: [
            Text(
              title,
              style: AppText.subtitle
                  .copyWith(fontSize: 17, color: AppColors.text1), // 17/w600(§5.2)
            ),
            if (showBack)
              Positioned(
                left: 0,
                top: 0,
                bottom: 0,
                child: IconButton(
                  key: backKey,
                  onPressed: onBack ?? () => Navigator.of(context).maybePop(),
                  icon: const Icon(Icons.arrow_back_ios_new_rounded,
                      size: 22, color: AppColors.text1),
                ),
              ),
            if (trailing != null)
              Positioned(
                right: 0,
                top: 0,
                bottom: 0,
                child: Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: Center(child: trailing),
                ),
              ),
          ],
        ),
      );
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/core/widgets/app_sub_page_bar_test.dart
```

Expected: 3 例 PASS。

- [ ] **Step 5: 替换两处私有副本**

`app/lib/features/square/my_posts_page.dart`:

```dart
// :68 处
            AppSubPageBar(
              title: '我的动态',
              backKey: const Key('myPosts.back'),
            ),
```

删掉文件末尾整个 `_SubPageBar` 类(`:129-165`,含注释);import 区加 `import '../../core/widgets/app_sub_page_bar.dart';`,并**删掉 `import '../../core/theme/app_typography.dart';`** —— `AppText` 在本文件的唯一用处就是被删掉的 `_SubPageBar`,不删会触发 `unused_import` 告警。

`app/lib/features/square/post_detail_page.dart`:

```dart
// :105 处
            const AppSubPageBar(
              title: '动态详情',
              backKey: Key('post.back'),
            ),
```

删掉 `:271-302` 整个 `_DetailBar` 类(含注释);import 区加 `import '../../core/widgets/app_sub_page_bar.dart';`(按字母序插在 `app_toast.dart` 之后)。

- [ ] **Step 6: 跑两页既有测试确认零回归**

```bash
../flutter/bin/flutter.bat test test/features/square/my_posts_page_test.dart test/features/square/post_detail_page_test.dart test/features/square/hero_transition_test.dart test/features/square/card_hero_flow_test.dart
```

Expected: 全 PASS(纯替换,视觉与行为不变)。

- [ ] **Step 7: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add -A
git commit -m "refactor(ui): 抽出 AppSubPageBar,取代我的动态/详情页两份私有顶栏副本" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: `AppBrandMark` + `AppTextAction`

**Files:**
- Create: `app/lib/core/widgets/app_brand_mark.dart`
- Create: `app/lib/core/widgets/app_text_action.dart`
- Test: `app/test/core/widgets/app_brand_mark_test.dart`
- Test: `app/test/core/widgets/app_text_action_test.dart`

**Interfaces:**
- Consumes: `AppGradients` / `AppRadius` / `AppText` / `AppColors` / `AppSpacing`
- Produces:
  - `class AppBrandMark extends StatelessWidget`,构造 `const AppBrandMark({super.key, double size = 72})`;根 `Container` 带 `Key` 由调用方传(login 传 `login.brand`、splash 传 `splash.brand`)。
  - `class AppTextAction extends StatelessWidget`,构造 `const AppTextAction({super.key, required String label, VoidCallback? onPressed, bool danger = false})`;`onPressed == null` 时文字 `text3`(禁用),否则 `brand`(或 `danger`)。**§7 文字按钮的紧凑形态**(无 52 高、无水平大内边距),用于输入框内嵌动作与二级页顶栏动作。Task 3 的 `AppTextField.suffix`、Task 9–17 的顶栏 trailing 依赖它。

- [ ] **Step 1: 写失败测试**

```dart
// app/test/core/widgets/app_brand_mark_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_gradients.dart';
import 'package:chatapp_app/core/widgets/app_brand_mark.dart';

void main() {
  testWidgets('72 圆角方 + 心跳渐变 + 白心形图标', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: Center(child: AppBrandMark(key: Key('brand')))),
    ));

    final box = tester.widget<Container>(
      find.descendant(
          of: find.byKey(const Key('brand')), matching: find.byType(Container)),
    );
    final decoration = box.decoration! as BoxDecoration;
    expect(decoration.gradient, AppGradients.heart);
    expect(tester.getSize(find.byKey(const Key('brand'))), const Size(72, 72));
    expect(find.byIcon(Icons.favorite_rounded), findsOneWidget);
  });

  testWidgets('品牌 mark 静态:连推数帧后仍无待处理帧', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: Center(child: AppBrandMark(key: Key('brand')))),
    ));
    await tester.pump(const Duration(milliseconds: 100));
    await tester.pump(const Duration(milliseconds: 100));
    expect(tester.binding.hasScheduledFrame, isFalse);
  });
}
```

```dart
// app/test/core/widgets/app_text_action_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_colors.dart';
import 'package:chatapp_app/core/widgets/app_text_action.dart';

void main() {
  testWidgets('可点:brand 15/w600;点回调', (tester) async {
    var taps = 0;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AppTextAction(
          key: const Key('act'),
          label: '保存',
          onPressed: () => taps++,
        ),
      ),
    ));

    final text = tester.widget<Text>(find.text('保存'));
    expect(text.style!.color, AppColors.brand);
    expect(text.style!.fontWeight, FontWeight.w600);
    expect(text.style!.fontSize, 15);

    await tester.tap(find.byKey(const Key('act')));
    expect(taps, 1);
  });

  testWidgets('禁用:文字 text3,点不动', (tester) async {
    var taps = 0;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AppTextAction(
          key: const Key('act'),
          label: '保存',
          onPressed: null,
        ),
      ),
    ));

    final text = tester.widget<Text>(find.text('保存'));
    expect(text.style!.color, AppColors.text3);
    expect(tester.widget<AppTextAction>(find.byKey(const Key('act'))).onPressed, isNull);
    expect(taps, 0);
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
../flutter/bin/flutter.bat test test/core/widgets/app_brand_mark_test.dart test/core/widgets/app_text_action_test.dart
```

Expected: FAIL,两个文件都不存在(编译错误)。

- [ ] **Step 3: 写实现**

```dart
// app/lib/core/widgets/app_brand_mark.dart
import 'package:flutter/material.dart';

import '../theme/app_gradients.dart';
import '../theme/app_radius.dart';

/// 品牌 mark(§2 心跳渐变):72 圆角方 + 白色心形图标。
///
/// **必须静态,不带任何常驻动画** —— 登录页/启动页有大量 `pumpAndSettle` 用例
/// (login_page_test / startup_flow_test / account_switch_test / kicked_offline_test /
/// agreement_gate_test),常驻无限动画会让它们永不收敛(批次⑤实测坑,附录 E.3)。
class AppBrandMark extends StatelessWidget {
  const AppBrandMark({super.key, this.size = 72});

  final double size;

  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          gradient: AppGradients.heart,
          borderRadius: BorderRadius.circular(AppRadius.sheet),
        ),
        child: Icon(Icons.favorite_rounded, size: size * 4 / 9, color: Colors.white),
      );
}
```

```dart
// app/lib/core/widgets/app_text_action.dart
import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// 「心跳」规则 §7 文字按钮的**紧凑形态**:`brand` 15/w600,无底无边距盒子。
///
/// 与 [AppButton] 的 `text` 变体区别:本组件没有 52 高、没有 24 水平内边距,
/// 因此能塞进输入框(`AppTextField.suffix`)与二级页顶栏(`AppSubPageBar.trailing`)。
/// `onPressed == null` 时文字 `text3`(§7 禁用态)。
class AppTextAction extends StatelessWidget {
  const AppTextAction({
    super.key,
    required this.label,
    this.onPressed,
    this.danger = false,
  });

  final String label;
  final VoidCallback? onPressed;
  final bool danger;

  @override
  Widget build(BuildContext context) {
    final disabled = onPressed == null;
    final color = disabled
        ? AppColors.text3
        : (danger ? AppColors.danger : AppColors.brand);
    return GestureDetector(
      onTap: onPressed,
      behavior: HitTestBehavior.opaque,
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.sm,
          vertical: AppSpacing.xs,
        ),
        child: Text(
          label,
          style: AppText.body.copyWith(color: color, fontWeight: FontWeight.w600),
        ),
      ),
    );
  }
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/core/widgets/app_brand_mark_test.dart test/core/widgets/app_text_action_test.dart
```

Expected: 4 例 PASS。

- [ ] **Step 5: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add -A
git commit -m "feat(ui): AppBrandMark(静态品牌 mark)+ AppTextAction(文字按钮紧凑形态)" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: `AppTextField`(表单输入框)

**Files:**
- Create: `app/lib/core/widgets/app_text_field.dart`
- Test: `app/test/core/widgets/app_text_field_test.dart`

**Interfaces:**
- Consumes: `AppColors` / `AppRadius` / `AppSpacing` / `AppMotion` / `AppText`
- Produces: `class AppTextField extends StatefulWidget`,构造:

```dart
const AppTextField({
  super.key,
  TextEditingController? controller,
  String? label,
  String? hint,
  String? errorText,
  TextInputType? keyboardType,
  int? maxLength,
  Key? counterKey,
  int maxLines = 1,
  int? minLines,
  ValueChanged<String>? onChanged,
  Widget? suffix,
  bool enabled = true,
  bool autofocus = false,
  FocusNode? focusNode,
  TextInputAction? textInputAction,
  bool borderless = false,
});
```

  单行盒高恒为 **52**(`AppTextField.singleLineHeight`);`maxLength != null` 时渲染 `x/y` 计数(有 `counterKey` 则挂上去);`borderless: true` 去掉底色/描边/圆角(发动态正文用)。Task 9–17 全部表单页依赖它。

- [ ] **Step 1: 写失败测试**

```dart
// app/test/core/widgets/app_text_field_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_colors.dart';
import 'package:chatapp_app/core/widgets/app_text_field.dart';

Widget _wrap(Widget child) => MaterialApp(
      home: Scaffold(body: Padding(padding: const EdgeInsets.all(16), child: child)),
    );

void main() {
  testWidgets('单行盒高 52;label 在上方;能输入', (tester) async {
    final controller = TextEditingController();
    addTearDown(controller.dispose);
    await tester.pumpWidget(_wrap(AppTextField(
      key: const Key('f'),
      controller: controller,
      label: '昵称',
    )));

    expect(find.text('昵称'), findsOneWidget);
    // 内盒高恒为 52(§7);label 在盒上方,所以整体比 52 高
    expect(
      tester.getSize(find.descendant(
        of: find.byKey(const Key('f')),
        matching: find.byType(AnimatedContainer),
      )).height,
      52,
    );

    await tester.enterText(find.byKey(const Key('f')), '小明');
    expect(controller.text, '小明');
  });

  testWidgets('聚焦时描边 1.5 brand', (tester) async {
    final node = FocusNode();
    addTearDown(node.dispose);
    await tester.pumpWidget(_wrap(AppTextField(
      key: const Key('f'),
      label: '昵称',
      focusNode: node,
    )));

    BoxDecoration decorationOf() {
      final container = tester.widget<AnimatedContainer>(find.descendant(
        of: find.byKey(const Key('f')),
        matching: find.byType(AnimatedContainer),
      ));
      return container.decoration! as BoxDecoration;
    }

    expect((decorationOf().border! as Border).top.color, AppColors.divider);
    expect((decorationOf().border! as Border).top.width, 1);

    node.requestFocus();
    await tester.pumpAndSettle();
    expect((decorationOf().border! as Border).top.color, AppColors.brand);
    expect((decorationOf().border! as Border).top.width, 1.5);
  });

  testWidgets('maxLength 渲染 x/y 计数并随输入更新', (tester) async {
    final controller = TextEditingController();
    addTearDown(controller.dispose);
    await tester.pumpWidget(_wrap(AppTextField(
      key: const Key('f'),
      controller: controller,
      label: '简介',
      maxLines: 3,
      maxLength: 200,
      counterKey: const Key('f.counter'),
    )));

    expect(find.byKey(const Key('f.counter')), findsOneWidget);
    expect(find.text('0/200'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('f')), '你好');
    await tester.pump();
    expect(find.text('2/200'), findsOneWidget);
  });

  testWidgets('suffix 渲染在输入区右侧', (tester) async {
    await tester.pumpWidget(_wrap(AppTextField(
      key: const Key('f'),
      label: '验证码',
      suffix: const Text('获取验证码', key: Key('f.suffix')),
    )));

    expect(find.byKey(const Key('f.suffix')), findsOneWidget);
    final fieldX = tester.getCenter(find.byType(EditableText)).dx;
    final suffixX = tester.getCenter(find.byKey(const Key('f.suffix'))).dx;
    expect(suffixX, greaterThan(fieldX));
  });

  testWidgets('borderless:无描边无底色', (tester) async {
    await tester.pumpWidget(_wrap(const AppTextField(
      key: Key('f'),
      hint: '分享新鲜事…',
      borderless: true,
      maxLines: 6,
      minLines: 6,
    )));

    expect(find.text('分享新鲜事…'), findsOneWidget);
    expect(
      find.descendant(of: find.byKey(const Key('f')), matching: find.byType(AnimatedContainer)),
      findsNothing,
    );
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
../flutter/bin/flutter.bat test test/core/widgets/app_text_field_test.dart
```

Expected: FAIL,`app_text_field.dart` 不存在(编译错误)。

- [ ] **Step 3: 写实现**

```dart
// app/lib/core/widgets/app_text_field.dart
import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_motion.dart';
import '../theme/app_radius.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// 「心跳」规则 §7 输入框:白底 `bgCard`、R16、描边 1px `divider`,
/// 聚焦 1.5px `brand` + 光晕 `brand@12%`(= 规则里的 rgba(255,44,85,.12))。
///
/// 单行盒高恒为 [singleLineHeight];`label` 渲染在盒子**上方**(不用 Material 的
/// 浮动 label,避免与自绘盒子打架);`maxLength` 的计数自己画
/// (不用 `InputDecoration.counterText`,否则样式被主题接管)。
///
/// key 挂在**本组件**上即可 —— `tester.enterText` 会向下找 `EditableText`
/// (`matchRoot: true`),不要给内部 `TextField` 再挂同一个 key。
class AppTextField extends StatefulWidget {
  const AppTextField({
    super.key,
    this.controller,
    this.label,
    this.hint,
    this.errorText,
    this.keyboardType,
    this.maxLength,
    this.counterKey,
    this.maxLines = 1,
    this.minLines,
    this.onChanged,
    this.suffix,
    this.enabled = true,
    this.autofocus = false,
    this.focusNode,
    this.textInputAction,
    this.borderless = false,
  });

  final TextEditingController? controller;
  final String? label;
  final String? hint;
  final String? errorText;
  final TextInputType? keyboardType;
  final int? maxLength;

  /// `maxLength != null` 时计数文本的 key(测试用)。
  final Key? counterKey;
  final int maxLines;
  final int? minLines;
  final ValueChanged<String>? onChanged;
  final Widget? suffix;
  final bool enabled;
  final bool autofocus;
  final FocusNode? focusNode;
  final TextInputAction? textInputAction;

  /// 无边框变体(发动态正文):去掉底色/描边/圆角,只留文字与 hint。
  final bool borderless;

  static const singleLineHeight = 52.0;

  @override
  State<AppTextField> createState() => _AppTextFieldState();
}

class _AppTextFieldState extends State<AppTextField> {
  late final FocusNode _node = widget.focusNode ?? FocusNode();
  late final bool _ownsNode = widget.focusNode == null;
  late int _length = widget.controller?.text.length ?? 0;
  var _focused = false;

  @override
  void initState() {
    super.initState();
    _node.addListener(_onFocusChanged);
  }

  @override
  void dispose() {
    _node.removeListener(_onFocusChanged);
    if (_ownsNode) _node.dispose();
    super.dispose();
  }

  void _onFocusChanged() {
    if (_focused == _node.hasFocus) return;
    setState(() => _focused = _node.hasFocus);
  }

  @override
  Widget build(BuildContext context) {
    final counter = widget.maxLength == null
        ? null
        : Text(
            '$_length/${widget.maxLength}',
            key: widget.counterKey,
            style: AppText.micro.copyWith(color: AppColors.text3),
          );

    if (widget.borderless) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _field(),
          if (counter != null) ...[
            const SizedBox(height: AppSpacing.xs),
            Align(alignment: Alignment.centerRight, child: counter),
          ],
        ],
      );
    }

    final borderColor = widget.errorText != null
        ? AppColors.danger
        : (_focused ? AppColors.brand : AppColors.divider);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (widget.label != null) ...[
          Text(widget.label!,
              style: AppText.caption.copyWith(color: AppColors.text2)),
          const SizedBox(height: AppSpacing.xs),
        ],
        AnimatedContainer(
          duration: AppMotion.fast,
          constraints:
              const BoxConstraints(minHeight: AppTextField.singleLineHeight),
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.lg,
            vertical: AppSpacing.sm,
          ),
          decoration: BoxDecoration(
            color: widget.enabled ? AppColors.bgCard : AppColors.divider,
            borderRadius: BorderRadius.circular(AppRadius.input),
            border: Border.all(
              color: borderColor,
              width: (_focused || widget.errorText != null) ? 1.5 : 1,
            ),
            boxShadow: _focused
                ? [
                    BoxShadow(
                      color: AppColors.brand.withValues(alpha: .12),
                      spreadRadius: 3,
                    ),
                  ]
                : null,
          ),
          child: Row(
            children: [
              Expanded(child: _field()),
              if (widget.suffix != null) ...[
                const SizedBox(width: AppSpacing.md),
                widget.suffix!,
              ],
            ],
          ),
        ),
        if (widget.errorText != null) ...[
          const SizedBox(height: AppSpacing.xs),
          Text(widget.errorText!,
              style: AppText.micro.copyWith(color: AppColors.danger)),
        ],
        if (counter != null) ...[
          const SizedBox(height: AppSpacing.xs),
          Align(alignment: Alignment.centerRight, child: counter),
        ],
      ],
    );
  }

  Widget _field() => TextField(
        controller: widget.controller,
        focusNode: _node,
        enabled: widget.enabled,
        autofocus: widget.autofocus,
        keyboardType: widget.keyboardType,
        textInputAction: widget.textInputAction,
        maxLength: widget.maxLength,
        maxLines: widget.maxLines,
        minLines: widget.minLines,
        onChanged: (value) {
          setState(() => _length = value.length);
          widget.onChanged?.call(value);
        },
        style: AppText.body.copyWith(color: AppColors.text1),
        decoration: InputDecoration(
          isDense: true,
          border: InputBorder.none,
          contentPadding: EdgeInsets.zero,
          counterText: '', // 计数自己画
          hintText: widget.hint,
          hintStyle: AppText.body.copyWith(color: AppColors.text3),
        ),
      );
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/core/widgets/app_text_field_test.dart
```

Expected: 5 例 PASS。若「聚焦描边」例找不到 `AnimatedContainer`(边框动画被合并),把断言目标换成 `find.byType(AnimatedContainer).first` 并把 `_focused` 初值确认无误——实现里盒子必须包在 `AnimatedContainer` 内。

- [ ] **Step 5: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add -A
git commit -m "feat(ui): AppTextField — R16 描边/聚焦光晕/自绘计数/内嵌 suffix" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: `AppOption` / `AppOptionGroup` / `AppChipGroup`

**Files:**
- Create: `app/lib/core/widgets/app_option_group.dart`
- Create: `app/lib/core/widgets/app_chip_group.dart`
- Test: `app/test/core/widgets/app_option_group_test.dart`
- Test: `app/test/core/widgets/app_chip_group_test.dart`

**Interfaces:**
- Consumes: `AppGradients` / `AppColors` / `AppRadius` / `AppSpacing` / `AppMotion` / `AppText`
- Produces:
  - `class AppOption<T>`,构造 `const AppOption({required T value, required String label})`。
  - `class AppOptionGroup<T> extends StatelessWidget`,构造 `const AppOptionGroup({super.key, required List<AppOption<T>> options, T? value, required ValueChanged<T> onChanged})`。整体高 **52**(4 内边距 + 44 段),与 `AppTextField` 对齐。
  - `class AppChipGroup<T> extends StatelessWidget`,构造 `const AppChipGroup({super.key, required List<AppOption<T>> items, required Set<T> selected, required ValueChanged<Set<T>> onChanged})`。
  - Task 9(编辑资料性别)、Task 10(想找的人)、Task 11(引导页性别)、Task 9/11(标签)依赖。

- [ ] **Step 1: 写失败测试**

```dart
// app/test/core/widgets/app_option_group_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_colors.dart';
import 'package:chatapp_app/core/theme/app_gradients.dart';
import 'package:chatapp_app/core/widgets/app_option_group.dart';

void main() {
  testWidgets('选中项渐变胶囊白字;未选中透明底 text2;点未选中项回调', (tester) async {
    String? picked;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AppOptionGroup<String>(
          options: const [
            AppOption(value: 'any', label: '不限'),
            AppOption(value: 'male', label: '男'),
            AppOption(value: 'female', label: '女'),
          ],
          value: 'any',
          onChanged: (value) => picked = value,
        ),
      ),
    ));

    BoxDecoration decorationOf(String label) => tester
        .widget<AnimatedContainer>(find.ancestor(
          of: find.text(label),
          matching: find.byType(AnimatedContainer),
        ))
        .decoration! as BoxDecoration;

    expect(decorationOf('不限').gradient, AppGradients.heart);
    expect(tester.widget<Text>(find.text('不限')).style!.color, Colors.white);
    expect(decorationOf('女').gradient, isNull);
    expect(tester.widget<Text>(find.text('女')).style!.color, AppColors.text2);

    await tester.tap(find.text('女'));
    expect(picked, 'female');
  });

  testWidgets('整体高 52', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AppOptionGroup<String>(
          options: const [
            AppOption(value: 'male', label: '男'),
            AppOption(value: 'female', label: '女'),
          ],
          value: null,
          onChanged: (_) {},
        ),
      ),
    ));
    expect(tester.getSize(find.byType(AppOptionGroup<String>)).height, 52);
  });
}
```

```dart
// app/test/core/widgets/app_chip_group_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_colors.dart';
import 'package:chatapp_app/core/widgets/app_option_group.dart';
import 'package:chatapp_app/core/widgets/app_chip_group.dart';

void main() {
  testWidgets('多选切换:点未选加入,点已选移除', (tester) async {
    Set<int> selected = {1};
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: StatefulBuilder(
          builder: (context, setState) => AppChipGroup<int>(
            items: const [
              AppOption(value: 1, label: '运动'),
              AppOption(value: 2, label: '音乐'),
            ],
            selected: selected,
            onChanged: (next) => setState(() => selected = next),
          ),
        ),
      ),
    ));

    BoxDecoration decorationOf(String label) => tester
        .widget<AnimatedContainer>(find.ancestor(
          of: find.text(label),
          matching: find.byType(AnimatedContainer),
        ))
        .decoration! as BoxDecoration;

    expect(decorationOf('运动').color, AppColors.brand.withValues(alpha: .12));
    expect(tester.widget<Text>(find.text('运动')).style!.color, AppColors.brand);

    await tester.tap(find.text('音乐'));
    await tester.pump();
    expect(selected, {1, 2});
    expect(decorationOf('音乐').color, AppColors.brand.withValues(alpha: .12));

    await tester.tap(find.text('运动'));
    await tester.pump();
    expect(selected, {2});
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
../flutter/bin/flutter.bat test test/core/widgets/app_option_group_test.dart test/core/widgets/app_chip_group_test.dart
```

Expected: FAIL,两个文件都不存在(编译错误)。

- [ ] **Step 3: 写实现**

```dart
// app/lib/core/widgets/app_option_group.dart
import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_gradients.dart';
import '../theme/app_motion.dart';
import '../theme/app_radius.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// 选项(单选/多选共用;`AppChipGroup` 也吃这个类型)。
class AppOption<T> {
  const AppOption({required this.value, required this.label});

  final T value;
  final String label;
}

/// 「心跳」§7 单选分段:白底 R16 描边容器内嵌等宽胶囊;
/// 选中 = `gradientHeart` 填充 + 白字 15/w600,未选中 = 透明底 + `text2`。
///
/// 整体高 [height](4 内边距 + 44 段)= 52,与 `AppTextField` 对齐。
/// 语义同旧 `SegmentedButton`:点已选中项不取消(现状如此,行为零变化)。
class AppOptionGroup<T> extends StatelessWidget {
  const AppOptionGroup({
    super.key,
    required this.options,
    required this.value,
    required this.onChanged,
  });

  final List<AppOption<T>> options;
  final T? value;
  final ValueChanged<T> onChanged;

  static const height = 52.0;
  static const _segmentHeight = 44.0;

  @override
  Widget build(BuildContext context) => Container(
        height: height,
        padding: const EdgeInsets.all(AppSpacing.xs),
        decoration: BoxDecoration(
          color: AppColors.bgCard,
          borderRadius: BorderRadius.circular(AppRadius.input),
          border: Border.all(color: AppColors.divider),
        ),
        child: Row(
          children: [
            for (final option in options)
              Expanded(
                child: GestureDetector(
                  onTap: () => onChanged(option.value),
                  behavior: HitTestBehavior.opaque,
                  child: AnimatedContainer(
                    duration: AppMotion.fast,
                    height: _segmentHeight,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      gradient:
                          option.value == value ? AppGradients.heart : null,
                      borderRadius: BorderRadius.circular(AppRadius.full),
                    ),
                    child: Text(
                      option.label,
                      style: AppText.body.copyWith(
                        color: option.value == value
                            ? Colors.white
                            : AppColors.text2,
                        fontWeight: option.value == value
                            ? FontWeight.w600
                            : FontWeight.w500,
                      ),
                    ),
                  ),
                ),
              ),
          ],
        ),
      );
}
```

```dart
// app/lib/core/widgets/app_chip_group.dart
import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_motion.dart';
import '../theme/app_radius.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import 'app_option_group.dart';

/// 「心跳」§7 多选标签:胶囊描边 `divider`;
/// 选中 = `brand@12%` 底 + 1px `brand` 描边 + `brand` 15/w600 字。
class AppChipGroup<T> extends StatelessWidget {
  const AppChipGroup({
    super.key,
    required this.items,
    required this.selected,
    required this.onChanged,
  });

  final List<AppOption<T>> items;
  final Set<T> selected;
  final ValueChanged<Set<T>> onChanged;

  @override
  Widget build(BuildContext context) => Wrap(
        spacing: AppSpacing.sm,
        runSpacing: AppSpacing.sm,
        children: [
          for (final item in items)
            GestureDetector(
              onTap: () {
                final next = {...selected};
                if (!next.remove(item.value)) next.add(item.value);
                onChanged(next);
              },
              behavior: HitTestBehavior.opaque,
              child: AnimatedContainer(
                duration: AppMotion.fast,
                padding: const EdgeInsets.symmetric(
                  horizontal: AppSpacing.lg,
                  vertical: AppSpacing.sm,
                ),
                decoration: BoxDecoration(
                  color: selected.contains(item.value)
                      ? AppColors.brand.withValues(alpha: .12)
                      : AppColors.bgCard,
                  borderRadius: BorderRadius.circular(AppRadius.full),
                  border: Border.all(
                    color: selected.contains(item.value)
                        ? AppColors.brand
                        : AppColors.divider,
                  ),
                ),
                child: Text(
                  item.label,
                  style: AppText.body.copyWith(
                    color: selected.contains(item.value)
                        ? AppColors.brand
                        : AppColors.text2,
                    fontWeight: selected.contains(item.value)
                        ? FontWeight.w600
                        : FontWeight.w500,
                  ),
                ),
              ),
            ),
        ],
      );
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/core/widgets/app_option_group_test.dart test/core/widgets/app_chip_group_test.dart
```

Expected: 3 例 PASS。

- [ ] **Step 5: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add -A
git commit -m "feat(ui): AppOptionGroup(渐变选中分段)+ AppChipGroup(多选标签)" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: `AppPickerField` + `AppRangeField`

**Files:**
- Create: `app/lib/core/widgets/app_picker_field.dart`
- Create: `app/lib/core/widgets/app_range_field.dart`
- Test: `app/test/core/widgets/app_picker_field_test.dart`
- Test: `app/test/core/widgets/app_range_field_test.dart`

**Interfaces:**
- Consumes: `AppColors` / `AppRadius` / `AppSpacing` / `AppText` / `AppShadows` / `AppGradients`;Flutter 的 `RangeSliderTrackShape` + `BaseRangeSliderTrackShape`(均从 `package:flutter/material.dart` 导出)
- Produces:
  - `class AppPickerField extends StatelessWidget`,构造 `const AppPickerField({super.key, required String label, String? value, String placeholder = '请选择', required VoidCallback onTap})`;盒高 52。
  - `class AppRangeField extends StatelessWidget`,构造 `const AppRangeField({super.key, required String title, required RangeValues values, required double min, required double max, int? divisions, required ValueChanged<RangeValues> onChanged})`;选中轨道用 `gradientHeart` 着色(自绘 `_GradientRangeTrackShape`)。
  - Task 9 / Task 11 的生日字段、Task 10 的年龄区间依赖。

- [ ] **Step 1: 写失败测试**

```dart
// app/test/core/widgets/app_picker_field_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_colors.dart';
import 'package:chatapp_app/core/widgets/app_picker_field.dart';

void main() {
  testWidgets('未选显示占位 text3;有值显示 text1;点击回调', (tester) async {
    var taps = 0;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AppPickerField(
          key: const Key('p'),
          label: '生日',
          onTap: () => taps++,
        ),
      ),
    ));

    expect(find.text('生日'), findsOneWidget);
    expect(find.text('请选择'), findsOneWidget);
    expect(tester.widget<Text>(find.text('请选择')).style!.color, AppColors.text3);

    await tester.tap(find.byKey(const Key('p')));
    expect(taps, 1);
  });

  testWidgets('有值时文字 text1,盒高 52', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AppPickerField(
          key: const Key('p'),
          label: '生日',
          value: '2000-01-01',
          onTap: () {},
        ),
      ),
    ));

    expect(tester.widget<Text>(find.text('2000-01-01')).style!.color, AppColors.text1);
    final box = tester.widget<Container>(find.descendant(
      of: find.byKey(const Key('p')),
      matching: find.byType(Container),
    ));
    expect(box.constraints!.maxHeight, 52);
  });
}
```

```dart
// app/test/core/widgets/app_range_field_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_range_field.dart';

void main() {
  testWidgets('标题 + 双滑块;拖动后回调新值', (tester) async {
    RangeValues values = const RangeValues(18, 99);
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: StatefulBuilder(
          builder: (context, setState) => AppRangeField(
            title: '年龄 ${values.start.round()} – ${values.end.round()} 岁',
            values: values,
            min: 18,
            max: 99,
            divisions: 81,
            onChanged: (next) => setState(() => values = next),
          ),
        ),
      ),
    ));

    expect(find.text('年龄 18 – 99 岁'), findsOneWidget);
    expect(find.byType(RangeSlider), findsOneWidget);

    // 抓「起点滑块」(轨道左端 = slider.left + 24,见 BaseRangeSliderTrackShape)
    // 往右拖;从正中拖会命中较近的那个滑块,断言会不稳。
    final slider = tester.getRect(find.byType(RangeSlider));
    await tester.dragFrom(
        Offset(slider.left + 24, slider.center.dy), const Offset(120, 0));
    await tester.pumpAndSettle();

    expect(values.start, greaterThan(18));
    expect(values.end, 99);
    expect(find.textContaining('年龄 ${values.start.round()}'), findsOneWidget);
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
../flutter/bin/flutter.bat test test/core/widgets/app_picker_field_test.dart test/core/widgets/app_range_field_test.dart
```

Expected: FAIL,两个文件都不存在(编译错误)。

- [ ] **Step 3: 写实现**

```dart
// app/lib/core/widgets/app_picker_field.dart
import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_radius.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// 「心跳」§7 选择框:外观与 `AppTextField` 同规格(白底 R16 描边 1px 高 52),
/// 点整块唤起外部选择器(如 `showDatePicker`)。
class AppPickerField extends StatelessWidget {
  const AppPickerField({
    super.key,
    required this.label,
    this.value,
    this.placeholder = '请选择',
    required this.onTap,
  });

  final String label;
  final String? value;
  final String placeholder;
  final VoidCallback onTap;

  static const height = 52.0;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: AppText.caption.copyWith(color: AppColors.text2)),
          const SizedBox(height: AppSpacing.xs),
          GestureDetector(
            onTap: onTap,
            behavior: HitTestBehavior.opaque,
            child: Container(
              height: height,
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
              decoration: BoxDecoration(
                color: AppColors.bgCard,
                borderRadius: BorderRadius.circular(AppRadius.input),
                border: Border.all(color: AppColors.divider),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      value ?? placeholder,
                      style: AppText.body.copyWith(
                        color: value == null ? AppColors.text3 : AppColors.text1,
                      ),
                    ),
                  ),
                  const Icon(Icons.expand_more_rounded,
                      size: 20, color: AppColors.text3),
                ],
              ),
            ),
          ),
        ],
      );
}
```

```dart
// app/lib/core/widgets/app_range_field.dart
import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_gradients.dart';
import '../theme/app_shadows.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// 「心跳」§7 区间选择:标题 + 双滑块。
/// 选中轨道用 `gradientHeart` 着色(§7「选中:填充样式 + gradientHeart 着色」),
/// 由 [_GradientRangeTrackShape] 自绘;未选段 `divider`;滑块白底圆 + 卡片阴影。
class AppRangeField extends StatelessWidget {
  const AppRangeField({
    super.key,
    required this.title,
    required this.values,
    required this.min,
    required this.max,
    this.divisions,
    required this.onChanged,
  });

  final String title;
  final RangeValues values;
  final double min;
  final double max;
  final int? divisions;
  final ValueChanged<RangeValues> onChanged;

  static const trackHeight = 4.0;
  static const thumbRadius = 12.0;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: AppText.subtitle.copyWith(color: AppColors.text1)),
          SliderTheme(
            data: SliderTheme.of(context).copyWith(
              trackHeight: trackHeight,
              activeTrackColor: AppColors.brand, // 自定义 track shape 会盖掉它
              inactiveTrackColor: AppColors.divider,
              thumbColor: AppColors.bgCard,
              overlayColor: AppColors.brand.withValues(alpha: .12),
              rangeTrackShape: const _GradientRangeTrackShape(),
              rangeThumbShape: const RoundRangeSliderThumbShape(
                enabledThumbRadius: thumbRadius,
                elevation: 2,
                pressedElevation: 4,
              ),
            ),
            child: RangeSlider(
              values: values,
              min: min,
              max: max,
              divisions: divisions,
              labels: RangeLabels(
                values.start.round().toString(),
                values.end.round().toString(),
              ),
              onChanged: onChanged,
            ),
          ),
        ],
      );
}

/// 选中段画 `gradientHeart`,未选段画 `divider`。
class _GradientRangeTrackShape extends RangeSliderTrackShape
    with BaseRangeSliderTrackShape {
  const _GradientRangeTrackShape();

  @override
  bool get isRounded => true;

  @override
  void paint(
    PaintingContext context,
    Offset offset, {
    required RenderBox parentBox,
    required SliderThemeData sliderTheme,
    required Animation<double> enableAnimation,
    required Offset startThumbCenter,
    required Offset endThumbCenter,
    bool isEnabled = false,
    bool isDiscrete = false,
    required TextDirection textDirection,
  }) {
    final rect = getPreferredRect(
      parentBox: parentBox,
      offset: offset,
      sliderTheme: sliderTheme,
      isEnabled: isEnabled,
      isDiscrete: isDiscrete,
    );
    if (rect.isEmpty) return;

    final radius = Radius.circular(rect.height / 2);
    final canvas = context.canvas;
    canvas.drawRRect(
      RRect.fromRectAndRadius(rect, radius),
      Paint()..color = sliderTheme.inactiveTrackColor ?? AppColors.divider,
    );

    final active = Rect.fromLTRB(
      startThumbCenter.dx < endThumbCenter.dx
          ? startThumbCenter.dx
          : endThumbCenter.dx,
      rect.top,
      startThumbCenter.dx < endThumbCenter.dx
          ? endThumbCenter.dx
          : startThumbCenter.dx,
      rect.bottom,
    );
    if (active.isEmpty) return;
    canvas.drawRRect(
      RRect.fromRectAndRadius(active, radius),
      Paint()..shader = AppGradients.heart.createShader(active),
    );
  }
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/core/widgets/app_picker_field_test.dart test/core/widgets/app_range_field_test.dart
```

Expected: 3 例 PASS。若 `RoundRangeSliderThumbShape` 的 `elevation` 参数在当前 Flutter 版本不存在,删掉 `elevation`/`pressedElevation` 两个具名参数(保留 `enabledThumbRadius`)——以 `flutter analyze` 报错为准。

- [ ] **Step 5: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add -A
git commit -m "feat(ui): AppPickerField(选择框)+ AppRangeField(渐变轨道双滑块)" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: `AppSectionCard` + `AppRowGroup` + `AppListRow`

**Files:**
- Create: `app/lib/core/widgets/app_section_card.dart`
- Create: `app/lib/core/widgets/app_row_group.dart`
- Create: `app/lib/core/widgets/app_list_row.dart`
- Test: `app/test/core/widgets/app_section_card_test.dart`
- Test: `app/test/core/widgets/app_row_group_test.dart`
- Test: `app/test/core/widgets/app_list_row_test.dart`

**Interfaces:**
- Consumes: `AppColors` / `AppRadius` / `AppShadows` / `AppSpacing` / `AppMotion` / `AppText`
- Produces:
  - `class AppSectionCard extends StatelessWidget`,构造 `const AppSectionCard({super.key, String? title, required List<Widget> children, double gap = AppSpacing.lg})` —— 表单分组卡(白卡 R20 + 阴影 + 内边距 16)。
  - `class AppRowGroup extends StatelessWidget`,构造 `const AppRowGroup({super.key, String? title, required List<Widget> children})` —— 行分组卡(白卡 R20 + 阴影 + **无内边距**,行自带 16 水平内边距,行间 1px `divider`)。
  - `class AppListRow extends StatefulWidget`,构造 `const AppListRow({super.key, IconData? icon, Widget? avatar, required String title, String? subtitle, Widget? trailing, VoidCallback? onTap, bool danger = false, bool showChevron = true, bool centerTitle = false})`;静态常量 `AppListRow.height = 64.0`。
  - Task 9–17 全部分组卡片与列表行依赖。

- [ ] **Step 1: 写失败测试**

```dart
// app/test/core/widgets/app_section_card_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_colors.dart';
import 'package:chatapp_app/core/theme/app_radius.dart';
import 'package:chatapp_app/core/widgets/app_section_card.dart';

void main() {
  testWidgets('白卡 R20 + 内边距 16;分组标题在最上;子项按 gap 竖排', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(
        body: AppSectionCard(
          key: Key('card'),
          title: '基本信息',
          children: [Text('甲'), Text('乙')],
        ),
      ),
    ));

    expect(find.text('基本信息'), findsOneWidget);
    expect(find.text('甲'), findsOneWidget);
    expect(find.text('乙'), findsOneWidget);

    final container = tester.widget<Container>(find.descendant(
      of: find.byKey(const Key('card')),
      matching: find.byType(Container),
    ));
    final decoration = container.decoration! as BoxDecoration;
    expect(decoration.color, AppColors.bgCard);
    expect(
      (decoration.borderRadius! as BorderRadius).topLeft.x,
      AppRadius.card,
    );

    final titleY = tester.getCenter(find.text('基本信息')).dy;
    final firstY = tester.getCenter(find.text('甲')).dy;
    final secondY = tester.getCenter(find.text('乙')).dy;
    expect(titleY, lessThan(firstY));
    expect(firstY, lessThan(secondY));
  });
}
```

```dart
// app/test/core/widgets/app_row_group_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_row_group.dart';

void main() {
  testWidgets('行之间插 1px divider;单行不插', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(
        body: AppRowGroup(children: [Text('A'), Text('B'), Text('C')]),
      ),
    ));
    expect(find.byType(Divider), findsNWidgets(2));

    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: AppRowGroup(children: [Text('A')])),
    ));
    expect(find.byType(Divider), findsNothing);
  });
}
```

```dart
// app/test/core/widgets/app_list_row_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_colors.dart';
import 'package:chatapp_app/core/widgets/app_list_row.dart';

void main() {
  testWidgets('图标 + 标题 + 副标题 + 默认 chevron;高 64;点击回调', (tester) async {
    var taps = 0;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AppListRow(
          key: const Key('row'),
          icon: Icons.block_rounded,
          title: '黑名单',
          subtitle: '3 人',
          onTap: () => taps++,
        ),
      ),
    ));

    expect(tester.getSize(find.byKey(const Key('row'))).height, 64);
    expect(find.byIcon(Icons.block_rounded), findsOneWidget);
    expect(find.byIcon(Icons.chevron_right_rounded), findsOneWidget);
    expect(find.text('3 人'), findsOneWidget);

    await tester.tap(find.byKey(const Key('row')));
    expect(taps, 1);
  });

  testWidgets('trailing 覆盖 chevron;showChevron=false 不渲染', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AppListRow(
          title: '小红',
          trailing: const Text('解除', key: Key('row.trailing')),
        ),
      ),
    ));
    expect(find.byKey(const Key('row.trailing')), findsOneWidget);
    expect(find.byIcon(Icons.chevron_right_rounded), findsNothing);
  });

  testWidgets('danger + centerTitle:居中 danger 字,无图标无 chevron', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AppListRow(
          key: const Key('row'),
          title: '退出登录',
          centerTitle: true,
          danger: true,
          onTap: () {},
        ),
      ),
    ));

    final text = tester.widget<Text>(find.text('退出登录'));
    expect(text.style!.color, AppColors.danger);
    expect(text.style!.fontWeight, FontWeight.w600);
    expect(find.byIcon(Icons.chevron_right_rounded), findsNothing);

    final rowCenter = tester.getCenter(find.byKey(const Key('row'))).dx;
    final textCenter = tester.getCenter(find.text('退出登录')).dx;
    expect(textCenter, closeTo(rowCenter, 0.5));
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
../flutter/bin/flutter.bat test test/core/widgets/app_section_card_test.dart test/core/widgets/app_row_group_test.dart test/core/widgets/app_list_row_test.dart
```

Expected: FAIL,三个文件都不存在(编译错误)。

- [ ] **Step 3: 写实现**

```dart
// app/lib/core/widgets/app_section_card.dart
import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_radius.dart';
import '../theme/app_shadows.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// 「心跳」§7 表单分组卡:白卡 R20 + 卡片阴影 + 内边距 16;可选分组标题。
/// 子项按 [gap] 竖排(默认 `AppSpacing.lg` = 16)。
///
/// 行式列表(行自带内边距、行间分隔线)请用 [AppRowGroup],别把两种内边距
/// 语义塞进同一个构造(附录 E.1)。
class AppSectionCard extends StatelessWidget {
  const AppSectionCard({
    super.key,
    this.title,
    required this.children,
    this.gap = AppSpacing.lg,
  });

  final String? title;
  final List<Widget> children;
  final double gap;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(AppSpacing.lg),
        decoration: BoxDecoration(
          color: AppColors.bgCard,
          borderRadius: BorderRadius.circular(AppRadius.card),
          boxShadow: AppShadows.card,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (title != null) ...[
              Text(title!,
                  style: AppText.subtitle.copyWith(color: AppColors.text1)),
              const SizedBox(height: AppSpacing.md),
            ],
            for (var i = 0; i < children.length; i++) ...[
              if (i > 0) SizedBox(height: gap),
              children[i],
            ],
          ],
        ),
      );
}
```

```dart
// app/lib/core/widgets/app_row_group.dart
import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_radius.dart';
import '../theme/app_shadows.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// 「心跳」§7 行分组卡:白卡 R20 + 卡片阴影 + **无内边距**(行自带 16 水平内边距);
/// 行之间插 1px `divider`。可选分组标题(自带 16 内边距)。
class AppRowGroup extends StatelessWidget {
  const AppRowGroup({super.key, this.title, required this.children});

  final String? title;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Container(
        clipBehavior: Clip.antiAlias,
        decoration: BoxDecoration(
          color: AppColors.bgCard,
          borderRadius: BorderRadius.circular(AppRadius.card),
          boxShadow: AppShadows.card,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (title != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(AppSpacing.lg, AppSpacing.md,
                    AppSpacing.lg, AppSpacing.xs),
                child: Text(title!,
                    style: AppText.caption.copyWith(color: AppColors.text3)),
              ),
            for (var i = 0; i < children.length; i++) ...[
              if (i > 0)
                const Divider(height: 1, thickness: 1, color: AppColors.divider),
              children[i],
            ],
          ],
        ),
      );
}
```

```dart
// app/lib/core/widgets/app_list_row.dart
import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_motion.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// 「心跳」§5.2 列表行:高 64;左槽图标(20)或头像;标题 + 可选副标题;
/// 右槽 [trailing] 或默认 `chevron_right_rounded`;按压 scale .98。
///
/// [centerTitle] 是「退出登录」这类单行危险动作的变体:居中、无左右槽。
class AppListRow extends StatefulWidget {
  const AppListRow({
    super.key,
    this.icon,
    this.avatar,
    required this.title,
    this.subtitle,
    this.trailing,
    this.onTap,
    this.danger = false,
    this.showChevron = true,
    this.centerTitle = false,
  });

  final IconData? icon;
  final Widget? avatar;
  final String title;
  final String? subtitle;
  final Widget? trailing;
  final VoidCallback? onTap;
  final bool danger;
  final bool showChevron;
  final bool centerTitle;

  static const height = 64.0;

  @override
  State<AppListRow> createState() => _AppListRowState();
}

class _AppListRowState extends State<AppListRow> {
  var _pressed = false;

  @override
  Widget build(BuildContext context) {
    final accent = widget.danger ? AppColors.danger : AppColors.text1;
    final iconColor = widget.danger ? AppColors.danger : AppColors.text2;
    final tappable = widget.onTap != null;

    final Widget content = widget.centerTitle
        ? Center(
            child: Text(
              widget.title,
              style: AppText.body
                  .copyWith(color: accent, fontWeight: FontWeight.w600),
            ),
          )
        : Row(
            children: [
              if (widget.avatar != null) ...[
                widget.avatar!,
                const SizedBox(width: AppSpacing.md),
              ] else if (widget.icon != null) ...[
                Icon(widget.icon, size: 20, color: iconColor),
                const SizedBox(width: AppSpacing.md),
              ],
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      widget.title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppText.body.copyWith(color: accent),
                    ),
                    if (widget.subtitle != null) ...[
                      const SizedBox(height: 2),
                      Text(
                        widget.subtitle!,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppText.micro.copyWith(color: AppColors.text3),
                      ),
                    ],
                  ],
                ),
              ),
              if (widget.trailing != null)
                widget.trailing!
              else if (widget.showChevron)
                const Icon(Icons.chevron_right_rounded,
                    size: 20, color: AppColors.text3),
            ],
          );

    return GestureDetector(
      onTapDown: tappable ? (_) => setState(() => _pressed = true) : null,
      onTapUp: tappable ? (_) => setState(() => _pressed = false) : null,
      onTapCancel: tappable ? () => setState(() => _pressed = false) : null,
      onTap: widget.onTap,
      child: AnimatedScale(
        scale: _pressed ? 0.98 : 1,
        duration: AppMotion.fast,
        child: Container(
          height: AppListRow.height,
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
          alignment: Alignment.center,
          child: content,
        ),
      ),
    );
  }
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/core/widgets/app_section_card_test.dart test/core/widgets/app_row_group_test.dart test/core/widgets/app_list_row_test.dart
```

Expected: 5 例 PASS。

- [ ] **Step 5: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add -A
git commit -m "feat(ui): AppSectionCard / AppRowGroup / AppListRow(分组卡与列表行规范)" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: `AppButton.dangerFilled` + `AppDialog` + `showConfirmDialog` + 删除动态确认接入

**Files:**
- Modify: `app/lib/core/widgets/app_button.dart`(加 `dangerFilled` 变体)
- Modify: `app/test/core/widgets/app_button_test.dart`(加一例)
- Create: `app/lib/core/widgets/app_dialog.dart`
- Test: `app/test/core/widgets/app_dialog_test.dart`
- Modify: `app/lib/features/square/post_actions.dart`(`confirmDeletePost` 换 `showConfirmDialog`)

**Interfaces:**
- Consumes: `AppColors` / `AppRadius` / `AppSpacing` / `AppText` / `AppButton` / `AppButtonVariant`
- Produces:
  - `AppButtonVariant` 新增成员 `dangerFilled`(§7「危险按钮:danger 描边或实底(二次确认后)」的实底形态;danger 实底 + 白字 w700,无阴影)。
  - `class AppDialog extends StatelessWidget`,构造 `const AppDialog({super.key, required String title, String? message, Widget? content, required List<Widget> actions})` —— 白底 R24、标题 17/w600 居中、正文 `caption` `text2` 居中、`actions` 等宽横排。
  - `Future<bool> showConfirmDialog(BuildContext context, {required String title, String? message, String cancelLabel = '取消', required String confirmLabel, bool danger = false, Key? confirmKey, bool barrierDismissible = true})`。
  - Task 12–17 的确认框与协议弹窗依赖。

- [ ] **Step 1: 写失败测试**

```dart
// app/test/core/widgets/app_dialog_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_button.dart';
import 'package:chatapp_app/core/widgets/app_dialog.dart';

void main() {
  testWidgets('showConfirmDialog:点确认返回 true,点取消返回 false', (tester) async {
    bool? result;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: Builder(
          builder: (context) => TextButton(
            onPressed: () async {
              result = await showConfirmDialog(
                context,
                title: '删除这条动态?',
                confirmLabel: '删除',
                confirmKey: const Key('d.confirm'),
                danger: true,
              );
            },
            child: const Text('开'),
          ),
        ),
      ),
    ));

    await tester.tap(find.text('开'));
    await tester.pumpAndSettle();
    expect(find.text('删除这条动态?'), findsOneWidget);
    expect(find.byKey(const Key('d.confirm')), findsOneWidget);
    expect(
      tester.widget<AppButton>(find.byKey(const Key('d.confirm'))).variant,
      AppButtonVariant.dangerFilled,
    );

    await tester.tap(find.byKey(const Key('d.confirm')));
    await tester.pumpAndSettle();
    expect(result, isTrue);

    await tester.tap(find.text('开'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();
    expect(result, isFalse);
  });

  testWidgets('AppDialog:标题 + 正文 + 自定义 content + 两个等宽按钮', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AppDialog(
          title: '用户协议与隐私政策',
          message: '请阅读并同意以下文件',
          content: const Text('《用户协议》'),
          actions: [
            AppButton(label: '不同意', variant: AppButtonVariant.secondary, onPressed: () {}),
            AppButton(label: '同意并继续', onPressed: () {}),
          ],
        ),
      ),
    ));

    expect(find.text('用户协议与隐私政策'), findsOneWidget);
    expect(find.text('请阅读并同意以下文件'), findsOneWidget);
    expect(find.text('《用户协议》'), findsOneWidget);

    final a = tester.getSize(find.widgetWithText(AppButton, '不同意'));
    final b = tester.getSize(find.widgetWithText(AppButton, '同意并继续'));
    expect(a.width, closeTo(b.width, 0.5)); // 等宽
  });
}
```

`app/test/core/widgets/app_button_test.dart` 尾部追加一例(该文件已有 `_wrap` 之类的辅助,按文件内既有写法追加;若无辅助函数就用下面的自足写法):

```dart
  testWidgets('dangerFilled:danger 实底 + 白字 w700', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AppButton(
          label: '删除',
          variant: AppButtonVariant.dangerFilled,
          onPressed: () {},
        ),
      ),
    ));

    final container = tester.widget<Container>(find.descendant(
      of: find.byType(AppButton),
      matching: find.byType(Container),
    ));
    final decoration = container.decoration! as BoxDecoration;
    expect(decoration.color, AppColors.danger);
    expect(decoration.gradient, isNull);
    final text = tester.widget<Text>(find.text('删除'));
    expect(text.style!.color, Colors.white);
    expect(text.style!.fontWeight, FontWeight.w700);
  });
```

- [ ] **Step 2: 跑测试确认失败**

```bash
../flutter/bin/flutter.bat test test/core/widgets/app_dialog_test.dart test/core/widgets/app_button_test.dart
```

Expected: FAIL —— `app_dialog.dart` 不存在;`dangerFilled` 未定义。

- [ ] **Step 3: 给 `AppButton` 加 `dangerFilled`**

`app/lib/core/widgets/app_button.dart`,把枚举与 switch 各加一支:

```dart
enum AppButtonVariant { primary, secondary, text, danger, dangerFilled }
```

```dart
      AppButtonVariant.danger => (
          BoxDecoration(
            borderRadius: BorderRadius.circular(AppRadius.full),
            border: Border.all(color: AppColors.danger),
          ),
          AppText.body.copyWith(color: AppColors.danger, fontWeight: FontWeight.w600),
        ),
      // §7「危险按钮:danger 描边或实底(二次确认后)」的实底形态。
      // 不带阴影:同屏阴影层级不超过 2 种(§5.1),且 primaryButton 阴影是 brand 色。
      AppButtonVariant.dangerFilled => (
          BoxDecoration(
            color: disabled ? AppColors.divider : AppColors.danger,
            borderRadius: BorderRadius.circular(AppRadius.full),
          ),
          AppText.body.copyWith(color: Colors.white, fontWeight: FontWeight.w700),
        ),
```

- [ ] **Step 4: 写 `AppDialog`**

```dart
// app/lib/core/widgets/app_dialog.dart
import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_radius.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import 'app_button.dart';

/// 「心跳」统一对话框:白底 R24、标题 17/w600 居中、正文 `caption` `text2`、
/// [actions] 等宽横排(次在左、主在右)。
///
/// 需要自定义内容(协议弹窗的协议链接)时传 [content];
/// 只要「确认/取消」两键的场合直接用 [showConfirmDialog]。
class AppDialog extends StatelessWidget {
  const AppDialog({
    super.key,
    required this.title,
    this.message,
    this.content,
    required this.actions,
  });

  final String title;
  final String? message;
  final Widget? content;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) => Dialog(
        backgroundColor: AppColors.bgCard,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.sheet),
        ),
        insetPadding:
            const EdgeInsets.symmetric(horizontal: AppSpacing.xxl),
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xxl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                title,
                textAlign: TextAlign.center,
                style: AppText.subtitle
                    .copyWith(fontSize: 17, color: AppColors.text1),
              ),
              if (message != null) ...[
                const SizedBox(height: AppSpacing.sm),
                Text(
                  message!,
                  textAlign: TextAlign.center,
                  style: AppText.caption.copyWith(color: AppColors.text2),
                ),
              ],
              if (content != null) ...[
                const SizedBox(height: AppSpacing.lg),
                content!,
              ],
              const SizedBox(height: AppSpacing.xxl),
              Row(
                children: [
                  for (var i = 0; i < actions.length; i++) ...[
                    if (i > 0) const SizedBox(width: AppSpacing.md),
                    Expanded(child: actions[i]),
                  ],
                ],
              ),
            ],
          ),
        ),
      );
}

/// 二次确认框:确认返回 true;取消 / 点外部返回 false。
Future<bool> showConfirmDialog(
  BuildContext context, {
  required String title,
  String? message,
  String cancelLabel = '取消',
  required String confirmLabel,
  bool danger = false,
  Key? confirmKey,
  bool barrierDismissible = true,
}) async {
  final confirmed = await showDialog<bool>(
    context: context,
    barrierDismissible: barrierDismissible,
    builder: (context) => AppDialog(
      title: title,
      message: message,
      actions: [
        AppButton(
          label: cancelLabel,
          variant: AppButtonVariant.secondary,
          onPressed: () => Navigator.pop(context, false),
        ),
        AppButton(
          key: confirmKey,
          label: confirmLabel,
          variant: danger ? AppButtonVariant.dangerFilled : AppButtonVariant.primary,
          onPressed: () => Navigator.pop(context, true),
        ),
      ],
    ),
  );
  return confirmed == true;
}
```

- [ ] **Step 5: 接入删除动态确认**

`app/lib/features/square/post_actions.dart`,把 `confirmDeletePost` 整段替换(其余不动):

```dart
/// 删除动态确认框(广场/详情/我的动态共用);用户确认返回 true。
Future<bool> confirmDeletePost(BuildContext context) => showConfirmDialog(
      context,
      title: '删除这条动态?',
      confirmLabel: '删除',
      confirmKey: const Key('post.delete.confirm'),
      danger: true,
    );
```

import 区:`import '../../core/widgets/app_toast.dart';` 之后加 `import '../../core/widgets/app_dialog.dart';`(按字母序 `app_dialog` 在 `app_toast` 之前,请放前面)。

- [ ] **Step 6: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/core/widgets/app_dialog_test.dart test/core/widgets/app_button_test.dart test/features/square/square_page_test.dart test/features/square/my_posts_page_test.dart test/features/square/post_detail_page_test.dart
```

Expected: 全 PASS。`square_page_test` 的删除用例断言 `post.delete.confirm` key,保留不变。

- [ ] **Step 7: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add -A
git commit -m "feat(ui): AppDialog/showConfirmDialog + AppButton.dangerFilled;删除动态确认接入" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 8: `AppProgressBar` + `AppFormSkeleton`

**Files:**
- Create: `app/lib/core/widgets/app_progress_bar.dart`
- Create: `app/lib/core/widgets/app_form_skeleton.dart`
- Test: `app/test/core/widgets/app_progress_bar_test.dart`
- Test: `app/test/core/widgets/app_form_skeleton_test.dart`

**Interfaces:**
- Consumes: `AppGradients` / `AppColors` / `AppMotion` / `AppSpacing` / `AppSkeleton` / `AppRadius`
- Produces:
  - `class AppProgressBar extends StatelessWidget`,构造 `const AppProgressBar({super.key, required int steps, required int current})`;高 4、段间 4;第 `i` 段填充 iff `i <= current`。
  - `class AppFormSkeleton extends StatelessWidget`,构造 `const AppFormSkeleton({super.key, int fields = 3})`;每段 = 标签条(64×12)+ 输入框块(通栏×52,`AppRadius.input`)。**含无限呼吸动画,相关用例只用有限 pump。**
  - Task 11(引导页进度)、Task 9/10/11(表单骨架)依赖。

- [ ] **Step 1: 写失败测试**

```dart
// app/test/core/widgets/app_progress_bar_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_colors.dart';
import 'package:chatapp_app/core/theme/app_gradients.dart';
import 'package:chatapp_app/core/widgets/app_progress_bar.dart';

void main() {
  testWidgets('3 段;第 0 段填充、其余 divider;高 4', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: AppProgressBar(steps: 3, current: 0)),
    ));

    final bars = find.descendant(
        of: find.byType(AppProgressBar), matching: find.byType(AnimatedContainer));
    expect(bars, findsNWidgets(3));

    BoxDecoration decorationAt(int index) =>
        tester.widget<AnimatedContainer>(bars.at(index)).decoration! as BoxDecoration;

    expect(decorationAt(0).gradient, AppGradients.heart);
    expect(decorationAt(1).gradient, isNull);
    expect(decorationAt(1).color, AppColors.divider);
    expect(tester.getSize(bars.at(0)).height, 4);
  });

  testWidgets('current=2 时三段全填充', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: AppProgressBar(steps: 3, current: 2)),
    ));
    final bars = find.descendant(
        of: find.byType(AppProgressBar), matching: find.byType(AnimatedContainer));
    for (var i = 0; i < 3; i++) {
      expect(
        (tester.widget<AnimatedContainer>(bars.at(i)).decoration! as BoxDecoration)
            .gradient,
        AppGradients.heart,
      );
    }
  });
}
```

```dart
// app/test/core/widgets/app_form_skeleton_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_form_skeleton.dart';
import 'package:chatapp_app/core/widgets/app_skeleton.dart';

void main() {
  testWidgets('fields=3 渲染 6 个骨架块(3 标签 + 3 输入框);只用有限 pump', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(
        body: Padding(
          padding: EdgeInsets.all(16),
          child: AppFormSkeleton(key: Key('sk')),
        ),
      ),
    ));
    await tester.pump(); // AppSkeleton 是无限呼吸动画,禁 pumpAndSettle
    expect(find.byKey(const Key('sk')), findsOneWidget);
    expect(find.byType(AppSkeleton), findsNWidgets(6));
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
../flutter/bin/flutter.bat test test/core/widgets/app_progress_bar_test.dart test/core/widgets/app_form_skeleton_test.dart
```

Expected: FAIL,两个文件都不存在(编译错误)。

- [ ] **Step 3: 写实现**

```dart
// app/lib/core/widgets/app_progress_bar.dart
import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_gradients.dart';
import '../theme/app_motion.dart';
import '../theme/app_spacing.dart';

/// 「心跳」分段进度(引导页用):高 4 胶囊,已过段 `gradientHeart`,未过段 `divider`。
/// 第 `i` 段填充当且仅当 `i <= current`(current 为 0 基的当前步骤)。
class AppProgressBar extends StatelessWidget {
  const AppProgressBar({super.key, required this.steps, required this.current});

  final int steps;
  final int current;

  static const height = 4.0;

  @override
  Widget build(BuildContext context) => Row(
        children: [
          for (var i = 0; i < steps; i++) ...[
            if (i > 0) const SizedBox(width: AppSpacing.xs),
            Expanded(
              child: AnimatedContainer(
                duration: AppMotion.base,
                height: height,
                decoration: BoxDecoration(
                  gradient: i <= current ? AppGradients.heart : null,
                  color: i <= current ? null : AppColors.divider,
                  borderRadius: BorderRadius.circular(height / 2),
                ),
              ),
            ),
          ],
        ],
      );
}
```

```dart
// app/lib/core/widgets/app_form_skeleton.dart
import 'package:flutter/material.dart';

import '../theme/app_radius.dart';
import '../theme/app_spacing.dart';
import 'app_skeleton.dart';

/// 「心跳」§7 表单页加载骨架:每组 = 标签条(64×12)+ 输入框块(通栏×52)。
/// 含无限呼吸动画 —— 可见它的用例只用有限 pump(`pumpFrames`),禁 `pumpAndSettle`。
class AppFormSkeleton extends StatelessWidget {
  const AppFormSkeleton({super.key, this.fields = 3});

  final int fields;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var i = 0; i < fields; i++) ...[
            if (i > 0) const SizedBox(height: AppSpacing.lg),
            const AppSkeleton(width: 64, height: 12),
            const SizedBox(height: AppSpacing.sm),
            const AppSkeleton(
              width: double.infinity,
              height: 52,
              radius: AppRadius.input,
            ),
          ],
        ],
      );
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/core/widgets/app_progress_bar_test.dart test/core/widgets/app_form_skeleton_test.dart
```

Expected: 3 例 PASS。

- [ ] **Step 5: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add -A
git commit -m "feat(ui): AppProgressBar(分段进度)+ AppFormSkeleton(表单骨架)" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 9: 编辑资料页 + 表单字段组件 + 标签选择 + 照片网格

**Files:**
- Modify: `app/lib/features/profile/widgets/profile_form_fields.dart`(五个具名组件换新控件)
- Modify: `app/lib/features/profile/widgets/tag_selector.dart`(`FilterChip` → `AppChipGroup`)
- Modify: `app/lib/features/profile/widgets/photo_grid.dart`(88 定宽 Wrap → 3 列 R12 网格 + 视觉整改)
- Modify: `app/lib/features/profile/profile_edit_page.dart`(整文件重写)
- Modify: `app/test/features/profile/profile_edit_page_test.dart`(Toast 收尾 + 用例名)
- Modify: `app/test/features/profile/photo_grid_test.dart`(Toast 收尾)

**Interfaces:**
- Consumes: Task 1–8 的全部组件
- Produces: `NicknameField` / `GenderSelector` / `BirthdayField` / `CityField` / `BioField` 对外构造签名**不变**(引导页共用);`TagSelector({required Set<int> selectedIds, required ValueChanged<Set<int>> onChanged})` 不变;`PhotoGrid({PickImage pickImage, int maxCount = 6})` 不变。Task 11 复用前四个字段组件与 `TagSelector`/`PhotoGrid`。

- [ ] **Step 1: 改既有断言(让现状红)**

`app/test/features/profile/profile_edit_page_test.dart`:

```dart
// :36 用例名
  testWidgets('后端 400(如违规词)→ AppToast 显示中文提示', (tester) async {
```

两个用例的 `expect(find.text('已保存'), findsOneWidget);` / `expect(find.text('昵称包含违规内容,请修改'), findsOneWidget);` **之后各补一行**:

```dart
    await drainToast(tester); // AppToast 2s Timer 收尾
```

`app/test/features/profile/photo_grid_test.dart`,`:63` 之后补:

```dart
    await drainToast(tester); // 『图片不能超过 5MB』走 AppToast,2s Timer 收尾
```

- [ ] **Step 2: 跑测试确认失败**

```bash
../flutter/bin/flutter.bat test test/features/profile/profile_edit_page_test.dart test/features/profile/photo_grid_test.dart
```

Expected: 先 FAIL —— 当前还是 `SnackBar`,没有 2s Timer,`drainToast` 不会报错但用例名/断言仍过;真正的红来自 Task 9 Step 5 改完提示通道后的行为变化。**此步的目的只是先把收尾脚手架放好**,若此时全绿属正常。

- [ ] **Step 3: 重写 `profile_form_fields.dart`**

```dart
// app/lib/features/profile/widgets/profile_form_fields.dart 整文件替换
import 'package:flutter/material.dart';

import '../../../core/format.dart';
import '../../../core/widgets/app_option_group.dart';
import '../../../core/widgets/app_picker_field.dart';
import '../../../core/widgets/app_text_field.dart';

/// 资料表单字段(批次⑥ 表单控件规范):全部是 core 组件的薄包装,
/// 对外构造签名与批次① 一致,编辑资料页与引导页共用。

class NicknameField extends StatelessWidget {
  const NicknameField({super.key, required this.controller, this.errorText});

  final TextEditingController controller;
  final String? errorText;

  @override
  Widget build(BuildContext context) => AppTextField(
        key: const Key('edit.nickname'),
        controller: controller,
        label: '昵称',
        maxLength: 20,
        errorText: errorText,
      );
}

class GenderSelector extends StatelessWidget {
  const GenderSelector({super.key, required this.value, required this.onChanged});

  final String? value;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('性别', style: AppText.caption.copyWith(color: AppColors.text2)),
          const SizedBox(height: AppSpacing.xs),
          AppOptionGroup<String>(
            options: const [
              AppOption(value: 'male', label: '男'),
              AppOption(value: 'female', label: '女'),
            ],
            value: value,
            onChanged: onChanged,
          ),
        ],
      );
}

class BirthdayField extends StatelessWidget {
  const BirthdayField({super.key, required this.value, required this.onChanged});

  final DateTime? value;
  final ValueChanged<DateTime> onChanged;

  @override
  Widget build(BuildContext context) => AppPickerField(
        key: const Key('edit.birthday'),
        label: '生日',
        value: value == null ? null : formatDate(value!),
        onTap: () async {
          final now = DateTime.now();
          final picked = await showDatePicker(
            context: context,
            initialDate: value ?? DateTime(now.year - 25, now.month, now.day),
            firstDate: DateTime(now.year - 100),
            lastDate: DateTime(now.year - 18, now.month, now.day), // 未满 18 岁选不出来
            helpText: '选择生日',
          );
          if (picked != null) onChanged(picked);
        },
      );
}

class CityField extends StatelessWidget {
  const CityField({super.key, required this.controller});

  final TextEditingController controller;

  @override
  Widget build(BuildContext context) => AppTextField(
        key: const Key('edit.city'),
        controller: controller,
        label: '城市',
        maxLength: 50,
      );
}

class BioField extends StatelessWidget {
  const BioField({super.key, required this.controller});

  final TextEditingController controller;

  @override
  Widget build(BuildContext context) => AppTextField(
        key: const Key('edit.bio'),
        controller: controller,
        label: '简介',
        maxLines: 3,
        maxLength: 200,
      );
}
```

**注意**:文件顶部要补 import:

```dart
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
```

- [ ] **Step 4: 重写 `tag_selector.dart`**

```dart
// app/lib/features/profile/widgets/tag_selector.dart 整文件替换
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_exception.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/app_chip_group.dart';
import '../../../core/widgets/app_option_group.dart';
import '../../../core/widgets/app_skeleton.dart';
import '../profile_controller.dart';

class TagSelector extends ConsumerWidget {
  const TagSelector({super.key, required this.selectedIds, required this.onChanged});

  final Set<int> selectedIds;
  final ValueChanged<Set<int>> onChanged;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tags = ref.watch(tagsProvider);
    return tags.when(
      // 三个胶囊骨架;AppSkeleton 是无限动画,可见它的用例只用有限 pump
      loading: () => const Row(
        children: [
          AppSkeleton(width: 64, height: 34, radius: AppRadius.full),
          SizedBox(width: AppSpacing.sm),
          AppSkeleton(width: 64, height: 34, radius: AppRadius.full),
          SizedBox(width: AppSpacing.sm),
          AppSkeleton(width: 64, height: 34, radius: AppRadius.full),
        ],
      ),
      error: (error, _) => Text(
        error is ApiException ? error.message : '标签加载失败',
        style: AppText.caption.copyWith(color: AppColors.text2),
      ),
      data: (list) => AppChipGroup<int>(
        items: [
          for (final tag in list) AppOption(value: tag.id, label: tag.name),
        ],
        selected: selectedIds,
        onChanged: onChanged,
      ),
    );
  }
}
```

- [ ] **Step 5: 重写 `photo_grid.dart`**

```dart
// app/lib/features/profile/widgets/photo_grid.dart 整文件替换
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_exception.dart';
import '../../../core/image_pick.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_motion.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/app_dialog.dart';
import '../../../core/widgets/app_toast.dart';
import '../models.dart';
import '../profile_controller.dart';
import '../profile_repository.dart';

const _maxBytes = 5 * 1024 * 1024;

/// 资料照片网格(§5.3 相册/照片网格:3 列、R12);最多 [maxCount] 张。
class PhotoGrid extends ConsumerStatefulWidget {
  const PhotoGrid({super.key, this.pickImage = pickImageFromGallery, this.maxCount = 6});

  /// 测试注入用;默认打开系统相册。
  final PickImage pickImage;
  final int maxCount;

  @override
  ConsumerState<PhotoGrid> createState() => _PhotoGridState();
}

class _PhotoGridState extends ConsumerState<PhotoGrid> {
  bool _busy = false;

  Future<void> _add() async {
    final file = await widget.pickImage();
    if (file == null) return;
    final bytes = await file.readAsBytes();
    if (!mounted) return;
    if (bytes.length > _maxBytes) {
      AppToast.show(context, '图片不能超过 5MB');
      return;
    }
    setState(() => _busy = true);
    try {
      await ref.read(profileRepositoryProvider).uploadPhoto(bytes, file.name);
      await ref.read(profileProvider.notifier).reload();
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _confirmDelete(Photo photo) async {
    final confirmed = await showConfirmDialog(
      context,
      title: '删除这张照片?',
      confirmLabel: '删除',
      danger: true,
    );
    if (!confirmed || !mounted) return;
    try {
      await ref.read(profileRepositoryProvider).deletePhoto(photo.id);
      await ref.read(profileProvider.notifier).reload();
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final photos = ref.watch(profileProvider).value?.photos ?? const <Photo>[];
    return GridView.count(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      crossAxisCount: 3,
      mainAxisSpacing: AppSpacing.sm,
      crossAxisSpacing: AppSpacing.sm,
      children: [
        for (final photo in photos)
          _PhotoTile(photo: photo, onDelete: () => _confirmDelete(photo)),
        if (photos.length < widget.maxCount)
          _AddTile(busy: _busy, onTap: _busy ? null : _add),
      ],
    );
  }
}

class _PhotoTile extends StatelessWidget {
  const _PhotoTile({required this.photo, required this.onDelete});

  final Photo photo;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) => Stack(
        fit: StackFit.expand,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(AppRadius.image),
            child: Image.network(
              photo.url,
              fit: BoxFit.cover,
              errorBuilder: (context, error, stack) => const ColoredBox(
                color: AppColors.divider,
                child: Center(
                  child: Icon(Icons.image_rounded, color: AppColors.text3),
                ),
              ),
            ),
          ),
          if (!photo.isApproved)
            Positioned(
              left: AppSpacing.xs,
              bottom: AppSpacing.xs,
              child: Container(
                padding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.sm, vertical: 2),
                decoration: BoxDecoration(
                  color: AppColors.amber,
                  borderRadius: BorderRadius.circular(AppRadius.chip),
                ),
                child: Text(
                  photo.status == 'pending' ? '待审核' : '已驳回',
                  style: AppText.badge.copyWith(color: Colors.white),
                ),
              ),
            ),
          Positioned(
            right: 0,
            top: 0,
            child: IconButton(
              key: Key('photo.delete.${photo.id}'),
              iconSize: 18,
              onPressed: onDelete,
              icon: const _RemoveBadge(),
            ),
          ),
        ],
      );
}

/// 半透明深底圆 + 白叉(照片右上角删除钮)。
class _RemoveBadge extends StatelessWidget {
  const _RemoveBadge();

  @override
  Widget build(BuildContext context) => Container(
        width: 22,
        height: 22,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: AppColors.text1.withValues(alpha: .55),
        ),
        child: const Icon(Icons.close_rounded, size: 14, color: Colors.white),
      );
}

class _AddTile extends StatefulWidget {
  const _AddTile({required this.busy, required this.onTap});

  final bool busy;
  final VoidCallback? onTap;

  @override
  State<_AddTile> createState() => _AddTileState();
}

class _AddTileState extends State<_AddTile> {
  var _pressed = false;

  @override
  Widget build(BuildContext context) => GestureDetector(
        key: const Key('photo.add'),
        onTapDown: widget.onTap == null ? null : (_) => setState(() => _pressed = true),
        onTapUp: widget.onTap == null ? null : (_) => setState(() => _pressed = false),
        onTapCancel: widget.onTap == null ? null : () => setState(() => _pressed = false),
        onTap: widget.onTap,
        child: AnimatedScale(
          scale: _pressed ? 0.96 : 1,
          duration: AppMotion.fast,
          child: DecoratedBox(
            decoration: BoxDecoration(
              color: AppColors.bgCard,
              borderRadius: BorderRadius.circular(AppRadius.image),
              border: Border.all(color: AppColors.divider),
            ),
            child: Center(
              child: widget.busy
                  // §7 加载:按钮内用白色小转圈 → 白底上用 brand 小转圈
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: AppColors.brand),
                    )
                  : const Icon(Icons.add_photo_alternate_rounded,
                      size: 24, color: AppColors.text3),
            ),
          ),
        ),
      );
}
```

- [ ] **Step 6: 重写 `profile_edit_page.dart`**

```dart
// app/lib/features/profile/profile_edit_page.dart 整文件替换
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_form_skeleton.dart';
import '../../core/widgets/app_section_card.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_text_action.dart';
import '../../core/widgets/app_toast.dart';
import 'models.dart';
import 'profile_controller.dart';
import 'widgets/photo_grid.dart';
import 'widgets/profile_form_fields.dart';
import 'widgets/tag_selector.dart';

/// 编辑资料(附录 E):二级页顶栏 + 三张分组卡(基本信息 / 关于我 / 照片)。
class ProfileEditPage extends ConsumerStatefulWidget {
  const ProfileEditPage({super.key});

  @override
  ConsumerState<ProfileEditPage> createState() => _ProfileEditPageState();
}

class _ProfileEditPageState extends ConsumerState<ProfileEditPage> {
  final _nickname = TextEditingController();
  final _city = TextEditingController();
  final _bio = TextEditingController();
  String? _gender;
  DateTime? _birthday;
  Set<int> _tagIds = {};
  bool _prefilled = false;
  bool _saving = false;

  @override
  void dispose() {
    _nickname.dispose();
    _city.dispose();
    _bio.dispose();
    super.dispose();
  }

  void _prefill(Profile profile) {
    if (_prefilled) return;
    _prefilled = true;
    _nickname.text = profile.nickname;
    _city.text = profile.city;
    _bio.text = profile.bio;
    _gender = profile.gender;
    _birthday = parseDate(profile.birthday);
    _tagIds = profile.tags.map((tag) => tag.id).toSet();
  }

  Future<void> _save() async {
    final nickname = _nickname.text.trim();
    if (nickname.isEmpty) {
      AppToast.show(context, '请填写昵称');
      return;
    }
    if (_birthday != null && !isAtLeast18(_birthday!)) {
      AppToast.show(context, '未满 18 周岁,无法使用本应用');
      return;
    }

    final patch = <String, dynamic>{
      'nickname': nickname,
      'city': _city.text.trim(),
      'bio': _bio.text.trim(),
      'tag_ids': _tagIds.toList(),
    };
    if (_gender != null) patch['gender'] = _gender;
    if (_birthday != null) patch['birthday'] = formatDate(_birthday!);

    setState(() => _saving = true);
    try {
      await ref.read(profileProvider.notifier).save(patch);
      if (!mounted) return;
      AppToast.show(context, '已保存');
      Navigator.of(context).pop();
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final profile = ref.watch(profileProvider);
    return Scaffold(
      backgroundColor: AppColors.bgPage,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            AppSubPageBar(
              title: '编辑资料',
              trailing: AppTextAction(
                key: const Key('edit.save'),
                label: _saving ? '保存中…' : '保存',
                onPressed: _saving ? null : _save,
              ),
            ),
            Expanded(
              child: profile.when(
                loading: () => const Padding(
                  padding: EdgeInsets.all(AppSpacing.pageH),
                  child: AppFormSkeleton(key: Key('edit.skeleton')),
                ),
                error: (error, _) => AppErrorView(
                  message: apiMessageOf(error),
                  retryKey: const Key('edit.retry'),
                  onRetry: () => ref.read(profileProvider.notifier).reload(),
                ),
                data: (data) {
                  _prefill(data);
                  return ListView(
                    padding: const EdgeInsets.fromLTRB(AppSpacing.pageH,
                        AppSpacing.md, AppSpacing.pageH, AppSpacing.xxl),
                    children: [
                      AppSectionCard(
                        title: '基本信息',
                        children: [
                          NicknameField(controller: _nickname),
                          GenderSelector(
                            value: _gender,
                            onChanged: (value) =>
                                setState(() => _gender = value),
                          ),
                          BirthdayField(
                            value: _birthday,
                            onChanged: (value) =>
                                setState(() => _birthday = value),
                          ),
                          CityField(controller: _city),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.cardGap),
                      AppSectionCard(
                        title: '关于我',
                        children: [
                          BioField(controller: _bio),
                          Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('标签',
                                  style: AppText.caption
                                      .copyWith(color: AppColors.text2)),
                              const SizedBox(height: AppSpacing.sm),
                              TagSelector(
                                selectedIds: _tagIds,
                                onChanged: (ids) =>
                                    setState(() => _tagIds = ids),
                              ),
                            ],
                          ),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.cardGap),
                      const AppSectionCard(
                        title: '照片',
                        children: [PhotoGrid()],
                      ),
                    ],
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}
```

- [ ] **Step 7: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/features/profile/
```

Expected: 全 PASS。若「加载中骨架」让某个 `pumpAndSettle` 超时,把该用例的 `pumpAndSettle` 换 `pumpFrames(tester)`(profileProvider 在真实链路里已预加载,通常不会触发)。

- [ ] **Step 8: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add -A
git commit -m "feat(ui): 编辑资料页 — 二级页顶栏/三张分组卡/表单控件规范落地;照片网格 3 列 R12" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 10: 想找的人页

**Files:**
- Modify: `app/lib/features/profile/preference_page.dart`(整文件重写)
- Modify: `app/test/features/profile/preference_page_test.dart`(Toast 收尾)

**Interfaces:**
- Consumes: `AppSubPageBar` / `AppTextAction` / `AppSectionCard` / `AppOptionGroup` / `AppRangeField` / `AppTextField` / `AppFormSkeleton` / `AppErrorView` / `AppToast` / `apiMessageOf`
- Produces: 页面级改动,无对外接口。key `preference.city` / `preference.save` 保留;新增 `preference.skeleton` / `preference.retry`。

- [ ] **Step 1: 改既有断言**

`app/test/features/profile/preference_page_test.dart`,`:36` 之后补:

```dart
    await drainToast(tester); // 『已保存』走 AppToast(挂根 Overlay,pop 后仍存活)
```

- [ ] **Step 2: 重写页面**

```dart
// app/lib/features/profile/preference_page.dart 整文件替换
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_form_skeleton.dart';
import '../../core/widgets/app_option_group.dart';
import '../../core/widgets/app_range_field.dart';
import '../../core/widgets/app_section_card.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_text_action.dart';
import '../../core/widgets/app_text_field.dart';
import '../../core/widgets/app_toast.dart';
import 'models.dart';
import 'profile_controller.dart';
import 'profile_repository.dart';

/// 想找的人(附录 E):目标性别 / 年龄区间 / 城市。
class PreferencePage extends ConsumerStatefulWidget {
  const PreferencePage({super.key});

  @override
  ConsumerState<PreferencePage> createState() => _PreferencePageState();
}

class _PreferencePageState extends ConsumerState<PreferencePage> {
  final _city = TextEditingController();
  String? _targetGender;
  RangeValues _ageRange = const RangeValues(18, 99);
  bool _prefilled = false;
  bool _saving = false;

  @override
  void dispose() {
    _city.dispose();
    super.dispose();
  }

  void _prefill(Preference preference) {
    if (_prefilled) return;
    _prefilled = true;
    _targetGender = preference.targetGender;
    _ageRange = RangeValues(
      preference.ageMin.toDouble(),
      preference.ageMax.toDouble().clamp(18, 99),
    );
    _city.text = preference.city;
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      await ref.read(profileRepositoryProvider).updatePreference({
        'target_gender': _targetGender,
        'age_min': _ageRange.start.round(),
        'age_max': _ageRange.end.round(),
        'city': _city.text.trim(),
      });
      if (!mounted) return;
      AppToast.show(context, '已保存');
      Navigator.of(context).pop();
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final profile = ref.watch(profileProvider);
    return Scaffold(
      backgroundColor: AppColors.bgPage,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            AppSubPageBar(
              title: '想找的人',
              trailing: AppTextAction(
                key: const Key('preference.save'),
                label: _saving ? '保存中…' : '保存',
                onPressed: _saving ? null : _save,
              ),
            ),
            Expanded(
              child: profile.when(
                loading: () => const Padding(
                  padding: EdgeInsets.all(AppSpacing.pageH),
                  child: AppFormSkeleton(key: Key('preference.skeleton')),
                ),
                error: (error, _) => AppErrorView(
                  message: apiMessageOf(error),
                  retryKey: const Key('preference.retry'),
                  onRetry: () => ref.read(profileProvider.notifier).reload(),
                ),
                data: (data) {
                  _prefill(data.preference);
                  return ListView(
                    padding: const EdgeInsets.fromLTRB(AppSpacing.pageH,
                        AppSpacing.md, AppSpacing.pageH, AppSpacing.xxl),
                    children: [
                      AppSectionCard(
                        title: '我想找',
                        children: [
                          AppOptionGroup<String>(
                            options: const [
                              AppOption(value: 'any', label: '不限'),
                              AppOption(value: 'male', label: '男'),
                              AppOption(value: 'female', label: '女'),
                            ],
                            value: _targetGender ?? 'any',
                            onChanged: (value) => setState(
                                () => _targetGender = value == 'any' ? null : value),
                          ),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.cardGap),
                      AppSectionCard(
                        children: [
                          AppRangeField(
                            title:
                                '年龄 ${_ageRange.start.round()} – ${_ageRange.end.round()} 岁',
                            values: _ageRange,
                            min: 18,
                            max: 99,
                            divisions: 81,
                            onChanged: (values) =>
                                setState(() => _ageRange = values),
                          ),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.cardGap),
                      AppSectionCard(
                        children: [
                          AppTextField(
                            key: const Key('preference.city'),
                            controller: _city,
                            label: '城市(留空 = 不限)',
                            maxLength: 50,
                          ),
                        ],
                      ),
                    ],
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}
```

- [ ] **Step 3: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/features/profile/preference_page_test.dart
```

Expected: PASS(`find.text('女')` 命中 `AppOptionGroup` 的段文字;`preference.save` 命中 `AppTextAction`)。

- [ ] **Step 4: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add -A
git commit -m "feat(ui): 想找的人页 — 分组卡 + 渐变分段 + 渐变轨道年龄区间" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 11: 引导页

**Files:**
- Modify: `app/lib/features/onboarding/onboarding_page.dart`(整文件重写)
- Modify: `app/test/features/onboarding/onboarding_page_test.dart`(Toast 收尾)

**Interfaces:**
- Consumes: Task 9 的 `NicknameField` / `GenderSelector` / `BirthdayField` / `CityField` / `BioField` / `TagSelector` / `PhotoGrid`;`AppSubPageBar` / `AppTextAction` / `AppProgressBar` / `AppSectionCard` / `AppButton` / `AppErrorView` / `AppToast`
- Produces: 纯函数 `validateBasicStep` / `validateAboutStep` 签名与返回值**零变化**(既有单测不动);key `onboarding.next` 保留;新增 `onboarding.progress` / `onboarding.retry`。

- [ ] **Step 1: 改既有断言**

`app/test/features/onboarding/onboarding_page_test.dart`,`:74` 之后补:

```dart
    await drainToast(tester); // 『请填写城市』走 AppToast,2s Timer 收尾
```

- [ ] **Step 2: 重写页面**

```dart
// app/lib/features/onboarding/onboarding_page.dart 整文件替换
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_form_skeleton.dart';
import '../../core/widgets/app_progress_bar.dart';
import '../../core/widgets/app_section_card.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_text_action.dart';
import '../../core/widgets/app_toast.dart';
import '../profile/models.dart';
import '../profile/profile_controller.dart';
import '../profile/widgets/photo_grid.dart';
import '../profile/widgets/profile_form_fields.dart';
import '../profile/widgets/tag_selector.dart';

String? validateBasicStep(
    {required String nickname, required String? gender, required DateTime? birthday}) {
  if (nickname.isEmpty) return '请填写昵称';
  if (gender == null) return '请选择性别';
  if (birthday == null) return '请选择生日';
  if (!isAtLeast18(birthday)) return '未满 18 周岁,无法使用本应用';
  return null;
}

String? validateAboutStep({required String city, required String bio}) {
  if (city.isEmpty) return '请填写城市';
  if (bio.isEmpty) return '请填写简介';
  return null;
}

/// 完善资料向导(附录 E):二级页顶栏 + 分段进度 + 三步表单 + 底部按钮行。
class OnboardingPage extends ConsumerStatefulWidget {
  const OnboardingPage({super.key});

  @override
  ConsumerState<OnboardingPage> createState() => _OnboardingPageState();
}

class _OnboardingPageState extends ConsumerState<OnboardingPage> {
  final _pageController = PageController();
  final _nickname = TextEditingController();
  final _city = TextEditingController();
  final _bio = TextEditingController();
  String? _gender;
  DateTime? _birthday;
  Set<int> _tagIds = {};
  bool _prefilled = false;
  bool _busy = false;
  int _step = 0;

  @override
  void dispose() {
    _pageController.dispose();
    _nickname.dispose();
    _city.dispose();
    _bio.dispose();
    super.dispose();
  }

  void _prefill(Profile profile) {
    if (_prefilled) return;
    _prefilled = true;
    _nickname.text = profile.nickname;
    _city.text = profile.city;
    _bio.text = profile.bio;
    _gender = profile.gender;
    _birthday = parseDate(profile.birthday);
    _tagIds = profile.tags.map((tag) => tag.id).toSet();
  }

  void _goToStep(int step) {
    setState(() => _step = step);
    _pageController.animateToPage(step,
        duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
  }

  Future<void> _next() async {
    Map<String, dynamic>? patch;
    if (_step == 0) {
      final error = validateBasicStep(
          nickname: _nickname.text.trim(), gender: _gender, birthday: _birthday);
      if (error != null) {
        AppToast.show(context, error);
        return;
      }
      patch = {
        'nickname': _nickname.text.trim(),
        'gender': _gender,
        'birthday': formatDate(_birthday!),
      };
    } else if (_step == 1) {
      final error = validateAboutStep(city: _city.text.trim(), bio: _bio.text.trim());
      if (error != null) {
        AppToast.show(context, error);
        return;
      }
      patch = {
        'city': _city.text.trim(),
        'bio': _bio.text.trim(),
        'tag_ids': _tagIds.toList(),
      };
    } else {
      await _finish();
      return;
    }

    setState(() => _busy = true);
    try {
      await ref.read(profileProvider.notifier).save(patch);
      if (!mounted) return;
      _goToStep(_step + 1);
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _finish() async {
    setState(() => _busy = true);
    try {
      await ref.read(profileProvider.notifier).reload();
      if (!mounted) return;
      final profile = ref.read(profileProvider).value;
      if (profile == null || profile.photos.where((photo) => photo.isApproved).isEmpty) {
        AppToast.show(context, '至少上传一张照片');
        return;
      }
      context.go('/home');
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final profile = ref.watch(profileProvider);
    return Scaffold(
      backgroundColor: AppColors.bgPage,
      body: SafeArea(
        bottom: false,
        child: profile.when(
          loading: () => const Padding(
            padding: EdgeInsets.all(AppSpacing.pageH),
            child: AppFormSkeleton(key: Key('onboarding.skeleton')),
          ),
          error: (error, _) => AppErrorView(
            message: apiMessageOf(error),
            retryKey: const Key('onboarding.retry'),
            onRetry: () => ref.read(profileProvider.notifier).reload(),
          ),
          data: (data) {
            _prefill(data);
            return Column(
              children: [
                AppSubPageBar(
                  title: '完善资料',
                  trailing: AppTextAction(
                    label: '稍后再说',
                    onPressed: () => context.go('/home'),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(AppSpacing.pageH,
                      AppSpacing.sm, AppSpacing.pageH, AppSpacing.md),
                  child: Column(
                    children: [
                      AppProgressBar(
                        key: const Key('onboarding.progress'),
                        steps: 3,
                        current: _step,
                      ),
                      const SizedBox(height: AppSpacing.sm),
                      Text('第 ${_step + 1} 步 / 共 3 步',
                          style:
                              AppText.caption.copyWith(color: AppColors.text2)),
                    ],
                  ),
                ),
                Expanded(
                  child: PageView(
                    controller: _pageController,
                    physics: const NeverScrollableScrollPhysics(),
                    children: [
                      _StepBasic(
                        nickname: _nickname,
                        gender: _gender,
                        birthday: _birthday,
                        onGenderChanged: (value) =>
                            setState(() => _gender = value),
                        onBirthdayChanged: (value) =>
                            setState(() => _birthday = value),
                      ),
                      _StepAbout(
                        city: _city,
                        bio: _bio,
                        tagIds: _tagIds,
                        onTagsChanged: (ids) => setState(() => _tagIds = ids),
                      ),
                      const _StepPhotos(),
                    ],
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.all(AppSpacing.lg),
                  child: Row(
                    children: [
                      if (_step > 0) ...[
                        AppButton(
                          label: '上一步',
                          variant: AppButtonVariant.secondary,
                          onPressed: _busy ? null : () => _goToStep(_step - 1),
                        ),
                        const SizedBox(width: AppSpacing.md),
                      ],
                      Expanded(
                        child: AppButton(
                          key: const Key('onboarding.next'),
                          label: _step == 2 ? '完成' : '下一步',
                          onPressed: _busy ? null : _next,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _StepBasic extends StatelessWidget {
  const _StepBasic({
    required this.nickname,
    required this.gender,
    required this.birthday,
    required this.onGenderChanged,
    required this.onBirthdayChanged,
  });

  final TextEditingController nickname;
  final String? gender;
  final DateTime? birthday;
  final ValueChanged<String> onGenderChanged;
  final ValueChanged<DateTime> onBirthdayChanged;

  @override
  Widget build(BuildContext context) => ListView(
        padding: const EdgeInsets.all(AppSpacing.pageH),
        children: [
          AppSectionCard(
            title: '基本信息',
            children: [
              NicknameField(controller: nickname),
              GenderSelector(value: gender, onChanged: onGenderChanged),
              BirthdayField(value: birthday, onChanged: onBirthdayChanged),
            ],
          ),
        ],
      );
}

class _StepAbout extends StatelessWidget {
  const _StepAbout({
    required this.city,
    required this.bio,
    required this.tagIds,
    required this.onTagsChanged,
  });

  final TextEditingController city;
  final TextEditingController bio;
  final Set<int> tagIds;
  final ValueChanged<Set<int>> onTagsChanged;

  @override
  Widget build(BuildContext context) => ListView(
        padding: const EdgeInsets.all(AppSpacing.pageH),
        children: [
          AppSectionCard(
            title: '关于我',
            children: [
              CityField(controller: city),
              BioField(controller: bio),
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('标签(可多选)',
                      style: AppText.caption.copyWith(color: AppColors.text2)),
                  const SizedBox(height: AppSpacing.sm),
                  TagSelector(selectedIds: tagIds, onChanged: onTagsChanged),
                ],
              ),
            ],
          ),
        ],
      );
}

class _StepPhotos extends StatelessWidget {
  const _StepPhotos();

  @override
  Widget build(BuildContext context) => ListView(
        padding: const EdgeInsets.all(AppSpacing.pageH),
        children: [
          AppSectionCard(
            title: '照片',
            children: [
              Text('上传至少 1 张照片(最多 6 张),让别人认识你',
                  style: AppText.caption.copyWith(color: AppColors.text2)),
              const SizedBox(height: AppSpacing.md),
              const PhotoGrid(),
            ],
          ),
        ],
      );
}
```

**注意**:`AppProgressBar` 的 `current` 必须随 `_step` 变(上面已是 `current: _step`,不要再加 `const`)。

- [ ] **Step 3: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/features/onboarding/onboarding_page_test.dart
```

Expected: 3 例 PASS(「第 1 步 / 共 3 步」「第 2 步 / 共 3 步」文案保留、`onboarding.next` key 保留、校验纯函数未动)。

- [ ] **Step 4: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add -A
git commit -m "feat(ui): 引导页 — 顶栏/分段进度/三步分组卡表单" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 12: 登录页

**Files:**
- Modify: `app/lib/features/auth/login_page.dart`(整文件重写)
- Modify: `app/test/features/auth/login_page_test.dart`(Toast 收尾)
- Modify: `app/test/features/auth/kicked_offline_test.dart`(Toast 收尾)
- Modify: `app/test/features/auth/account_switch_test.dart`(Toast 收尾)

**Interfaces:**
- Consumes: `AppBrandMark` / `AppSectionCard` / `AppTextField` / `AppTextAction` / `AppButton` / `AppToast`
- Produces: 页面级改动,无对外接口。key `login.phone` / `login.code` / `login.sendCode` / `login.submit` 保留;新增 `login.brand`。**品牌区必须静态**(Global Constraints)。

- [ ] **Step 1: 改既有断言**

`app/test/features/auth/login_page_test.dart`:在三个用例的末尾断言之后各补一行。

```dart
// 「手机号格式不对 → 不发请求」(:38 之后)
    await drainToast(tester); // 『请输入正确的手机号』走 AppToast
```

```dart
// 「verify 网络两次都失败 → 提示可直接再点登录」(:92 之后)
    await drainToast(tester);
```

```dart
// 「verify 业务错误(码过期)不重试」(:112 之后)
    await drainToast(tester);
```

「获取验证码 → 倒计时」例已有 `await tester.pumpWidget(const SizedBox());` 卸树取消 Timer,**不需要** drain。

`app/test/features/auth/kicked_offline_test.dart`:两个用例末尾各补:

```dart
    await drainToast(tester); // 登录页首帧的「被顶下线原因」走 AppToast
```

`app/test/features/auth/account_switch_test.dart`:`:41`(`expect(find.byKey(const Key('login.phone')), findsOneWidget);`)之后补:

```dart
    await drainToast(tester); // 被顶号原因提示走 AppToast
```

- [ ] **Step 2: 重写页面**

```dart
// app/lib/features/auth/login_page.dart 整文件替换
import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/providers.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_brand_mark.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_section_card.dart';
import '../../core/widgets/app_text_action.dart';
import '../../core/widgets/app_text_field.dart';
import '../../core/widgets/app_toast.dart';
import 'auth_repository.dart';
import 'session.dart';

/// 登录页(附录 E):品牌区 + 表单卡 + 渐变主按钮。
/// 品牌区**静态无动画** —— 本页有大量 pumpAndSettle 用例(Global Constraints)。
class LoginPage extends ConsumerStatefulWidget {
  const LoginPage({super.key});

  @override
  ConsumerState<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends ConsumerState<LoginPage> {
  static final _phonePattern = RegExp(r'^1[3-9]\d{9}$');

  final _phoneController = TextEditingController();
  final _codeController = TextEditingController();
  Timer? _timer;
  int _countdown = 0;
  bool _sending = false;
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    // 被踢/强退带过来的原因(一次性信号):首帧后提示,让用户知道为什么被退出
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final reason = ref.read(tokenStoreProvider).takeForceLogoutReason();
      if (reason != null) AppToast.show(context, reason);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _phoneController.dispose();
    _codeController.dispose();
    super.dispose();
  }

  Future<void> _sendCode() async {
    final phone = _phoneController.text.trim();
    if (!_phonePattern.hasMatch(phone)) {
      AppToast.show(context, '请输入正确的手机号');
      return;
    }
    setState(() => _sending = true);
    try {
      await ref.read(authRepositoryProvider).sendSms(phone);
      if (!mounted) return;
      _startCountdown();
      AppToast.show(context, '验证码已发送,请查看短信');
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  void _startCountdown() {
    _timer?.cancel();
    setState(() => _countdown = 60);
    _timer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) {
        timer.cancel();
        return;
      }
      if (_countdown <= 1) {
        timer.cancel();
        setState(() => _countdown = 0);
      } else {
        setState(() => _countdown -= 1);
      }
    });
  }

  Future<void> _submit() async {
    final phone = _phoneController.text.trim();
    final code = _codeController.text.trim();
    if (!_phonePattern.hasMatch(phone)) {
      AppToast.show(context, '请输入正确的手机号');
      return;
    }
    if (code.length != 6) {
      AppToast.show(context, '请输入 6 位验证码');
      return;
    }
    setState(() => _submitting = true);
    try {
      final result = await ref.read(sessionProvider.notifier).login(phone, code);
      if (!mounted) return;
      context.go(result.isNewUser ? '/onboarding' : '/home');
    } on ApiException catch (error) {
      if (mounted) {
        AppToast.show(
          context,
          error.statusCode == null ? '网络超时,可直接再次点击「登录」重试' : error.message,
        );
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.bgPage,
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(AppSpacing.xxl),
          children: [
            const SizedBox(height: AppSpacing.xxl),
            const Center(child: AppBrandMark(key: Key('login.brand'))),
            const SizedBox(height: AppSpacing.lg),
            Text('交友 Chat',
                textAlign: TextAlign.center,
                style: AppText.display.copyWith(color: AppColors.text1)),
            const SizedBox(height: AppSpacing.xs),
            Text('手机号登录 / 注册',
                textAlign: TextAlign.center,
                style: AppText.caption.copyWith(color: AppColors.text2)),
            const SizedBox(height: AppSpacing.xxl),
            AppSectionCard(
              children: [
                AppTextField(
                  key: const Key('login.phone'),
                  controller: _phoneController,
                  label: '手机号',
                  keyboardType: TextInputType.phone,
                  maxLength: 11,
                ),
                AppTextField(
                  key: const Key('login.code'),
                  controller: _codeController,
                  label: '验证码',
                  keyboardType: TextInputType.number,
                  maxLength: 6,
                  suffix: AppTextAction(
                    key: const Key('login.sendCode'),
                    label: _countdown > 0 ? '$_countdown 秒后重发' : '获取验证码',
                    onPressed: (_sending || _countdown > 0) ? null : _sendCode,
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.xxl),
            AppButton(
              key: const Key('login.submit'),
              label: _submitting ? '登录中…' : '登录 / 注册',
              onPressed: _submitting ? null : _submit,
            ),
            const SizedBox(height: AppSpacing.lg),
            if (kDebugMode)
              Text('开发模式:验证码固定 123456',
                  textAlign: TextAlign.center,
                  style: AppText.micro.copyWith(color: AppColors.text3)),
          ],
        ),
      ),
    );
  }
}
```

- [ ] **Step 3: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/features/auth/ test/features/legal/agreement_gate_test.dart
```

Expected: 全 PASS。

- [ ] **Step 4: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add -A
git commit -m "feat(ui): 登录页 — 静态品牌区 + 表单卡 + 输入框内嵌验证码按钮 + AppToast" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 13: 启动页 + 协议弹窗

**Files:**
- Modify: `app/lib/features/auth/splash_page.dart`(整文件重写)
- Modify: `app/lib/features/legal/agreement_dialog.dart`(换 `AppDialog`)
- Modify: `app/test/features/legal/agreement_gate_test.dart`(过期注释)

**Interfaces:**
- Consumes: `AppBrandMark` / `AppButton` / `AppErrorView` / `AppDialog` / `AppTextAction`
- Produces: `showAgreementDialog(BuildContext) → Future<bool?>` 签名与返回值**不变**;key `splash.reread` / `agreement.accept` / `agreement.decline` 保留;新增 `splash.brand` / `splash.retry`。

- [ ] **Step 1: 更新过期注释**

`app/test/features/legal/agreement_gate_test.dart:11`:

```dart
  // 协议弹窗在 _start 的 prefs 读取之后才出现,固定推两帧最省;启动页已无转圈动画,
  // 但这里仍保持有限 pump(不依赖弹窗之外的动画行为)。
  Future<void> pumpUntilDialog(WidgetTester tester) async {
```

- [ ] **Step 2: 重写协议弹窗**

```dart
// app/lib/features/legal/agreement_dialog.dart 整文件替换
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/app_spacing.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_dialog.dart';
import '../../core/widgets/app_text_action.dart';

/// 首启协议弹窗:不可点外部关闭;同意返回 true,不同意返回 false。
Future<bool?> showAgreementDialog(BuildContext context) => showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AppDialog(
        title: '用户协议与隐私政策',
        message: '欢迎使用「交友 Chat」。请阅读并同意以下文件后再开始使用:',
        content: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            AppTextAction(
              label: '《用户协议》',
              onPressed: () => context.push('/legal/agreement'),
            ),
            const SizedBox(height: AppSpacing.xs),
            AppTextAction(
              label: '《隐私政策》',
              onPressed: () => context.push('/legal/privacy'),
            ),
          ],
        ),
        actions: [
          AppButton(
            key: const Key('agreement.decline'),
            label: '不同意',
            variant: AppButtonVariant.secondary,
            onPressed: () => Navigator.pop(context, false),
          ),
          AppButton(
            key: const Key('agreement.accept'),
            label: '同意并继续',
            onPressed: () => Navigator.pop(context, true),
          ),
        ],
      ),
    );
```

- [ ] **Step 3: 重写启动页**

```dart
// app/lib/features/auth/splash_page.dart 整文件替换
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_brand_mark.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_error_view.dart';
import '../legal/agreement_dialog.dart';
import '../legal/legal_gate.dart';
import 'session.dart';

/// 启动页(附录 E):静态品牌区 + 状态文案。
/// **去掉原 CircularProgressIndicator** —— 常驻无限动画会让 pumpAndSettle 用例不收敛。
class SplashPage extends ConsumerStatefulWidget {
  const SplashPage({super.key});

  @override
  ConsumerState<SplashPage> createState() => _SplashPageState();
}

class _SplashPageState extends ConsumerState<SplashPage> {
  bool _agreementDeclined = false;

  @override
  void initState() {
    super.initState();
    // 第一步就是 await,状态变更发生在异步之后,initState 里触发是安全的
    _start();
  }

  Future<void> _start() async {
    if (_agreementDeclined) setState(() => _agreementDeclined = false);
    if (!await hasAgreedToLegal()) {
      if (!mounted) return;
      final accepted = await showAgreementDialog(context);
      if (accepted != true) {
        if (!mounted) return;
        setState(() => _agreementDeclined = true);
        if (defaultTargetPlatform == TargetPlatform.android ||
            defaultTargetPlatform == TargetPlatform.iOS) {
          SystemNavigator.pop(); // 移动端直接退出;上面的提示页只是兜底
        }
        return;
      }
      await acceptLegal();
    }
    if (!mounted) return;
    ref.read(sessionProvider.notifier).bootstrap();
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider);
    return Scaffold(
      backgroundColor: AppColors.bgPage,
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xxl),
          child: switch (session) {
            SessionBootFailed(:final message) => AppErrorView(
                message: message,
                retryKey: const Key('splash.retry'),
                onRetry: () => ref.read(sessionProvider.notifier).bootstrap(),
              ),
            _ when _agreementDeclined => Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const AppBrandMark(key: Key('splash.brand')),
                  const SizedBox(height: AppSpacing.lg),
                  Text(
                    '需要同意《用户协议》与《隐私政策》才能使用本应用',
                    textAlign: TextAlign.center,
                    style: AppText.caption.copyWith(color: AppColors.text2),
                  ),
                  const SizedBox(height: AppSpacing.xxl),
                  AppButton(
                    key: const Key('splash.reread'),
                    label: '重新阅读',
                    onPressed: _start,
                  ),
                ],
              ),
            _ => Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const AppBrandMark(key: Key('splash.brand')),
                  const SizedBox(height: AppSpacing.lg),
                  Text('交友 Chat',
                      style: AppText.title.copyWith(color: AppColors.text1)),
                  const SizedBox(height: AppSpacing.xs),
                  Text('正在启动…',
                      style: AppText.caption.copyWith(color: AppColors.text2)),
                ],
              ),
          },
        ),
      ),
    );
  }
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/features/legal/ test/features/auth/
```

Expected: 全 PASS。

- [ ] **Step 5: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add -A
git commit -m "feat(ui): 启动页静态品牌区(去常驻转圈)+ 协议弹窗换 AppDialog" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 14: 设置页

**Files:**
- Modify: `app/lib/features/settings/settings_page.dart`(整文件重写)
- Modify: `app/test/features/settings/settings_page_test.dart`(加分组断言)

**Interfaces:**
- Consumes: `AppSubPageBar` / `AppRowGroup` / `AppListRow` / `showConfirmDialog`
- Produces: 页面级改动,无对外接口。新增 key `settings.row.blocks` / `settings.row.agreement` / `settings.row.privacy` / `settings.logout`。

- [ ] **Step 1: 加断言**

`app/test/features/settings/settings_page_test.dart`,`:26`(`await tester.pumpAndSettle();` 进设置页之后)插入:

```dart
    expect(find.byKey(const Key('settings.row.blocks')), findsOneWidget);
    expect(find.byKey(const Key('settings.row.agreement')), findsOneWidget);
    expect(find.byKey(const Key('settings.row.privacy')), findsOneWidget);
    expect(find.byKey(const Key('settings.logout')), findsOneWidget);
```

- [ ] **Step 2: 重写页面**

```dart
// app/lib/features/settings/settings_page.dart 整文件替换
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/widgets/app_dialog.dart';
import '../../core/widgets/app_list_row.dart';
import '../../core/widgets/app_row_group.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../auth/session.dart';

/// 设置页(附录 E):二级页顶栏 + 两张行分组卡。
class SettingsPage extends ConsumerWidget {
  const SettingsPage({super.key});

  Future<void> _logout(BuildContext context, WidgetRef ref) async {
    final confirmed = await showConfirmDialog(
      context,
      title: '退出登录?',
      message: '退出后需要重新用手机号登录',
      confirmLabel: '退出',
      danger: true,
    );
    if (!confirmed) return;
    await ref.read(sessionProvider.notifier).logout();
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) => Scaffold(
        backgroundColor: AppColors.bgPage,
        body: SafeArea(
          bottom: false,
          child: Column(
            children: [
              const AppSubPageBar(title: '设置'),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(AppSpacing.pageH,
                      AppSpacing.md, AppSpacing.pageH, AppSpacing.xxl),
                  children: [
                    AppRowGroup(
                      children: [
                        AppListRow(
                          key: const Key('settings.row.blocks'),
                          icon: Icons.block_rounded,
                          title: '黑名单',
                          onTap: () => context.push('/settings/blocks'),
                        ),
                        AppListRow(
                          key: const Key('settings.row.agreement'),
                          icon: Icons.description_rounded,
                          title: '用户协议',
                          onTap: () => context.push('/legal/agreement'),
                        ),
                        AppListRow(
                          key: const Key('settings.row.privacy'),
                          icon: Icons.privacy_tip_rounded,
                          title: '隐私政策',
                          onTap: () => context.push('/legal/privacy'),
                        ),
                      ],
                    ),
                    const SizedBox(height: AppSpacing.cardGap),
                    AppRowGroup(
                      children: [
                        AppListRow(
                          key: const Key('settings.logout'),
                          title: '退出登录',
                          centerTitle: true,
                          danger: true,
                          onTap: () => _logout(context, ref),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
}
```

- [ ] **Step 3: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/features/settings/settings_page_test.dart
```

Expected: PASS(`find.text('退出登录')` 命中居中行,`find.text('退出')` 命中 `AppDialog` 的确认按钮)。

- [ ] **Step 4: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add -A
git commit -m "feat(ui): 设置页 — 二级页顶栏 + 行分组卡 + 居中危险退出行 + AppDialog 确认" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 15: 黑名单页

**Files:**
- Create: `app/lib/features/settings/widgets/blocked_users_skeleton.dart`
- Modify: `app/lib/features/settings/blocked_users_page.dart`(整文件重写)
- Modify: `app/test/features/settings/blocked_users_page_test.dart`(Toast 收尾 + 骨架/错误用例)

**Interfaces:**
- Consumes: `AppSubPageBar` / `AppListRow` / `AppAvatar` / `AppTextAction` / `AppEmptyState` / `AppErrorView` / `AppSkeleton` / `showConfirmDialog` / `AppToast` / `apiMessageOf`
- Produces: `class BlockedUsersSkeleton extends StatelessWidget`,构造 `const BlockedUsersSkeleton({super.key})`,根 key `blocked.skeleton`。页面新增 key `blocked.empty` / `blocked.retry`;`unblock.{id}` / `unblock.confirm` 保留。

- [ ] **Step 1: 写失败测试**

`app/test/features/settings/blocked_users_page_test.dart`:

```dart
// 「列表 + 解除拉黑」用例 :61 之后补
    await drainToast(tester); // 『已解除拉黑』走 AppToast
```

```dart
// 文件末尾追加两个用例
  testWidgets('加载失败 → AppErrorView,blocked.retry 重试成功', (tester) async {
    adapter.routes['GET /blocks'] = offline;
    await pumpBlocked(tester);
    expect(find.byKey(const Key('blocked.retry')), findsOneWidget);

    adapter.routes['GET /blocks'] =
        (options) => ok(pageJson([blockedUserJson(userId: 9, nickname: '小红')]));
    await tester.tap(find.byKey(const Key('blocked.retry')));
    await tester.pumpAndSettle();
    expect(find.text('小红'), findsOneWidget);
  });

  testWidgets('空态带 blocked.empty key', (tester) async {
    adapter.routes['GET /blocks'] = (options) => ok(pageJson([]));
    await pumpBlocked(tester);
    expect(find.byKey(const Key('blocked.empty')), findsOneWidget);
    expect(find.text('还没有拉黑任何人'), findsOneWidget);
  });
```

- [ ] **Step 2: 跑测试确认失败**

```bash
../flutter/bin/flutter.bat test test/features/settings/blocked_users_page_test.dart
```

Expected: FAIL(`blocked.retry` / `blocked.empty` 不存在)。

- [ ] **Step 3: 写骨架组件**

```dart
// app/lib/features/settings/widgets/blocked_users_skeleton.dart
import 'package:flutter/material.dart';

import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/widgets/app_skeleton.dart';

/// 黑名单加载骨架(附录 E):3 行「圆头像 44 + 两条文字条」。
/// 含无限呼吸动画 —— 可见它的用例只用有限 pump。
class BlockedUsersSkeleton extends StatelessWidget {
  const BlockedUsersSkeleton({super.key});

  @override
  Widget build(BuildContext context) => Column(
        key: const Key('blocked.skeleton'),
        children: [
          for (var i = 0; i < 3; i++)
            const Padding(
              padding: EdgeInsets.symmetric(
                horizontal: AppSpacing.lg,
                vertical: AppSpacing.md,
              ),
              child: Row(
                children: [
                  AppSkeleton(width: 44, height: 44, radius: AppRadius.full),
                  SizedBox(width: AppSpacing.md),
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      AppSkeleton(width: 120, height: 14),
                      SizedBox(height: AppSpacing.xs),
                      AppSkeleton(width: 96, height: 12),
                    ],
                  ),
                ],
              ),
            ),
        ],
      );
}
```

- [ ] **Step 4: 重写页面**

```dart
// app/lib/features/settings/blocked_users_page.dart 整文件替换
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/widgets/app_avatar.dart';
import '../../core/widgets/app_dialog.dart';
import '../../core/widgets/app_empty_state.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_list_row.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_text_action.dart';
import '../../core/widgets/app_toast.dart';
import '../moderation/models.dart';
import '../moderation/moderation_controller.dart';
import '../moderation/moderation_repository.dart';
import 'widgets/blocked_users_skeleton.dart';

/// 黑名单(附录 E):二级页顶栏 + 圆头像列表行 + 解除确认。
class BlockedUsersPage extends ConsumerWidget {
  const BlockedUsersPage({super.key});

  Future<void> _unblock(
      BuildContext context, WidgetRef ref, BlockedUser user) async {
    final confirmed = await showConfirmDialog(
      context,
      title: '解除对 ${user.nickname} 的拉黑?',
      message: '解除后你们将重新互相可见',
      confirmLabel: '解除',
      confirmKey: const Key('unblock.confirm'),
    );
    if (!confirmed) return;
    try {
      await ref.read(moderationRepositoryProvider).unblock(user.userId);
      await ref.read(blockedUsersProvider.notifier).reload();
      if (context.mounted) AppToast.show(context, '已解除拉黑');
    } on ApiException catch (error) {
      if (context.mounted) AppToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final blocked = ref.watch(blockedUsersProvider);
    return Scaffold(
      backgroundColor: AppColors.bgPage,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            const AppSubPageBar(title: '黑名单'),
            Expanded(
              child: blocked.when(
                loading: () => const BlockedUsersSkeleton(),
                error: (error, _) => AppErrorView(
                  message:
                      error is ApiException ? error.message : '加载失败,请重试',
                  retryKey: const Key('blocked.retry'),
                  onRetry: () =>
                      ref.read(blockedUsersProvider.notifier).reload(),
                ),
                data: (items) => items.isEmpty
                    ? const Center(
                        child: AppEmptyState(
                          key: Key('blocked.empty'),
                          emoji: '🙈',
                          title: '还没有拉黑任何人',
                          description: '被你拉黑的人不会再出现在发现页',
                        ),
                      )
                    : ListView.separated(
                        padding:
                            const EdgeInsets.symmetric(vertical: AppSpacing.sm),
                        itemCount: items.length,
                        separatorBuilder: (_, _) => const Divider(
                          height: 1,
                          indent: 72,
                          color: AppColors.divider,
                        ),
                        itemBuilder: (context, index) {
                          final user = items[index];
                          return AppListRow(
                            avatar: AppAvatar(
                              size: 44,
                              imageUrl: user.avatarUrl,
                              fallbackText: user.nickname,
                            ),
                            title: user.nickname,
                            subtitle: _dateLabel(user.blockedAt),
                            trailing: AppTextAction(
                              key: Key('unblock.${user.userId}'),
                              label: '解除',
                              onPressed: () => _unblock(context, ref, user),
                            ),
                          );
                        },
                      ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

String _dateLabel(DateTime? time) {
  if (time == null) return '已拉黑';
  String two(int value) => value.toString().padLeft(2, '0');
  return '拉黑于 ${time.year}-${two(time.month)}-${two(time.day)}';
}
```

- [ ] **Step 5: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/features/settings/blocked_users_page_test.dart
```

Expected: 4 例 PASS。

- [ ] **Step 6: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add -A
git commit -m "feat(ui): 黑名单页 — 骨架/空态/错误三态 + 圆头像列表行 + AppDialog 确认" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 16: 发动态页 + `ComposePhotoGrid`

**Files:**
- Create: `app/lib/features/square/widgets/compose_photo_grid.dart`
- Modify: `app/lib/features/square/post_compose_page.dart`(整文件重写)
- Modify: `app/test/features/square/post_compose_page_test.dart`(`FilledButton` → `AppTextAction`)
- Modify: `app/test/features/square/square_page_test.dart`(过期注释)

**Interfaces:**
- Consumes: `AppSubPageBar` / `AppTextAction` / `AppTextField` / `AppToast`
- Produces: `class ComposePhotoGrid extends StatelessWidget`,构造 `const ComposePhotoGrid({super.key, required List<Uint8List> images, required ValueChanged<int> onRemove, required VoidCallback onAdd, int maxCount = 9})`;key `compose.add` / `compose.picked.{i}`。页面保留 `compose.text` / `compose.submit`,新增 `compose.counter`。

- [ ] **Step 1: 改既有断言**

`app/test/features/square/post_compose_page_test.dart`:

```dart
// :1 之后的 import 区补
import 'package:chatapp_app/core/widgets/app_text_action.dart';
```

```dart
// :44、:48 两行
    expect(tester.widget<AppTextAction>(button).onPressed, isNull);   // 置灰
    ...
    expect(tester.widget<AppTextAction>(button).onPressed, isNotNull);
```

`app/test/features/square/square_page_test.dart:57`:

```dart
    expect(find.text('发布动态'), findsOneWidget); // 发布页顶栏标题
```

- [ ] **Step 2: 跑测试确认失败**

```bash
../flutter/bin/flutter.bat test test/features/square/post_compose_page_test.dart
```

Expected: FAIL —— 当前顶栏是 `FilledButton`,`tester.widget<AppTextAction>` 类型不符抛错。

- [ ] **Step 3: 写选图网格**

```dart
// app/lib/features/square/widgets/compose_photo_grid.dart
import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_motion.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';

/// 发动态选图(附录 E):3 列 R12 正方格,与广场九宫格同视觉;
/// 加号格 `divider` 描边,已选图右上角半透明深底删除钮。
class ComposePhotoGrid extends StatelessWidget {
  const ComposePhotoGrid({
    super.key,
    required this.images,
    required this.onRemove,
    required this.onAdd,
    this.maxCount = 9,
  });

  final List<Uint8List> images;
  final ValueChanged<int> onRemove;
  final VoidCallback onAdd;
  final int maxCount;

  @override
  Widget build(BuildContext context) => GridView.count(
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        crossAxisCount: 3,
        mainAxisSpacing: AppSpacing.sm,
        crossAxisSpacing: AppSpacing.sm,
        children: [
          for (var i = 0; i < images.length; i++)
            _PickedTile(
              key: Key('compose.picked.$i'),
              bytes: images[i],
              onRemove: () => onRemove(i),
            ),
          if (images.length < maxCount) _AddTile(onTap: onAdd),
        ],
      );
}

class _PickedTile extends StatelessWidget {
  const _PickedTile({super.key, required this.bytes, required this.onRemove});

  final Uint8List bytes;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) => Stack(
        fit: StackFit.expand,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(AppRadius.image),
            child: Image.memory(
              bytes,
              fit: BoxFit.cover,
              errorBuilder: (_, _, _) => const ColoredBox(
                color: AppColors.divider,
                child: Center(
                  child: Icon(Icons.image_rounded, color: AppColors.text3),
                ),
              ),
            ),
          ),
          Positioned(
            right: 0,
            top: 0,
            child: IconButton(
              iconSize: 18,
              onPressed: onRemove,
              icon: const _RemoveBadge(),
            ),
          ),
        ],
      );
}

/// 半透明深底圆 + 白叉(与资料照片网格同款)。
class _RemoveBadge extends StatelessWidget {
  const _RemoveBadge();

  @override
  Widget build(BuildContext context) => Container(
        width: 22,
        height: 22,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: AppColors.text1.withValues(alpha: .55),
        ),
        child: const Icon(Icons.close_rounded, size: 14, color: Colors.white),
      );
}

class _AddTile extends StatefulWidget {
  const _AddTile({required this.onTap});

  final VoidCallback onTap;

  @override
  State<_AddTile> createState() => _AddTileState();
}

class _AddTileState extends State<_AddTile> {
  var _pressed = false;

  @override
  Widget build(BuildContext context) => GestureDetector(
        key: const Key('compose.add'),
        onTapDown: (_) => setState(() => _pressed = true),
        onTapUp: (_) => setState(() => _pressed = false),
        onTapCancel: () => setState(() => _pressed = false),
        onTap: widget.onTap,
        child: AnimatedScale(
          scale: _pressed ? 0.96 : 1,
          duration: AppMotion.fast,
          child: DecoratedBox(
            decoration: BoxDecoration(
              color: AppColors.bgCard,
              borderRadius: BorderRadius.circular(AppRadius.image),
              border: Border.all(color: AppColors.divider),
            ),
            child: const Center(
              child: Icon(Icons.add_photo_alternate_rounded,
                  size: 24, color: AppColors.text3),
            ),
          ),
        ),
      );
}
```

- [ ] **Step 4: 重写页面**

```dart
// app/lib/features/square/post_compose_page.dart 整文件替换
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/image_pick.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_text_action.dart';
import '../../core/widgets/app_text_field.dart';
import '../../core/widgets/app_toast.dart';
import 'feed_repository.dart';
import 'square_controller.dart';
import 'widgets/compose_photo_grid.dart';

const _maxBytes = 5 * 1024 * 1024;
const _maxCount = 9;

typedef _Picked = ({Uint8List bytes, String name});

/// 发布动态(附录 E):顶栏「发布」文字按钮 + 无边框正文 + 三列选图。
class PostComposePage extends ConsumerStatefulWidget {
  const PostComposePage({super.key, this.pickImages = pickImagesFromGallery});

  /// 测试注入用;默认打开系统相册多选。
  final PickImages pickImages;

  @override
  ConsumerState<PostComposePage> createState() => _PostComposePageState();
}

class _PostComposePageState extends ConsumerState<PostComposePage> {
  final _text = TextEditingController();
  final _images = <_Picked>[];
  bool _submitting = false;

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Future<void> _pick() async {
    final files = await widget.pickImages();
    if (!mounted || files.isEmpty) return;
    for (final file in files) {
      if (_images.length >= _maxCount) {
        AppToast.show(context, '最多 9 张图片');
        break;
      }
      final bytes = await file.readAsBytes();
      if (bytes.length > _maxBytes) {
        AppToast.show(context, '单张图片不能超过 5MB');
        continue;
      }
      _images.add((bytes: bytes, name: file.name));
    }
    setState(() {});
  }

  Future<void> _submit() async {
    setState(() => _submitting = true);
    try {
      await ref.read(feedRepositoryProvider).createPost(
          text: _text.text.trim(), images: List.of(_images));
      ref.invalidate(squareProvider);
      if (mounted) Navigator.of(context).pop(true);
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final canSubmit =
        !_submitting && (_text.text.trim().isNotEmpty || _images.isNotEmpty);
    return Scaffold(
      backgroundColor: AppColors.bgPage,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            AppSubPageBar(
              title: '发布动态',
              trailing: AppTextAction(
                key: const Key('compose.submit'),
                label: '发布',
                onPressed: canSubmit ? _submit : null,
              ),
            ),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(AppSpacing.pageH,
                    AppSpacing.md, AppSpacing.pageH, AppSpacing.xxl),
                children: [
                  AppTextField(
                    key: const Key('compose.text'),
                    controller: _text,
                    hint: '分享新鲜事…',
                    borderless: true,
                    maxLines: 6,
                    minLines: 6,
                    maxLength: 500,
                    counterKey: const Key('compose.counter'),
                    onChanged: (_) => setState(() {}),
                  ),
                  const SizedBox(height: AppSpacing.lg),
                  ComposePhotoGrid(
                    images: [for (final item in _images) item.bytes],
                    onAdd: _pick,
                    onRemove: (index) =>
                        setState(() => _images.removeAt(index)),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
```

- [ ] **Step 5: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/features/square/post_compose_page_test.dart test/features/square/square_page_test.dart
```

Expected: 全 PASS。

- [ ] **Step 6: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add -A
git commit -m "feat(ui): 发动态页 — 顶栏发布文字按钮/无边框正文/三列选图网格" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 17: 协议页 + 封禁页

**Files:**
- Modify: `app/lib/features/legal/legal_page.dart`(整文件重写)
- Modify: `app/lib/features/shell/banned_page.dart`(整文件重写)
- Test: `app/test/features/legal/legal_page_test.dart`(新建)
- Modify: `app/test/features/shell/banned_page_test.dart`(加视觉断言)

**Interfaces:**
- Consumes: `AppSubPageBar` / `AppSectionCard` / `AppButton` / `AppText` / `AppColors`
- Produces: `LegalPage.agreement` / `LegalPage.privacy` 构造不变;新增 key `legal.back`;`banned.logout` 保留。

- [ ] **Step 1: 写失败测试**

```dart
// app/test/features/legal/legal_page_test.dart 新建
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/legal/legal_page.dart';
import 'package:chatapp_app/features/legal/legal_texts.dart';

void main() {
  testWidgets('协议页:顶栏标题 + 返回键 + 正文全文', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: LegalPage.agreement()));

    expect(find.text('用户协议'), findsOneWidget);
    expect(find.byKey(const Key('legal.back')), findsOneWidget);
    expect(find.textContaining('欢迎使用'), findsOneWidget);
    expect(userAgreementText.isNotEmpty, isTrue);
  });

  testWidgets('隐私政策页标题正确', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: LegalPage.privacy()));
    expect(find.text('隐私政策'), findsOneWidget);
    expect(find.byKey(const Key('legal.back')), findsOneWidget);
  });
}
```

`app/test/features/shell/banned_page_test.dart`,`:22` 之后补:

```dart
    expect(find.byIcon(Icons.block_rounded), findsOneWidget);
```

- [ ] **Step 2: 跑测试确认失败**

```bash
../flutter/bin/flutter.bat test test/features/legal/legal_page_test.dart test/features/shell/banned_page_test.dart
```

Expected: FAIL(`legal.back` 不存在;`block_rounded` 未使用,当前是 `Icons.block`)。

- [ ] **Step 3: 重写协议页**

```dart
// app/lib/features/legal/legal_page.dart 整文件替换
import 'package:flutter/material.dart';

import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_section_card.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import 'legal_texts.dart';

/// 协议/隐私全文页(附录 E):二级页顶栏 + 白卡长文。
/// 正文来自 `legal_texts.dart`,**一字不动**。
class LegalPage extends StatelessWidget {
  const LegalPage.agreement({super.key}) : _title = '用户协议', _text = userAgreementText;

  const LegalPage.privacy({super.key}) : _title = '隐私政策', _text = privacyPolicyText;

  final String _title;
  final String _text;

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: AppColors.bgPage,
        body: SafeArea(
          bottom: false,
          child: Column(
            children: [
              AppSubPageBar(title: _title, backKey: const Key('legal.back')),
              Expanded(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(AppSpacing.pageH,
                      AppSpacing.md, AppSpacing.pageH, AppSpacing.xxl),
                  child: AppSectionCard(
                    children: [
                      Text(
                        _text,
                        style: AppText.body.copyWith(
                          color: AppColors.text1,
                          height: 1.6,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      );
}
```

- [ ] **Step 4: 重写封禁页**

```dart
// app/lib/features/shell/banned_page.dart 整文件替换
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_button.dart';
import '../auth/session.dart';
import '../profile/models.dart';

/// 重封禁用户看到的整屏提示(替代主框架):原因 + 退出登录。
/// 大号元素用 `danger@12%` 圆底 + `block_rounded`(§7 禁止灰色图标占位)。
class BannedPage extends ConsumerWidget {
  const BannedPage({super.key, required this.profile});

  final Profile profile;

  @override
  Widget build(BuildContext context, WidgetRef ref) => Scaffold(
        backgroundColor: AppColors.bgPage,
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.xxl),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 96,
                  height: 96,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: AppColors.danger.withValues(alpha: .12),
                  ),
                  child: const Icon(Icons.block_rounded,
                      size: 40, color: AppColors.danger),
                ),
                const SizedBox(height: AppSpacing.lg),
                Text('账号已被封禁',
                    style: AppText.title.copyWith(color: AppColors.text1)),
                if (profile.banReason.isNotEmpty) ...[
                  const SizedBox(height: AppSpacing.sm),
                  Text('原因:${profile.banReason}',
                      style: AppText.caption.copyWith(color: AppColors.text2)),
                ],
                const SizedBox(height: AppSpacing.sm),
                Text('封禁期间所有功能暂停使用',
                    style: AppText.caption.copyWith(color: AppColors.text2)),
                const SizedBox(height: AppSpacing.sm),
                Text('如有疑问请联系客服',
                    style: AppText.micro.copyWith(color: AppColors.text3)),
                const SizedBox(height: AppSpacing.xxl),
                AppButton(
                  key: const Key('banned.logout'),
                  label: '退出登录',
                  variant: AppButtonVariant.dangerFilled,
                  onPressed: () => ref.read(sessionProvider.notifier).logout(),
                ),
              ],
            ),
          ),
        ),
      );
}
```

- [ ] **Step 5: 跑测试确认通过**

```bash
../flutter/bin/flutter.bat test test/features/legal/ test/features/shell/
```

Expected: 全 PASS。

- [ ] **Step 6: 全量门槛 + 提交**

```bash
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
git add -A
git commit -m "feat(ui): 协议页(白卡长文)+ 封禁页(danger 圆底大号元素)" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 18: 文档同步 + 打包上模拟器

**Files:**
- Modify: `docs/superpowers/specs/2026-09-15-ui-design-language-design.md`(升 v1.5 + 附录 E)
- Modify: `docs/pitfalls/frontend.md`(新增二级页/表单控件分节)
- Modify: `CLAUDE.md`(里程碑表 + 下一步)

**Interfaces:**
- Consumes: 前 17 个任务的全部产物
- Produces: 文档与代码一致;release APK 覆盖安装到模拟器,交用户手测

- [ ] **Step 1: 规则文档升 v1.5**

在 `2026-09-15-ui-design-language-design.md` 的版本行改 `v1.5`,变更记录追加一条;正文 §8 实施顺序那句「⑥ 二级页(登录/引导/设置/编辑等)」标注**已落地(见附录 E)**;§6.2 无需改动(本批无新转场);文件末尾追加附录 E:

```markdown
## 附录 E:二级页/表单控件落地补充(2026-10-12,批次⑥)

### E.1 表单控件规范(11 个 core 组件)

| 组件 | 规格 |
|---|---|
| `AppSubPageBar` | §5.2 二级页顶栏:高 52、返回 22 `text1`、标题 17/w600 居中;`trailing` 为右侧动作槽 |
| `AppBrandMark` | 品牌 mark:72 圆角方 `gradientHeart` + 白心形 32;**静态无动画** |
| `AppTextAction` | §7 文字按钮紧凑形态:`brand` 15/w600,无 52 高、无大内边距;禁用 `text3`;用于输入框内嵌动作与顶栏动作 |
| `AppTextField` | §7 输入框:白底 R16、描边 1px `divider`、聚焦 1.5px `brand` + 光晕 `brand@12%`;单行盒高 52;label 在盒上方;`maxLength` 计数自绘;`borderless` 变体给正文 |
| `AppOptionGroup<T>` | 单选分段:整体高 52(4 内边距 + 44 段);选中 `gradientHeart` + 白字 15/w600;未选透明 + `text2` |
| `AppChipGroup<T>` | 多选标签:胶囊 R-full;选中 `brand@12%` 底 + `brand` 描边 + `brand` 15/w600 |
| `AppPickerField` | 选择框:外观同输入框,盒高 52,右侧 `expand_more_rounded` |
| `AppRangeField` | 区间:标题 `subtitle` + 双滑块;轨道高 4,选中段 `gradientHeart`(自绘 `RangeSliderTrackShape`),滑块白底圆 24 + 卡片阴影 |
| `AppSectionCard` | 表单分组卡:白卡 R20 + 阴影 + 内边距 16;分组标题 `subtitle`;子项按 gap 竖排 |
| `AppRowGroup` | 行分组卡:白卡 R20 + 阴影 + 无内边距;行间 1px `divider`;可选分组小标题 `caption` `text3` |
| `AppListRow` | §5.2 列表行:高 64;图标 20 `text2` 或头像;`trailing` 或 chevron;`danger`/`centerTitle` 变体;按压 scale .98 |
| `AppDialog` | 统一对话框:白底 R24、标题 17/w600、正文 `caption` `text2`;`showConfirmDialog` 是两键确认的便捷入口 |
| `AppProgressBar` | 分段进度:高 4 胶囊,第 i 段填充 iff `i <= current`;已过段 `gradientHeart` |
| `AppFormSkeleton` | 表单骨架:每组「标签条 64×12 + 输入框块 通栏×52」 |

新增按钮变体:`AppButtonVariant.dangerFilled`(§7「危险按钮 danger 描边或实底(二次确认后)」的实底形态;danger 实底 + 白字 w700,无阴影)。

### E.2 二级页统一形态

顶栏一律 `AppSubPageBar`;内容一律 `bgPage` 底 + 分组卡流(表单用 `AppSectionCard`,行式用 `AppRowGroup`),水平外边距 `AppSpacing.pageH`,卡间 `AppSpacing.cardGap`;主操作(保存/发布)放顶栏右侧 `AppTextAction`。

批次⑤ 在我的动态页与详情页各留的 `_SubPageBar` / `_DetailBar` 两份私有副本,本批统一为 `AppSubPageBar`。

### E.3 常驻动画禁令(登录/启动路径)

登录页与启动页的品牌区**必须是静态的**:这两个页面在 `login_page_test` / `startup_flow_test` / `account_switch_test` / `kicked_offline_test` / `agreement_gate_test` 里被 `pumpAndSettle` 驱动,常驻无限动画会让这些用例永不收敛(批次⑤实测坑)。骨架屏只在 loading 态短暂出现,不受此限。

### E.4 提示与弹窗口径

- 页面内操作反馈(校验失败/保存成功/接口 message)一律 `AppToast`;
- 二次确认一律 `showConfirmDialog`;协议弹窗用 `AppDialog` 自定义 `content`;
- 举报底部弹层(`ReportSheet`)不在此列(bottom sheet,§7 已合规)。
```

- [ ] **Step 2: 踩坑册新增分节**

`docs/pitfalls/frontend.md` 在「## 广场(`features/square/`)」之后插入:

```markdown
## 二级页与表单控件(`features/auth,onboarding,profile,settings,legal,shell`)

- **品牌区禁常驻动画**:登录页/启动页有 `pumpAndSettle` 用例(`login_page_test`/`startup_flow_test`/`account_switch_test`/`kicked_offline_test`/`agreement_gate_test`),`AppBrandMark` 做成纯静态;`CircularProgressIndicator` 也从启动页移除。
- **`AppTextField` 的 key 放包装件**:`tester.enterText(find.byKey(...))` 内部走 `find.descendant(..., matchRoot: true)`,能穿透到内部 `EditableText`;但**别在包装件和内部 `TextField` 上挂同一个 key**,否则 `find.byKey` 命中两个。
- **计数别用 `InputDecoration.counterText`**:会被 Material 默认样式接管,`AppTextField` 自己画 `x/y`。
- **`AppToast` 收尾**:触发过 Toast 的用例必须 `await drainToast(tester)`;注意**登录页 `initState` 的「被顶下线原因」提示**也会触发(`kicked_offline_test`/`account_switch_test`),以及**保存成功后 pop 的页面**——Toast 挂在根 Overlay,pop 不会取消它的 2s Timer(`preference_page_test`)。
- **`AppSubPageBar` 取代私有副本**:我的动态页/详情页原各有一份 `_SubPageBar`/`_DetailBar`,已统一;新二级页直接用 core 组件。
- **分组卡两种内边距**:表单内容用 `AppSectionCard`(内边距 16),行式列表用 `AppRowGroup`(无内边距、行自带 16、行间 divider),不要混用。
```

- [ ] **Step 3: CLAUDE.md 里程碑与下一步**

里程碑表追加一行(放在批次⑤行之后):

```markdown
| 2026-10-12 | UI 整改批次⑥「二级页」交付(表单控件规范 14 组件 + 10 页:登录/启动/引导/设置/黑名单/编辑资料/想找的人/发动态/协议/封禁;`AlertDialog`→`AppDialog`、`SnackBar`→`AppToast` 全量统一;测试 N 绿) |
```

「下一步」段改为:

```markdown
**下一步(M4 续)**:App 端「心跳」UI 整改 ①–⑥ 已全部交付(设计规则 §8 实施顺序收官)。接下来启动**上线合规轨**,按 `2026-09-18-launch-execution.md` 推进(上线流程表含商业化/资质细节,已从开源仓库移出,仅本地保留)。
```

**注意**:`N` 以 Task 18 Step 4 实测的测试数为准,别写占位符。`<SERVER_IP>` 是测试服地址(私有运维手册里,本地保留、不入库),执行时按 `README.md`「部署」一节取值。

- [ ] **Step 4: 全量门槛 + 打包上模拟器**

```bash
cd app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
../flutter/bin/flutter.bat build apk --release --dart-define=API_BASE=http://<SERVER_IP>/api/v1
adb -s emulator-5554 install -r build/app/outputs/flutter-apk/app-release.apk
```

Expected: analyze 零告警;全量测试绿(记录实际数字,回填 Step 3 与执行记录);APK 覆盖安装成功。

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "docs: 规则文档 v1.5 附录 E + 踩坑册二级页分册 + CLAUDE.md 批次⑥同步" -m "Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 19: 待用户手测通过后收尾(另一步执行)

- [ ] **Step 1: 回填本文件执行记录**(测试数、任务提交表、手测结果)

- [ ] **Step 2: 合回 master**

```bash
git push -u origin ui/batch6
# 走 PR 流程:PR → CI analyze-and-test 通过 → squash 合并
git fetch origin && git reset --hard origin/master   # squash 后本地 master 对齐
git branch -d ui/batch6 && git push origin --delete ui/batch6
```

- [ ] **Step 3: 更新会话记忆**(`.remember/` 由 harness 的 remember 机制维护,不手改——CLAUDE.md 明示「勿改动、勿提交」)

---

## 手测清单(交用户,模拟器 release 包)

1. **登录页**:品牌区静态展示;手机号格式错提示;获取验证码 → 60 秒倒计时;老用户登录进主框架;断网重试提示。
2. **启动页**:冷启动品牌区;首启协议弹窗(点《用户协议》/《隐私政策》能打开全文);不同意 → 提示页;重新阅读;已同意 → 直进登录页。
3. **引导页**:三步向导;进度条随步骤前进;性别/生日选择;标签多选;照片上传;缺项提示。
4. **编辑资料**:分组卡三段;昵称/性别/生日/城市/简介;标签选中态;照片 3 列网格、待审核角标、删除确认;保存成功 Toast。
5. **想找的人**:不限/男/女 分段选中渐变;年龄区间拖动;城市留空;保存后返回。
6. **设置页**:三行 + 居中危险退出行;退出确认弹窗(取消/退出);协议与隐私跳转。
7. **黑名单页**:空态;有数据时圆头像 + 拉黑时间;解除确认;解除成功 Toast。
8. **发动态页**:正文无边框 + 字数计数;选图 3 列;删图;超 9 张/超 5MB 提示;发布成功返回并刷新广场。
9. **协议页**:长文滚动;返回键。
10. **封禁页**:重封禁账号整屏提示 + 退出登录。
11. **系统「减弱动态效果」**开启后各页正常;窄屏(360dp)表单不溢出;键盘弹出不遮输入框。
