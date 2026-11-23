import 'dart:ui' show Tristate;

import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_theme.dart';

/// `test/core/ui/` 的公共夹具:真实主题 + 居中舞台。
///
/// 为什么必须挂真实主题:组件取色走 `context.ember`(ThemeExtension),
/// 裸 `MaterialApp()` 里没有注册扩展,debug 断言会直接炸;而且「浅/深两套取值」
/// 本身就是 §8.3 的一半判据,所以亮度要能显式指定。
Widget emberStage(
  Widget child, {
  Brightness brightness = Brightness.light,
  bool disableAnimations = false,
}) =>
    MaterialApp(
      theme: buildAppTheme(brightness: brightness),
      home: MediaQuery(
        // §8.4「减弱动态效果」:真机上由系统开关驱动,测试里直接注入这个标志。
        data: MediaQueryData(disableAnimations: disableAnimations),
        child: Scaffold(body: Center(child: child)),
      ),
    );

/// pump 一个组件(带真实主题)。
///
/// 组件里有循环动画(骨架呼吸、在线点呼吸),**不能**用 `pumpAndSettle`。
Future<void> pumpEmber(
  WidgetTester tester,
  Widget child, {
  Brightness brightness = Brightness.light,
  bool disableAnimations = false,
}) async {
  await tester.pumpWidget(
    emberStage(
      child,
      brightness: brightness,
      disableAnimations: disableAnimations,
    ),
  );
  await tester.pump();
}

/// 取某个组件的语义节点(必须先 `tester.ensureSemantics()`)。
///
/// 用 [SemanticsNode] 的具名 getter(`isEnabled` / `isButton` / `label`)而不是
/// 已弃用的 `hasFlag`,后者在新版本 Flutter 上会报 `deprecated_member_use`。
SemanticsNode semanticsOf(WidgetTester tester, Finder finder) =>
    tester.getSemantics(finder);

/// 断言语义上「可用」。
///
/// 走 `flagsCollection`(新 API):`hasFlag` 已弃用,而 `SemanticsNode` 上没有
/// 直接的 `isEnabled` getter,所以取三态值再与 [Tristate] 比。
void expectSemanticallyEnabled(WidgetTester tester, Finder finder, {bool enabled = true}) {
  final flag = tester.getSemantics(finder).getSemanticsData().flagsCollection.isEnabled;
  expect(flag, enabled ? Tristate.isTrue : Tristate.isFalse);
}

/// 断言语义上「是不是按钮」(卡片应是 false、按钮应是 true)。
void expectSemanticallyButton(WidgetTester tester, Finder finder, {required bool isButton}) {
  expect(
    tester.getSemantics(finder).getSemanticsData().flagsCollection.isButton,
    isButton,
  );
}

/// 连续推进若干帧并渲染。
///
/// 为什么不能一次 `pump(200ms)` 就断言:弹簧动画的第一帧只用来「对齐时钟」
/// (elapsed=0),所以要让 [AnimationController] 真正前进,必须多推几帧。
Future<void> pumpFrames(
  WidgetTester tester, {
  int frames = 8,
  Duration step = const Duration(milliseconds: 32),
}) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(step);
  }
}

/// 取 [EmberPressable] 当前的缩放比(spring 推的动画值)。
///
/// `/ .97` 这类断言不能用像素快照:spring 是连续值,只断言「明显小于 1」。
double pressableScale(WidgetTester tester, Finder within) {
  final transform = tester.widget<Transform>(
    find
        .descendant(of: within, matching: find.byType(Transform))
        .first,
  );
  // 注意:不能用 getMaxScaleOnAxis() —— `Transform.scale` 只缩放 x/y,z 仍为 1,
  // 那个方法取的是「各轴最大值」,于是永远返回 1。取 x 轴分量才是真实缩放比。
  return transform.transform.storage[0];
}
