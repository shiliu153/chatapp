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
