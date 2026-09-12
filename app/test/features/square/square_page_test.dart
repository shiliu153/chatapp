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
}
