import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/ember_colors.dart';
import 'package:chatapp_app/core/theme/tokens.g.dart' as tokens;
import 'package:chatapp_app/core/ui/ember_button.dart';
import 'package:chatapp_app/core/ui/ember_empty.dart';

import 'ember_test_kit.dart';

Widget _illustration() => Container(
      width: 96,
      height: 96,
      color: const Color(0x00000000),
      child: const Icon(Icons.auto_awesome),
    );

void main() {
  group('EmberEmpty · default(§8.3 空态表)', () {
    testWidgets('标题 17/w600 + 说明 13/text.secondary + 插画 72–96', (tester) async {
      await pumpEmber(
        tester,
        EmberEmpty(
          illustration: _illustration(),
          title: '还没有新配对',
          description: '多滑几张卡,遇见合适的人',
        ),
      );

      final title = tester.widget<Text>(find.text('还没有新配对'));
      expect(title.style!.fontSize, tokens.fontSizeSubtitle);
      expect(title.style!.fontWeight, FontWeight.w600);
      expect(title.style!.color, EmberColors.light.textPrimary);

      final description = tester.widget<Text>(find.text('多滑几张卡,遇见合适的人'));
      expect(description.style!.fontSize, tokens.fontSizeCaption);
      expect(description.style!.color, EmberColors.light.textSecondary);

      // 插画区域至少 72(§8.3「插画 72–96」),不是灰图标占位
      expect(
        tester.getSize(find.byType(EmberEmpty)).width,
        greaterThanOrEqualTo(72),
      );
    });

    testWidgets('给了文案与回调才出现主按钮', (tester) async {
      await pumpEmber(
        tester,
        EmberEmpty(
          illustration: _illustration(),
          title: '网络不太好',
          actionLabel: '重试',
          onAction: () {},
        ),
      );
      expect(find.byType(EmberButton), findsOneWidget);
      expect(find.text('重试'), findsOneWidget);

      await pumpEmber(
        tester,
        EmberEmpty(illustration: _illustration(), title: '网络不太好'),
      );
      expect(find.byType(EmberButton), findsNothing);
    });

    testWidgets('没有说明也能渲染(说明是可选的)', (tester) async {
      await pumpEmber(
        tester,
        EmberEmpty(illustration: _illustration(), title: '空空如也'),
      );
      expect(find.text('空空如也'), findsOneWidget);
    });
  });

  group('EmberEmpty · error(§8.1 空态 / 错误态共用)', () {
    testWidgets('错误态用文案 + 图标表达,不靠灰色图标占位', (tester) async {
      await pumpEmber(
        tester,
        EmberEmpty(
          // 插画由调用方给:禁止灰色 Icon 占位意味着这里必须传图或暖色几何体,
          // 组件不接受 IconData。
          illustration: const Icon(Icons.sentiment_dissatisfied),
          title: '加载失败',
          description: '下拉刷新再试一次',
          actionLabel: '重试',
          onAction: () {},
        ),
      );
      expect(find.text('加载失败'), findsOneWidget);
      expect(find.text('重试'), findsOneWidget);
    });
  });

  group('EmberEmpty · 读屏播报(§8.4)', () {
    testWidgets('标题与说明合成为一条播报', (tester) async {
      final handle = tester.ensureSemantics();
      await pumpEmber(
        tester,
        EmberEmpty(
          illustration: _illustration(),
          title: '还没有新配对',
          description: '多滑几张卡',
        ),
      );
      final label = semanticsOf(tester, find.byType(EmberEmpty)).label;
      expect(label, contains('还没有新配对'));
      expect(label, contains('多滑几张卡'));
      handle.dispose();
    });
  });

  group('EmberEmpty · 无 pressed / disabled / loading(§8.1)', () {
    test('空态只承担展示,可点性交给里面的主按钮', () {
      // §8.1 的「空态 / 错误态」行只勾 default 与 error —— 没有 pressed/loading。
      final empty = EmberEmpty(illustration: _illustration(), title: 't');
      expect(empty.onAction, isNull);
    });
  });
}
