import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/square/models.dart';
import 'package:chatapp_app/features/square/widgets/post_card.dart';

Post _post({required bool liked}) => Post(
      id: 1,
      author: const FeedAuthor(userId: 9, nickname: 'Alice'),
      text: '正文',
      images: const [],
      likeCount: liked ? 1 : 0,
      commentCount: 0,
      likedByMe: liked,
      createdAt: DateTime(2026, 9, 12, 20),
    );

void main() {
  testWidgets('点赞翻转触发心跳脉冲:scale 峰值 >1(有限 pump)', (tester) async {
    Post post = _post(liked: false);
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: StatefulBuilder(
          builder: (context, setState) => PostCard(
            post: post,
            isMine: false,
            onToggleLike: () => setState(() => post = _post(liked: !post.likedByMe)),
          ),
        ),
      ),
    ));
    await tester.pump();

    await tester.tap(find.byKey(const Key('post.like.1')));
    await tester.pump(); // 乐观翻转 → 脉冲启动
    await tester.pump(const Duration(milliseconds: 80)); // 推到上升段

    // 只找点赞位的 ScaleTransition(评论位没有动画);
    // 注意 find.ancestor 有两层命中:内层是脉冲(先),外层是 AppCard 按压 AnimatedScale(后)→ 取 first
    final pulse = find.ancestor(
        of: find.byIcon(Icons.favorite_rounded),
        matching: find.byType(ScaleTransition));
    expect(pulse, findsWidgets);
    final scale = tester.widget<ScaleTransition>(pulse.first).scale.value;
    expect(scale, greaterThan(1.0));

    await tester.pumpAndSettle(); // 脉冲收尾(有界)
  });

  testWidgets('取消赞不触发脉冲', (tester) async {
    Post post = _post(liked: true);
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: StatefulBuilder(
          builder: (context, setState) => PostCard(
            post: post,
            isMine: false,
            onToggleLike: () => setState(() => post = _post(liked: !post.likedByMe)),
          ),
        ),
      ),
    ));
    await tester.pump();

    await tester.tap(find.byKey(const Key('post.like.1')));
    await tester.pump(const Duration(milliseconds: 80));

    final pulse = find.ancestor(
        of: find.byIcon(Icons.favorite_border_rounded),
        matching: find.byType(ScaleTransition));
    expect(pulse, findsWidgets); // 两层:内层脉冲 + 外层 AppCard 按压层
    final scale = tester.widget<ScaleTransition>(pulse.first).scale.value;
    expect(scale, 1.0); // 脉冲没被触发
  });
}
