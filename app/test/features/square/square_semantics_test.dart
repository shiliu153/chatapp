import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/features/square/models.dart';
import 'package:chatapp_app/features/square/widgets/comment_thread.dart';
import 'package:chatapp_app/features/square/widgets/post_card.dart';
import 'package:chatapp_app/features/square/widgets/post_reaction_buttons.dart';

import '../../support/sample_data.dart';

/// 回声(广场)线 Semantics 断言(E-5.5 page spec §6 第 3 条)。
///
/// 三条播报口径(规范 §8.4「读屏播报」+ page spec §6):
/// 1. 动态卡 =「作者,正文摘要,N 赞,M 评论」;
/// 2. 点赞钮 =「赞,已赞 / 未赞」—— **颜色不是唯一线索**,字重与文案同时变;
/// 3. 评论项 =「作者,内容,时间」。
///
/// 为什么按 `find.bySemanticsLabel` 判而不截图:金图能证明「看起来不一样」,
/// 但读屏能不能念出来只有语义树知道(§8.4「颜色不是唯一线索」)。
void main() {
  /// 统一挂真实主题(`context.ember` 需要 `EmberColors` 扩展)并打开语义。
  Future<void> pump(WidgetTester tester, Widget child) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(brightness: Brightness.light),
        home: Scaffold(body: Center(child: SizedBox(width: 390, child: child))),
      ),
    );
    await tester.pump();
  }

  Post samplePost({bool liked = false}) => Post.fromJson(postJson(
        id: 1,
        nickname: '小红',
        text: '江边走了很久',
        likeCount: 12,
        commentCount: 3,
        likedByMe: liked,
      ));

  testWidgets('动态卡:`作者,正文摘要,N 赞,M 评论`', (tester) async {
    final handle = tester.ensureSemantics();
    await pump(
      tester,
      PostCard(post: samplePost(), isMine: false, onTap: () {}),
    );
    expect(
      find.bySemanticsLabel(RegExp('小红.*江边走了很久.*12 赞.*3 评论')),
      findsOneWidget,
    );
    handle.dispose();
  });

  testWidgets('动态卡(详情页静态卡):同样播报卡片信息', (tester) async {
    final handle = tester.ensureSemantics();
    // 详情页顶卡的 onTap 为 null(点卡不再进详情),语义容器由 PostCard 自己补。
    await pump(tester, PostCard(post: samplePost(), isMine: false));
    expect(
      find.bySemanticsLabel(RegExp('小红.*江边走了很久.*12 赞.*3 评论')),
      findsOneWidget,
    );
    handle.dispose();
  });

  testWidgets('点赞钮:未赞读「赞,未赞」,已赞读「赞,已赞」', (tester) async {
    final handle = tester.ensureSemantics();
    await pump(tester, PostLikeButton(liked: false, onTap: () {}));
    expect(find.bySemanticsLabel('赞，未赞'), findsOneWidget);
    expect(find.bySemanticsLabel('赞，已赞'), findsNothing);

    await pump(tester, PostLikeButton(liked: true, onTap: () {}));
    expect(find.bySemanticsLabel('赞，已赞'), findsOneWidget);
    expect(find.bySemanticsLabel('赞，未赞'), findsNothing);
    handle.dispose();
  });

  testWidgets('评论项:`作者,内容,时间`', (tester) async {
    final handle = tester.ensureSemantics();
    await pump(
      tester,
      CommentTile(
        comment: PostCommentItem.fromJson(commentJson(
          id: 5,
          nickname: '阿秋',
          text: '江边这个点风最大',
          createdAt: '2026-11-24T12:30:00+08:00',
        )),
        depth: 0,
        isMine: false,
        onReply: () {},
        onDelete: () {},
      ),
    );
    // 时间走 `formatPostTime`,这里只钉「作者 + 内容 + 时间三者都在同一条播报里」。
    final node = find.bySemanticsLabel(RegExp('阿秋，江边这个点风最大，'));
    expect(node, findsOneWidget);
    handle.dispose();
  });
}
