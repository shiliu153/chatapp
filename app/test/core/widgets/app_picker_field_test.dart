import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_colors.dart';
import 'package:chatapp_app/core/widgets/app_picker_field.dart';

void main() {
  testWidgets('未选显示占位 text3;点击回调', (tester) async {
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

    // 注意:AppPickerField 的外层 Column 在宽松高度约束下会撑满整屏(Scaffold body),
    // 所以按 key 取中心会落到盒子外;点文字才是盒子内的精确位置。
    await tester.tap(find.text('请选择'));
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

    expect(tester.widget<Text>(find.text('2000-01-01')).style!.color,
        AppColors.text1);
    expect(
      tester.getSize(find.descendant(
        of: find.byKey(const Key('p')),
        matching: find.byType(Container),
      )).height,
      52,
    );
  });
}
