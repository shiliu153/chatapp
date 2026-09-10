import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

void main() {
  testWidgets('资料完善 → 显示第一张卡;点喜欢发 like 请求并换下一张', (tester) async {
    var calls = 0;
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /discovery/candidates': (options) {
        calls += 1;
        return calls == 1
            ? ok([candidateJson(userId: 9, nickname: '小红'),
                  candidateJson(userId: 10, nickname: '小刚')])
            : ok([]);
      },
      'POST /discovery/swipe': (options) => ok({'matched': false}),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(find.text('小红,25'), findsOneWidget);

    await tester.tap(find.byKey(const Key('discovery.like')));
    await tester.pumpAndSettle();

    final request = adapter.log.lastWhere((item) => item.method == 'POST');
    expect(request.data, {'target_user_id': 9, 'action': 'like'});
    expect(find.text('小红,25'), findsNothing);
    expect(find.text('小刚,25'), findsOneWidget);
  });

  testWidgets('互相喜欢 → 弹配对动效;点继续滑卡回到卡组', (tester) async {
    var calls = 0;
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /discovery/candidates': (options) {
        calls += 1;
        return calls == 1
            ? ok([candidateJson(userId: 9, nickname: '小红'),
                  candidateJson(userId: 10, nickname: '小刚')])
            : ok([]);
      },
      'POST /discovery/swipe': (options) => ok({'matched': true}),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('discovery.like')));
    await tester.pumpAndSettle();

    expect(find.text('你们已互相喜欢'), findsOneWidget);
    expect(find.text('和 小红 打个招呼吧'), findsOneWidget);

    await tester.tap(find.byKey(const Key('match.continue')));
    await tester.pumpAndSettle();

    expect(find.text('你们已互相喜欢'), findsNothing);
    expect(find.text('小刚,25'), findsOneWidget);
  });

  testWidgets('没有候选 → 空态;点刷新重新拉', (tester) async {
    var calls = 0;
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /discovery/candidates': (options) {
        calls += 1;
        return calls == 1 ? ok([]) : ok([candidateJson(userId: 9, nickname: '小红')]);
      },
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(find.text('附近暂时没有新的人了'), findsOneWidget);

    await tester.tap(find.byKey(const Key('discovery.refresh')));
    await tester.pumpAndSettle();

    expect(find.text('小红,25'), findsOneWidget);
  });

  testWidgets('拉候选失败 → 显示错误并能重试', (tester) async {
    var calls = 0;
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /discovery/candidates': (options) {
        calls += 1;
        return calls == 1
            ? jsonError(500, '服务器开小差了')
            : ok([candidateJson(userId: 9, nickname: '小红')]);
      },
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(find.textContaining('服务器开小差了'), findsOneWidget);

    await tester.tap(find.text('重试'));
    await tester.pumpAndSettle();

    expect(find.text('小红,25'), findsOneWidget);
  });

  testWidgets('滑卡失败 → 提示错误且卡片回到队首', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /discovery/candidates': (options) => ok([candidateJson(userId: 9, nickname: '小红')]),
      'POST /discovery/swipe': (options) => jsonError(429, '操作太快了,休息一下吧'),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('discovery.like')));
    await tester.pumpAndSettle();

    expect(find.text('操作太快了,休息一下吧'), findsOneWidget);
    expect(find.text('小红,25'), findsOneWidget);
  });
}
