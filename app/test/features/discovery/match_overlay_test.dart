import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_avatar.dart';
import 'package:chatapp_app/features/discovery/models.dart';
import 'package:chatapp_app/features/discovery/widgets/match_overlay.dart';

import '../../support/sample_data.dart';

/// 完成帧文案的不透明度(0=未入场,1=完成帧)。
double _textOpacity(WidgetTester tester) => tester
    .widget<Opacity>(
      find.ancestor(of: find.text('你们已互相喜欢'), matching: find.byType(Opacity)).first,
    )
    .opacity;

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
    expect(find.byType(AppAvatar), findsNWidgets(2)); // 双头像在位(无头像侧回退占位)
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

  testWidgets('编排结束后完成帧可见', (tester) async {
    final candidate = Candidate.fromJson(candidateJson(nickname: '小红'));
    await tester.pumpWidget(
      MaterialApp(home: MatchOverlay(candidate: candidate, onClose: () {})),
    );
    await tester.pumpAndSettle();

    expect(_textOpacity(tester), 1);
  });

  testWidgets('点击任意处直达完成帧', (tester) async {
    final candidate = Candidate.fromJson(candidateJson(nickname: '小红'));
    await tester.pumpWidget(
      MaterialApp(home: MatchOverlay(candidate: candidate, onClose: () {})),
    );
    await tester.pump();
    expect(_textOpacity(tester), lessThan(1)); // 首帧还没走完编排

    await tester.tapAt(const Offset(20, 20));
    await tester.pump();
    expect(_textOpacity(tester), 1);
  });

  testWidgets('减弱动态效果 → 初始即完成帧', (tester) async {
    final candidate = Candidate.fromJson(candidateJson(nickname: '小红'));
    await tester.pumpWidget(MaterialApp(
      home: MediaQuery(
        data: const MediaQueryData(disableAnimations: true),
        child: MatchOverlay(candidate: candidate, onClose: () {}),
      ),
    ));
    expect(_textOpacity(tester), 1);
  });
}
