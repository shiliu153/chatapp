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
