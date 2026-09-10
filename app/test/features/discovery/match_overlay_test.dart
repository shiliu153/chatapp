import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/discovery/models.dart';
import 'package:chatapp_app/features/discovery/widgets/match_overlay.dart';

import '../../support/sample_data.dart';

void main() {
  testWidgets('展示文案与头像位;点继续滑卡触发关闭', (tester) async {
    final candidate = Candidate.fromJson(candidateJson(nickname: '小红'));
    var closed = false;

    await tester.pumpWidget(MaterialApp(
      home: MatchOverlay(
        candidate: candidate,
        myAvatarUrl: null,
        onClose: () => closed = true,
      ),
    ));

    expect(find.text('你们已互相喜欢'), findsOneWidget);
    expect(find.text('和 小红 打个招呼吧'), findsOneWidget);
    expect(find.byIcon(Icons.person), findsOneWidget); // 我没头像时的占位
    expect(find.byKey(const Key('match.continue')), findsOneWidget);

    await tester.tap(find.byKey(const Key('match.continue')));
    expect(closed, isTrue);
  });

  testWidgets('给了 onGoChat 才显示「去聊天」;点了触发回调', (tester) async {
    final candidate = Candidate.fromJson(candidateJson(nickname: '小红'));
    var wentChat = false;

    await tester.pumpWidget(MaterialApp(
      home: MatchOverlay(
        candidate: candidate,
        onClose: () {},
        onGoChat: () => wentChat = true,
      ),
    ));

    await tester.tap(find.byKey(const Key('match.goChat')));
    expect(wentChat, isTrue);
  });

  testWidgets('不给 onGoChat 时没有「去聊天」', (tester) async {
    final candidate = Candidate.fromJson(candidateJson(nickname: '小红'));

    await tester.pumpWidget(MaterialApp(
      home: MatchOverlay(candidate: candidate, onClose: () {}),
    ));

    expect(find.byKey(const Key('match.goChat')), findsNothing);
  });
}
