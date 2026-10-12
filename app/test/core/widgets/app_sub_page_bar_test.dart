import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_sub_page_bar.dart';

Widget _wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

void main() {
  testWidgets('标题 + 返回键;点返回触发回调', (tester) async {
    var popped = 0;
    await tester.pumpWidget(_wrap(AppSubPageBar(
      title: '设置',
      backKey: const Key('bar.back'),
      onBack: () => popped++,
    )));

    expect(find.text('设置'), findsOneWidget);
    expect(find.byKey(const Key('bar.back')), findsOneWidget);
    expect(tester.getSize(find.byType(AppSubPageBar)).height, 52);

    await tester.tap(find.byKey(const Key('bar.back')));
    expect(popped, 1);
  });

  testWidgets('showBack=false 不渲染返回键', (tester) async {
    await tester.pumpWidget(_wrap(const AppSubPageBar(
      title: '设置',
      backKey: Key('bar.back'),
      showBack: false,
    )));
    expect(find.byKey(const Key('bar.back')), findsNothing);
  });

  testWidgets('trailing 槽渲染在右侧', (tester) async {
    await tester.pumpWidget(_wrap(const AppSubPageBar(
      title: '编辑资料',
      trailing: Text('保存', key: Key('bar.trailing')),
    )));
    expect(find.byKey(const Key('bar.trailing')), findsOneWidget);
    final titleX = tester.getCenter(find.text('编辑资料')).dx;
    final trailingX = tester.getCenter(find.byKey(const Key('bar.trailing'))).dx;
    expect(trailingX, greaterThan(titleX));
  });
}
