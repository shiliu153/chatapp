import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

ScriptedAdapter _adapter(Map<String, dynamic> postsPage) => ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(nickname: '小明')),
      'GET /posts': (options) => ok(postsPage),
      'GET /presence': (options) => ok({'results': []}),
    });

Future<void> _openSquare(WidgetTester tester) async {
  await tester.tap(navTab('广场'));
  await tester.pumpAndSettle();
}

/// 收藏是私密书签:菜单项对「自己」和「他人」的动态都要有,
/// 且做乐观翻转 —— 失败必须回滚,不能留一个假的已收藏态。
void main() {
  testWidgets('别人的动态也能收藏:乐观翻转 → 再开菜单变「取消收藏」', (tester) async {
    final adapter =
        _adapter(pageJson([postJson(id: 2, authorId: 9, nickname: 'Alice', text: '别人的')]));
    adapter.routes['POST /posts/2/favorite'] = (options) => ok({}, status: 204);
    adapter.routes['DELETE /posts/2/favorite'] = (options) => ok({}, status: 204);

    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await _openSquare(tester);

    await tester.tap(find.byKey(const Key('post.more.2')));
    await tester.pumpAndSettle();
    // 收藏与「举报」同在:它是第三种动作,不是 isMine 二选一里的一支
    expect(find.byKey(const Key('post.menu.favorite')), findsOneWidget);
    expect(find.byKey(const Key('post.menu.report')), findsOneWidget);
    expect(find.text('收藏'), findsOneWidget);

    await tester.tap(find.text('收藏'));
    await tester.pumpAndSettle();

    expect(
        adapter.log.where((r) => r.method == 'POST' && r.path == '/posts/2/favorite'),
        hasLength(1));
    expect(find.text('已收藏'), findsOneWidget);

    // 再开菜单:标签跟着乐观翻转后的状态走
    await tester.tap(find.byKey(const Key('post.more.2')));
    await tester.pumpAndSettle();
    expect(find.text('取消收藏'), findsOneWidget);

    // 取消收藏同样打到 DELETE
    await tester.tap(find.text('取消收藏'));
    await tester.pumpAndSettle();
    expect(
        adapter.log.where((r) => r.method == 'DELETE' && r.path == '/posts/2/favorite'),
        hasLength(1));
    expect(find.text('已取消收藏'), findsOneWidget);

    await drainToast(tester);
  });

  testWidgets('收藏失败:回滚到「未收藏」并提示后端原因', (tester) async {
    final adapter =
        _adapter(pageJson([postJson(id: 3, authorId: 9, nickname: 'Alice', text: '别人的')]));
    adapter.routes['POST /posts/3/favorite'] =
        (options) => jsonError(500, '服务器开小差了');

    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await _openSquare(tester);

    await tester.tap(find.byKey(const Key('post.more.3')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('收藏'));
    await tester.pumpAndSettle();

    expect(find.text('服务器开小差了'), findsOneWidget);

    // 回滚:菜单里仍是「收藏」,没有被乐观更新留在已收藏态
    await tester.tap(find.byKey(const Key('post.more.3')));
    await tester.pumpAndSettle();
    expect(find.text('收藏'), findsOneWidget);
    expect(find.text('取消收藏'), findsNothing);

    await drainToast(tester);
  });
}
