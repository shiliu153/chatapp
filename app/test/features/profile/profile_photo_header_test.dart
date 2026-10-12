import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/avatar_hero.dart';
import 'package:chatapp_app/features/profile/widgets/profile_photo_header.dart';

import '../../support/harness.dart';

Widget wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

void main() {
  testWidgets('有照片:渲染网络图 + 昵称·年龄 + 城市', (tester) async {
    await tester.pumpWidget(wrap(const ProfilePhotoHeader(
      photoUrl: 'http://test/media/photos/1.png',
      nickname: '小红',
      age: 25,
      city: '上海',
    )));
    await pumpFrames(tester, frames: 3);

    expect(find.byType(Image), findsWidgets);
    expect(find.text('小红,25'), findsOneWidget);
    expect(find.text('上海'), findsOneWidget);
  });

  testWidgets('无年龄:昵称不带逗号', (tester) async {
    await tester.pumpWidget(wrap(const ProfilePhotoHeader(
      photoUrl: null,
      nickname: '小红',
      age: null,
    )));
    await pumpFrames(tester, frames: 3);

    expect(find.text('小红'), findsOneWidget);
  });

  testWidgets('无照片:走 person 占位(非空态)', (tester) async {
    await tester.pumpWidget(wrap(const ProfilePhotoHeader(
      photoUrl: null,
      nickname: '小红',
    )));
    await pumpFrames(tester, frames: 3);

    expect(find.byIcon(Icons.person_rounded), findsOneWidget);
  });

  testWidgets('在线:渲染呼吸点 + 「在线」', (tester) async {
    await tester.pumpWidget(wrap(const ProfilePhotoHeader(
      photoUrl: null,
      nickname: '小红',
      online: true,
    )));
    await pumpFrames(tester, frames: 3);

    expect(find.text('在线'), findsOneWidget);
    expect(find.byKey(const Key('user.onlineDot')), findsOneWidget);
  });

  testWidgets('离线:不渲染在线行', (tester) async {
    await tester.pumpWidget(wrap(const ProfilePhotoHeader(
      photoUrl: null,
      nickname: '小红',
      online: false,
    )));
    await pumpFrames(tester, frames: 3);

    expect(find.text('在线'), findsNothing);
  });

  testWidgets('heroTag 非空 → 包 AvatarHero', (tester) async {
    await tester.pumpWidget(wrap(const ProfilePhotoHeader(
      photoUrl: 'http://test/media/photos/1.png',
      nickname: '小红',
      heroTag: 'avatar-post-1',
    )));
    await pumpFrames(tester, frames: 3);

    final hero = tester.widget<AvatarHero>(find.byType(AvatarHero));
    expect(hero.tag, 'avatar-post-1');
  });
}
