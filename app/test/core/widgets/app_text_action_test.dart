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
    expect(tester.widget<AppTextAction>(find.byKey(const Key('act'))).onPressed,
        isNull);
    expect(taps, 0);
  });
}
