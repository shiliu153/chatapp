import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/discovery/models.dart';
import 'package:chatapp_app/features/discovery/widgets/profile_card.dart';

import '../../support/sample_data.dart';

Widget _wrap(Candidate candidate) => MaterialApp(
      home: Scaffold(
        body: Center(
          child: SizedBox(width: 360, height: 560, child: ProfileCard(candidate: candidate)),
        ),
      ),
    );

void main() {
  testWidgets('展示昵称、年龄、城市、简介和标签', (tester) async {
    final candidate = Candidate.fromJson(candidateJson(
      nickname: '小红',
      age: 25,
      city: '上海',
      bio: '喜欢爬山',
      tags: [tagJson(1, '运动'), tagJson(2, '音乐')],
    ));

    await tester.pumpWidget(_wrap(candidate));
    await tester.pump();

    expect(find.text('小红,25'), findsOneWidget);
    expect(find.text('上海'), findsOneWidget);
    expect(find.text('喜欢爬山'), findsOneWidget);
    expect(find.text('运动'), findsOneWidget);
    expect(find.text('音乐'), findsOneWidget);
  });

  testWidgets('没有年龄时只显示昵称', (tester) async {
    final candidate = Candidate.fromJson(candidateJson(nickname: '小红', age: null));

    await tester.pumpWidget(_wrap(candidate));
    await tester.pump();

    expect(find.text('小红'), findsOneWidget);
  });

  testWidgets('多张照片:点右侧下一张、点左侧上一张,首尾循环', (tester) async {
    final candidate = Candidate.fromJson(
        candidateJson(photos: [photoJson(1), photoJson(2), photoJson(3)]));

    await tester.pumpWidget(_wrap(candidate));
    await tester.pump();

    expect(find.byKey(const ValueKey('card.photo.1')), findsOneWidget);
    expect(find.byKey(const Key('card.dots')), findsOneWidget);

    await tester.tap(find.byKey(const Key('card.nextPhoto')));
    await tester.pump();
    expect(find.byKey(const ValueKey('card.photo.2')), findsOneWidget);

    await tester.tap(find.byKey(const Key('card.nextPhoto')));
    await tester.pump();
    expect(find.byKey(const ValueKey('card.photo.3')), findsOneWidget);

    await tester.tap(find.byKey(const Key('card.nextPhoto')));
    await tester.pump();
    expect(find.byKey(const ValueKey('card.photo.1')), findsOneWidget); // 循环回第一张

    await tester.tap(find.byKey(const Key('card.prevPhoto')));
    await tester.pump();
    expect(find.byKey(const ValueKey('card.photo.3')), findsOneWidget); // 上一张也是循环
  });

  testWidgets('单张照片:没有切换区也没有圆点', (tester) async {
    final candidate = Candidate.fromJson(candidateJson(photos: [photoJson(1)]));

    await tester.pumpWidget(_wrap(candidate));
    await tester.pump();

    expect(find.byKey(const Key('card.nextPhoto')), findsNothing);
    expect(find.byKey(const Key('card.prevPhoto')), findsNothing);
    expect(find.byKey(const Key('card.dots')), findsNothing);
  });

  testWidgets('一张照片都没有:显示占位图标,不崩', (tester) async {
    final candidate = Candidate.fromJson(candidateJson(photos: []));

    await tester.pumpWidget(_wrap(candidate));
    await tester.pump();

    expect(find.byIcon(Icons.person_outline), findsOneWidget);
  });
}
