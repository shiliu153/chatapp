import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/presence/online_dot.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

ScriptedAdapter _adapter(Map<String, dynamic> postsPage,
        {Map<String, dynamic>? presence}) =>
    ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(nickname: '小明')),
      'GET /posts': (options) => ok(postsPage),
      'GET /presence': (options) => ok(presence ?? {'results': []}),
    });

Future<void> _openSquare(WidgetTester tester) async {
  await tester.tap(navTab('广场'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('广场流渲染卡片(昵称/文字/计数)', (tester) async {
    final adapter = _adapter(pageJson([
      postJson(id: 1, nickname: 'Alice', text: '今天天气真好', likeCount: 3, commentCount: 1),
    ]));
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await _openSquare(tester);

    expect(find.text('Alice'), findsOneWidget);
    expect(find.text('今天天气真好'), findsOneWidget);
    expect(find.text('3'), findsOneWidget);
    expect(find.byKey(const Key('square.fab')), findsOneWidget);
  });

  testWidgets('空态显示提示与刷新', (tester) async {
    final adapter = _adapter(pageJson([]));
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await _openSquare(tester);

    expect(find.text('还没有动态,发一条吧'), findsOneWidget);
  });

  testWidgets('点赞乐观更新;失败回滚', (tester) async {
    final adapter = _adapter(pageJson([postJson(id: 1, nickname: 'Alice', text: '赞我')]));
    adapter.routes['POST /posts/1/like'] = offline;   // 请求失败 → 走回滚分支

    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await _openSquare(tester);

    await tester.tap(find.byKey(const Key('post.like.1')));
    await tester.pump();   // 乐观:马上变红
    expect(tester.widget<Icon>(find.byIcon(Icons.favorite)).color,
        const Color(0xFFFF2C55));
    await tester.pumpAndSettle();   // 请求失败 → 回滚
    expect(find.byIcon(Icons.favorite_border), findsOneWidget);
  });

  testWidgets('别人的动态菜单是举报,提交后提示', (tester) async {
    final adapter = _adapter(
        pageJson([postJson(id: 2, authorId: 9, nickname: 'Alice', text: '别人的')]));
    adapter.routes['POST /posts/2/report'] =
        (options) => ok({'id': 1, 'status': 'pending'}, status: 201);

    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await _openSquare(tester);

    await tester.tap(find.byKey(const Key('post.more.2')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('post.menu.report')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('report.type.porn')));
    await tester.pump();
    await tester.tap(find.byKey(const Key('report.submit')));
    await tester.pumpAndSettle();
    expect(find.text('已收到举报,我们会尽快处理'), findsOneWidget);
  });

  testWidgets('自己的动态菜单是删除', (tester) async {
    final adapter =
        _adapter(pageJson([postJson(id: 3, authorId: 7, nickname: '小明', text: '我发的')]));

    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await _openSquare(tester);

    await tester.tap(find.byKey(const Key('post.more.3')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('post.menu.delete')), findsOneWidget);
    expect(find.byKey(const Key('post.menu.report')), findsNothing);
  });

  testWidgets('点头像打开公开资料页', (tester) async {
    final adapter = _adapter(
        pageJson([postJson(id: 1, authorId: 9, nickname: 'Alice', text: '你好')]));
    adapter.routes['GET /users/9'] =
        (options) => ok(publicProfileJson(userId: 9, nickname: 'Alice'));

    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await _openSquare(tester);

    await tester.tap(find.byKey(const Key('post.avatar.1')));
    await tester.pumpAndSettle();

    expect(find.text('详细资料'), findsOneWidget);
    expect(find.text('ID:u9'), findsOneWidget);
  });

  testWidgets('点昵称打开公开资料页', (tester) async {
    final adapter = _adapter(
        pageJson([postJson(id: 1, authorId: 9, nickname: 'Alice', text: '你好')]));
    adapter.routes['GET /users/9'] =
        (options) => ok(publicProfileJson(userId: 9, nickname: 'Alice'));

    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await _openSquare(tester);

    await tester.tap(find.byKey(const Key('post.nickname.1')));
    await tester.pumpAndSettle();

    expect(find.text('详细资料'), findsOneWidget);
  });

  testWidgets('自己的动态点头像不打开资料页', (tester) async {
    final adapter =
        _adapter(pageJson([postJson(id: 3, authorId: 7, nickname: '小明', text: '我发的')]));

    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await _openSquare(tester);

    await tester.tap(find.byKey(const Key('post.avatar.3')));
    await tester.pumpAndSettle();

    // 完全没反应:既不进资料页,也不触发外层卡片进详情
    expect(find.text('详细资料'), findsNothing);
    expect(find.text('动态详情'), findsNothing);
  });

  testWidgets('作者在线时头像右下角显示绿点,离线不显示', (tester) async {
    final adapter = _adapter(
      pageJson([
        postJson(id: 1, authorId: 9, nickname: 'Alice', text: '在线的人'),
        postJson(id: 2, authorId: 10, nickname: 'Bob', text: '离线的人'),
      ]),
      presence: {
        'results': [
          {'user_id': 9, 'online': true, 'last_active_at': null},
          {'user_id': 10, 'online': false, 'last_active_at': '2026-09-13T10:00:00+08:00'},
        ],
      },
    );

    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await _openSquare(tester);
    await tester.pumpAndSettle();

    expect(
        find.descendant(
            of: find.byKey(const Key('post.avatar.1')), matching: find.byType(OnlineDot)),
        findsOneWidget);
    expect(
        find.descendant(
            of: find.byKey(const Key('post.avatar.2')), matching: find.byType(OnlineDot)),
        findsNothing);
    // 查的正是两条动态的作者 id
    final request = adapter.log.lastWhere((r) => r.path == '/presence');
    expect(request.queryParameters['user_ids'], contains('9'));
    expect(request.queryParameters['user_ids'], contains('10'));
  });
}
