import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/avatar_hero.dart';

Widget wrap(Widget child, {bool disableAnimations = false}) => MaterialApp(
      home: MediaQuery(
        data: MediaQueryData(disableAnimations: disableAnimations),
        child: Scaffold(body: Center(child: child)),
      ),
    );

void main() {
  testWidgets('tag 非空 → 包一层 Hero', (tester) async {
    await tester.pumpWidget(wrap(const AvatarHero(
      tag: 'avatar-post-1',
      imageUrl: null,
      child: SizedBox(width: 40, height: 40),
    )));

    final hero = tester.widget<Hero>(find.byType(Hero));
    expect(hero.tag, 'avatar-post-1');
  });

  testWidgets('tag 为 null → 不包 Hero(无来源/深链)', (tester) async {
    await tester.pumpWidget(wrap(const AvatarHero(
      tag: null,
      imageUrl: null,
      child: SizedBox(width: 40, height: 40),
    )));

    expect(find.byType(Hero), findsNothing);
    expect(find.byType(SizedBox), findsWidgets); // child 仍在
  });

  testWidgets('减弱动态效果 → 不包 Hero', (tester) async {
    await tester.pumpWidget(wrap(
      const AvatarHero(
        tag: 'avatar-post-1',
        imageUrl: null,
        child: SizedBox(width: 40, height: 40),
      ),
      disableAnimations: true,
    ));

    expect(find.byType(Hero), findsNothing);
  });

  testWidgets('child 正常渲染', (tester) async {
    await tester.pumpWidget(wrap(const AvatarHero(
      tag: 'avatar-post-1',
      imageUrl: null,
      child: Text('头像占位'),
    )));

    expect(find.text('头像占位'), findsOneWidget);
  });
}
