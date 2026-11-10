import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/profile/user_profile_page.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

ScriptedAdapter _adapter(Map<String, dynamic> postsPage, Map<String, dynamic> likesPage) =>
    ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(nickname: '小明')),
      'GET /posts': (options) => ok(postsPage),
      'GET /presence': (options) => ok({'results': []}),
      'GET /posts/1/likes': (options) => ok(likesPage),
      'GET /users/8': (options) => ok(publicProfileJson(userId: 8, nickname: '小雨8')),
    });

/// 点赞数字是独立的入口:点它打开「点赞」二级页,而不是触发点赞。
void main() {
  testWidgets('点点赞数字进点赞列表:昵称 + 时间,点行进资料页', (tester) async {
    final adapter = _adapter(
      pageJson([postJson(id: 1, authorId: 9, nickname: 'Alice', text: '赞我', likeCount: 2)]),
      cursorPageJson([
        postLikerJson(userId: 8, nickname: '小雨8'),
        postLikerJson(userId: 9, nickname: 'Alice', avatarUrl: 'http://test/a.png'),
      ]),
    );
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('广场'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('post.likeCount.1')));
    await tester.pumpAndSettle();

    // 顶栏标题 + 两行点赞者
    expect(find.text('点赞'), findsOneWidget);
    expect(find.byKey(const Key('postLikes.list')), findsOneWidget);
    expect(find.text('小雨8'), findsOneWidget);
    expect(find.byKey(const Key('postLikes.row.8')), findsOneWidget);

    // 数字区只是「打开列表」:没顺手把这条动态点赞
    expect(adapter.log.where((r) => r.path == '/posts/1/like'), isEmpty);
    expect(adapter.log.where((r) => r.path == '/posts/1/likes'), hasLength(1));

    await tester.tap(find.byKey(const Key('postLikes.row.8')));
    await tester.pumpAndSettle();
    expect(find.byType(UserProfilePage), findsOneWidget);
  });

  testWidgets('没人点赞:空态文案,不崩', (tester) async {
    final adapter = _adapter(
      pageJson([postJson(id: 1, authorId: 9, nickname: 'Alice', text: '赞我', likeCount: 3)]),
      cursorPageJson([]),
    );
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('广场'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('post.likeCount.1')));
    // 空态里的涟漪是无限动画,只能有限 pump
    await pumpFrames(tester);

    expect(find.byKey(const Key('postLikes.empty')), findsOneWidget);
    expect(find.text('还没有人点赞'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
