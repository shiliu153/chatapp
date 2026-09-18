import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_card.dart';

void main() {
  testWidgets('渲染子内容;onTap 触发', (tester) async {
    var taps = 0;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: AppCard(onTap: () => taps++, child: const Text('内容'))),
    ));
    expect(find.text('内容'), findsOneWidget);
    await tester.tap(find.text('内容'));
    expect(taps, 1);
  });

  testWidgets('无 onTap 也可渲染', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: AppCard(child: Text('纯展示'))),
    ));
    expect(find.text('纯展示'), findsOneWidget);
  });
}
