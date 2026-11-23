import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/ember_colors.dart';
import 'package:chatapp_app/core/theme/tokens.g.dart' as tokens;
import 'package:chatapp_app/core/ui/ember_field.dart';

import 'ember_test_kit.dart';

/// 输入框内部的 `TextField`(加 key 是为了在测试里精确取到它,而不是第一个碰到的)。
final _input = find.byKey(const Key('ember.field.input'));

InputDecoration _decoration(WidgetTester tester) =>
    tester.widget<TextField>(_input).decoration!;

BorderSide _side(WidgetTester tester) =>
    (_decoration(tester).enabledBorder! as OutlineInputBorder).borderSide;

void main() {
  group('EmberField · default(§8.3 输入框表)', () {
    testWidgets('surface.card 底 + 1px border.divider + 占位 text.tertiary + 高 52', (tester) async {
      await pumpEmber(tester, EmberField(placeholder: '说点什么'));
      final decoration = _decoration(tester);
      expect(decoration.fillColor, EmberColors.light.surfaceCard);
      expect(_side(tester).color, EmberColors.light.borderDivider);
      expect(_side(tester).width, 1);
      expect(
        (decoration.hintStyle!.color),
        EmberColors.light.textTertiary,
      );
      expect(
        (decoration.border! as OutlineInputBorder).borderRadius,
        BorderRadius.circular(tokens.radiusMd),
      );
      expect(
        decoration.constraints!.minHeight,
        tokens.sizeControlHeight,
      );
    });
  });

  group('EmberField · focus(2px brand + 2px 外扩 @12%)', () {
    testWidgets('聚焦后描边转 brand.default 2px,并出现外扩光晕', (tester) async {
      await pumpEmber(tester, EmberField(placeholder: '搜索'));
      await tester.tap(_input);
      await tester.pump();

      expect(_side(tester).color, EmberColors.light.brandDefault);
      expect(_side(tester).width, 2);

      final halo = tester
          .widgetList<Container>(find.byType(Container))
          .where((c) => c.decoration is BoxDecoration)
          .map((c) => (c.decoration! as BoxDecoration).color)
          .whereType<Color>();
      expect(
        halo.any((c) =>
            c.a == EmberColors.light.brandDefault.withValues(alpha: 0.12).a &&
            c.r == EmberColors.light.brandDefault.withValues(alpha: 0.12).r),
        isTrue,
        reason: '聚焦时应有 brand@12% 的外扩光晕',
      );
    });
  });

  group('EmberField · error(2px danger + 必须有说明文字)', () {
    testWidgets('描边转 status.danger 2px,且说明文字以 13 号渲染', (tester) async {
      await pumpEmber(
        tester,
        EmberField(placeholder: '手机号', errorText: '手机号格式不对'),
      );
      expect(_side(tester).color, EmberColors.light.statusDanger);
      expect(_side(tester).width, 2);
      final text = tester.widget<Text>(find.text('手机号格式不对'));
      expect(text.style!.color, EmberColors.light.statusDanger);
      expect(text.style!.fontSize, tokens.fontSizeCaption);
    });
  });

  group('EmberField · disabled', () {
    testWidgets('surface.sunken 底 + text.tertiary 字 + 描边透明 + 读屏 isEnabled=false', (tester) async {
      final handle = tester.ensureSemantics();
      await pumpEmber(
        tester,
        const EmberField(placeholder: '昵称', enabled: false),
      );
      expect(_decoration(tester).fillColor, EmberColors.light.surfaceSunken);
      expect(_side(tester).color, Colors.transparent);
      expect(
        tester.widget<TextField>(_input).style!.color,
        EmberColors.light.textTertiary,
      );
      expectSemanticallyEnabled(tester, _input, enabled: false);
      handle.dispose();
    });
  });

  test('§8.1 的输入框没有 loading 态:组件不提供 loading 参数', () {
    // 这条是「不要自己发明状态」的显式记录:§8.1 状态矩阵里 Input / Textarea
    // 那一行没有 loading,所以 EmberField 也就没有。
    const field = EmberField(placeholder: 'x');
    expect(field.enabled, isTrue);
  });
}
