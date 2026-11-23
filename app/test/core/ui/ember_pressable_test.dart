import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/ui/ember_pressable.dart';

import 'ember_test_kit.dart';

Widget _box({VoidCallback? onTap, bool enabled = true, bool autofocus = false}) =>
    EmberPressable(
      onTap: onTap,
      enabled: enabled,
      autofocus: autofocus,
      pressedScale: 0.97,
      borderRadius: BorderRadius.circular(12),
      semanticLabel: '按钮',
      builder: (context, state) => Container(
        width: 120,
        height: 52,
        color: state.pressed ? Colors.grey : Colors.transparent,
        alignment: Alignment.center,
        child: Text(state.pressed ? '按下' : '抬起'),
      ),
    );

void main() {
  group('EmberPressable · default', () {
    testWidgets('静止时缩放为 1,内容可见', (tester) async {
      await pumpEmber(tester, _box(onTap: () {}));
      expect(pressableScale(tester, find.byType(EmberPressable)), closeTo(1, 0.001));
      expect(find.text('抬起'), findsOneWidget);
    });
  });

  group('EmberPressable · pressed(spring.fast)', () {
    testWidgets('按下用弹簧缩小,抬起回升;builder 收到 pressed=true', (tester) async {
      await pumpEmber(tester, _box(onTap: () {}));
      final finder = find.byType(EmberPressable);
      final gesture = await tester.startGesture(tester.getCenter(finder));
      // onTapDown 要等手势竞技场判定(TapGestureRecognizer 的 kPressTimeout=100ms),
      // 之后弹簧还要若干帧才走到目标值,所以统一用 pumpFrames 推进。
      await pumpFrames(tester, frames: 8, step: const Duration(milliseconds: 32));

      expect(find.text('按下'), findsOneWidget);
      expect(pressableScale(tester, finder), lessThan(1));

      await gesture.up();
      await pumpFrames(tester, frames: 12, step: const Duration(milliseconds: 32));
      expect(find.text('抬起'), findsOneWidget);
      expect(pressableScale(tester, finder), closeTo(1, 0.05));
    });

    testWidgets('减弱动态效果时不缩放,直接取终态(§8.4)', (tester) async {
      await pumpEmber(tester, _box(onTap: () {}), disableAnimations: true);
      final finder = find.byType(EmberPressable);
      final gesture = await tester.startGesture(tester.getCenter(finder));
      await tester.pump();
      expect(
        pressableScale(tester, finder),
        closeTo(0.97, 1e-9),
        reason: 'reduced-motion 下取消缩放 → 直接是终态值',
      );
      await gesture.up();
      await tester.pump();
    });
  });

  group('EmberPressable · disabled', () {
    testWidgets('onTap 为 null 时点击无效、无按压反馈、语义 isEnabled=false', (tester) async {
      final handle = tester.ensureSemantics();
      var taps = 0;
      await pumpEmber(tester, _box(onTap: null));
      await tester.tap(find.byType(EmberPressable));
      await tester.pump();
      expect(taps, 0);
      expect(find.text('抬起'), findsOneWidget);

      final data = semanticsOf(tester, find.byType(EmberPressable));
      expectSemanticallyEnabled(tester, find.byType(EmberPressable), enabled: false);
      expect(data.label, contains('按钮'));
      handle.dispose();
    });
  });

  group('EmberPressable · focus(§8.4 禁止去掉焦点环)', () {
    testWidgets('获得键盘焦点后出现 2px 焦点环,并支持 Enter 触发', (tester) async {
      var taps = 0;
      await pumpEmber(tester, _box(onTap: () => taps++, autofocus: true));
      await tester.pump();
      expect(find.byType(EmberFocusRing), findsOneWidget);

      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.pump();
      expect(taps, 1);
    });

    testWidgets('disabled 的控件不进焦点链', (tester) async {
      await pumpEmber(tester, _box(onTap: null, autofocus: true));
      await tester.pump();
      expect(find.byType(EmberFocusRing), findsNothing);
    });
  });
}
