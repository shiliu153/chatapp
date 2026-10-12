import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_colors.dart';
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

  testWidgets('宽松约束下收缩为内容宽度(不撑满整行)', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: Center(child: AppButton(label: '刷新', onPressed: () {}))),
    ));
    expect(tester.getSize(find.byType(AppButton)).width, lessThan(200));
  });

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
}
