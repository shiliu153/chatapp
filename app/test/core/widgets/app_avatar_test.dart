import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_avatar.dart';

Widget wrap(Widget child) => MaterialApp(home: Scaffold(body: Center(child: child)));

void main() {
  testWidgets('渲染圆形头像占位', (tester) async {
    await tester.pumpWidget(wrap(const AppAvatar()));
    expect(find.byType(AppAvatar), findsOneWidget);
    expect(find.byIcon(Icons.person_rounded), findsOneWidget);
  });

  testWidgets('showOnlineDot 时出现呼吸在线点(有限 pump,不 settle)', (tester) async {
    await tester.pumpWidget(wrap(const AppAvatar(showOnlineDot: true)));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.byKey(const Key('avatar.onlineDot')), findsOneWidget);
  });

  testWidgets('默认不显示在线点', (tester) async {
    await tester.pumpWidget(wrap(const AppAvatar()));
    expect(find.byKey(const Key('avatar.onlineDot')), findsNothing);
  });
}
