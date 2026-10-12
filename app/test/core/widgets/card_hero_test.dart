import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/card_hero.dart';

Widget _wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

void main() {
  testWidgets('tag 为 null 时直接返回 child,不包 Hero', (tester) async {
    await tester.pumpWidget(_wrap(const CardHero(
      tag: null,
      child: SizedBox(width: 100, height: 50, child: Text('卡')),
    )));
    expect(find.byType(Hero), findsNothing);
    expect(find.text('卡'), findsOneWidget);
  });

  testWidgets('disableAnimations 时直接返回 child,不包 Hero', (tester) async {
    await tester.pumpWidget(_wrap(MediaQuery(
      data: const MediaQueryData(disableAnimations: true),
      child: const CardHero(
        tag: 'card-post-1',
        child: SizedBox(width: 100, height: 50, child: Text('卡')),
      ),
    )));
    expect(find.byType(Hero), findsNothing);
  });

  testWidgets('有 tag 时包 Hero,tag 一致', (tester) async {
    await tester.pumpWidget(_wrap(const CardHero(
      tag: 'card-post-1',
      child: SizedBox(width: 100, height: 50, child: Text('卡')),
    )));
    final hero = tester.widget<Hero>(find.byType(Hero));
    expect(hero.tag, 'card-post-1');
  });
}
