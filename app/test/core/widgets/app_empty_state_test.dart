import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_empty_state.dart';
import 'package:chatapp_app/core/widgets/app_button.dart';

void main() {
  testWidgets('四要素渲染,主按钮可点;禁灰色图标占位(§7)', (tester) async {
    var taps = 0;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: Center(
          child: AppEmptyState(
            emoji: '💫',
            title: '还没有内容',
            description: '去逛逛吧',
            action: AppButton(label: '去逛逛', onPressed: () => taps++),
          ),
        ),
      ),
    ));
    expect(find.text('💫'), findsOneWidget);
    expect(find.text('还没有内容'), findsOneWidget);
    expect(find.text('去逛逛吧'), findsOneWidget);
    await tester.tap(find.text('去逛逛'));
    expect(taps, 1);
  });

  testWidgets('无说明无按钮也可渲染', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: Center(child: AppEmptyState(emoji: '✨', title: '空空如也'))),
    ));
    expect(find.text('✨'), findsOneWidget);
    expect(find.text('空空如也'), findsOneWidget);
  });
}
