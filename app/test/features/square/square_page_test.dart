import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_colors.dart';
import 'package:chatapp_app/core/widgets/breathing_dot.dart';
import 'package:chatapp_app/features/profile/user_profile_page.dart';

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

  testWidgets('空态:涟漪 + 文案 + 发布按钮,点按钮进发布页', (tester) async {
    final adapter = _adapter(pageJson([]));
    await pumpApp(tester, adapter, prefs: _loggedIn);
    // 广场空态的 HeartRipple 在 IndexedStack 隐藏页也一直跑:全程禁 settle
    await pumpFrames(tester);
    await tester.tap(navTab('广场'));
    await pumpFrames(tester); // HeartRipple 无限动画,禁 settle

    expect(find.text('广场'), findsNWidgets(2)); // 底栏 tab + 页内大标题
    expect(find.text('还没有动态'), findsOneWidget);
    expect(find.text('发一条,让大家认识你'), findsOneWidget);

    await tester.tap(find.byKey(const Key('square.compose')));
    await pumpFrames(tester);
    expect(find.text('发布动态'), findsOneWidget); // 发布页顶栏标题
  });

  testWidgets('加载失败 → AppErrorView,square.retry 重试成功', (tester) async {
    final adapter = _adapter(pageJson([]));
    adapter.routes['GET /posts'] = offline;
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await pumpFrames(tester); // 错误态无无限动画,但起始 IndexedStack 里广场页在转圈
    await tester.tap(navTab('广场'));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('square.retry')), findsOneWidget);

    adapter.routes['GET /posts'] =
        (options) => ok(pageJson([postJson(id: 1, text: '恢复')]));
    await tester.tap(find.byKey(const Key('square.retry')));
    await tester.pumpAndSettle();
    expect(find.text('恢复'), findsOneWidget);
  });

  testWidgets('点赞乐观更新;失败回滚', (tester) async {
    final adapter = _adapter(pageJson([postJson(id: 1, nickname: 'Alice', text: '赞我')]));
    adapter.routes['POST /posts/1/like'] = offline;   // 请求失败 → 走回滚分支

    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await _openSquare(tester);

    await tester.tap(find.byKey(const Key('post.like.1')));
    await tester.pump();   // 乐观:马上变红
    expect(tester.widget<Icon>(find.byIcon(Icons.favorite_rounded)).color,
        AppColors.brand);
    await tester.pumpAndSettle();   // 请求失败 → 回滚
    expect(find.byIcon(Icons.favorite_border_rounded), findsOneWidget);
    await tester.pump(const Duration(seconds: 3)); // AppToast 2s Timer 收尾
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
    await drainToast(tester); // Toast Timer 收尾,否则 pending timer 报错
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

    expect(find.byType(UserProfilePage), findsOneWidget);
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

    expect(find.byType(UserProfilePage), findsOneWidget);
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
    expect(find.byType(UserProfilePage), findsNothing);
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
    await pumpFrames(tester); // 呼吸点是无限动画,不能 pumpAndSettle
    await tester.tap(navTab('广场'));
    await pumpFrames(tester);

    expect(
        find.descendant(
            of: find.byKey(const Key('post.avatar.1')),
            matching: find.byType(BreathingDot)),
        findsOneWidget);
    expect(
        find.descendant(
            of: find.byKey(const Key('post.avatar.2')),
            matching: find.byType(BreathingDot)),
        findsNothing);
    // 查的正是两条动态的作者 id
    final request = adapter.log.lastWhere((r) => r.path == '/presence');
    expect(request.queryParameters['user_ids'], contains('9'));
    expect(request.queryParameters['user_ids'], contains('10'));
  });
}
