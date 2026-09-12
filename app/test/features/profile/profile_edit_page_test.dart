import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

void main() {
  testWidgets('改昵称保存 → PATCH 带上表单内容', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /users/tags': (options) => ok([tagJson(1, '运动')]),
      'PATCH /users/me': (options) => ok(profileJson(nickname: '新昵称')),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('my.row.nickname')));
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('edit.nickname')), '新昵称');
    await tester.tap(find.byKey(const Key('edit.save')));
    await tester.pumpAndSettle();

    final patch = adapter.log.lastWhere((r) => r.method == 'PATCH').data as Map<String, dynamic>;
    expect(patch['nickname'], '新昵称');
    expect(patch['tag_ids'], isEmpty);
    expect(find.text('已保存'), findsOneWidget);
  });

  testWidgets('后端 400(如违规词)→ SnackBar 显示中文提示', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /users/tags': (options) => ok([]),
      'PATCH /users/me': (options) => jsonError(400, '昵称包含违规内容,请修改'),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('my.row.nickname')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('edit.save')));
    await tester.pumpAndSettle();

    expect(find.text('昵称包含违规内容,请修改'), findsOneWidget);
  });
}
