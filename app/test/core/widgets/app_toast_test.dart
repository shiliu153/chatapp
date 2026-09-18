import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_toast.dart';

void main() {
  testWidgets('Toast 出现后 2s 自动消失', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: Builder(
          builder: (context) => TextButton(
            onPressed: () => AppToast.show(context, '已保存'),
            child: const Text('show'),
          ),
        ),
      ),
    ));
    await tester.tap(find.text('show'));
    await tester.pump(const Duration(milliseconds: 300)); // 入场
    expect(find.text('已保存'), findsOneWidget);
    await tester.pump(const Duration(seconds: 3)); // 超时自动移除
    expect(find.text('已保存'), findsNothing);
  });
}
