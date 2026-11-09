import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/discovery/discovery_clock.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

/// 批次 O 的发现页单测:撤销按钮(30 秒窗口)与每日喜欢额度提示。
///
/// 关键手法:撤销按钮的倒计时是**动画**驱动的,所以「滑卡之后」不能 `pumpAndSettle`
/// —— 那会把 30 秒一口气推完、按钮直接置灰。要验证「可用」就先 `pump` 到请求回来
/// 为止,验证「置灰」再显式推过 30 秒。
const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

/// 假时钟:额度冷却(42904 的 `Retry-After`)按它算。
final _fixedNow = DateTime(2026, 11, 9, 20);

final _undoKey = find.byKey(const Key('discovery.undo'));

/// 滑一张卡并把请求放行到「响应已回来」,但**不**推完 30 秒倒计时。
Future<void> _swipeAndSettle(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('discovery.like')));
  // 飞出动画(250ms)+ 请求往返;总共只推 0.8 秒,离 30 秒窗口还远
  for (var i = 0; i < 8; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

/// 发现页通用铺底:两张卡 + 一条额度快照(默认「不限」)。
///
/// 候选池只给一次:卡少了会触发续拉,把刚滑掉的人再发回来(去重后追加在队尾),
/// 「撤销后回到队首」就看不清了 —— 这里让续拉返回空,卡组状态可控。
ScriptedAdapter _adapter({Map<String, dynamic>? quota}) {
  var candidateCalls = 0;
  return ScriptedAdapter({
    'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
    'GET /users/me': (options) => ok(profileJson()),
    'GET /discovery/candidates': (options) {
      candidateCalls += 1;
      return candidateCalls == 1
          ? ok([
              candidateJson(userId: 9, nickname: '小红'),
              candidateJson(userId: 10, nickname: '小刚'),
            ])
          : ok([]);
    },
    'GET /discovery/quota': (options) => ok(quota ??
        {'like_limit': 0, 'likes_used': 0, 'likes_remaining': null}),
    'POST /discovery/swipe': (options) => ok({'matched': false}),
  });
}

void main() {
  testWidgets('没划过卡 → 不显示撤销按钮', (tester) async {
    final adapter = _adapter();
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(_undoKey, findsNothing);
    expect(find.text('小红,25'), findsOneWidget);
  });

  testWidgets('滑卡后出现撤销按钮;点它把刚划掉的卡放回卡堆顶部', (tester) async {
    final adapter = _adapter();
    adapter.routes['POST /discovery/swipe/undo'] =
        (options) => ok({'undone': true, 'target_user_id': 9});
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await _swipeAndSettle(tester);

    expect(find.text('小红,25'), findsNothing);
    expect(find.text('小刚,25'), findsOneWidget);
    expect(_undoKey, findsOneWidget);

    await tester.tap(_undoKey);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    expect(adapter.log.where((item) => item.path == '/discovery/swipe/undo'), hasLength(1));
    // 卡回到**卡堆顶部**(不是队尾),撤销按钮收起(没有「上一次」可撤了)
    expect(
      find.descendant(
          of: find.byKey(const Key('deck.topCard')), matching: find.text('小红,25')),
      findsOneWidget,
    );
    expect(find.text('小刚,25'), findsOneWidget); // 原来那张退到第二张
    expect(find.text('已撤销'), findsOneWidget);
    expect(_undoKey, findsNothing);

    await drainToast(tester);
  });

  testWidgets('撤销超过 30 秒 → 按钮置灰,点了也不发请求', (tester) async {
    final adapter = _adapter();
    adapter.routes['POST /discovery/swipe/undo'] =
        (options) => ok({'undone': true, 'target_user_id': 9});
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await _swipeAndSettle(tester);
    expect(_undoKey, findsOneWidget);

    await tester.pump(const Duration(seconds: 31)); // 推过 30 秒窗口
    await tester.pump();
    expect(_undoKey, findsOneWidget); // 置灰但仍在,不突然消失

    await tester.tap(_undoKey);
    await tester.pump(const Duration(milliseconds: 100));

    expect(adapter.log.where((item) => item.path == '/discovery/swipe/undo'), isEmpty);
    expect(find.text('小红,25'), findsNothing);
  });

  testWidgets('撤销回 40003 → 提示「没有可撤销的操作」并隐藏按钮', (tester) async {
    final adapter = _adapter();
    adapter.routes['POST /discovery/swipe/undo'] =
        (options) => jsonErrorWithHeaders(400, code: 40003, message: '没有可撤销的滑卡');
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await _swipeAndSettle(tester);
    await tester.tap(_undoKey);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    expect(find.text('没有可撤销的操作'), findsOneWidget);
    expect(_undoKey, findsNothing);
    expect(find.text('小红,25'), findsNothing); // 没撤销成功,卡不该回来

    await drainToast(tester);
  });

  testWidgets('额度开启 → 显示「今日还可喜欢 N 次」,喜欢一次后减一', (tester) async {
    final adapter = _adapter(
        quota: {'like_limit': 10, 'likes_used': 3, 'likes_remaining': 7});
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(find.text('今日还可喜欢 7 次'), findsOneWidget);

    await _swipeAndSettle(tester);

    expect(find.text('今日还可喜欢 6 次'), findsOneWidget);
  });

  testWidgets('like_limit = 0(不限)→ 额度文案整块不渲染', (tester) async {
    final adapter = _adapter(
        quota: {'like_limit': 0, 'likes_used': 0, 'likes_remaining': null});
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('discovery.quota')), findsNothing);
    expect(find.textContaining('今日还可喜欢'), findsNothing);
  });

  testWidgets('喜欢超限 429/42904 → 提示「今日喜欢次数已用完」并禁用喜欢按钮', (tester) async {
    final adapter =
        _adapter(quota: {'like_limit': 10, 'likes_used': 9, 'likes_remaining': 1});
    adapter.routes['POST /discovery/swipe'] = (options) => jsonErrorWithHeaders(
          429,
          code: 42904,
          message: '今日喜欢次数已用完',
          headers: {'Retry-After': '3600'},
        );
    await pumpApp(tester, adapter, prefs: _loggedIn, overrides: [
      // 冷却窗按假时钟算,不然「禁用到什么时候」没法断言
      discoveryClockProvider.overrideWithValue(() => _fixedNow),
    ]);
    await tester.pumpAndSettle();

    await _swipeAndSettle(tester);

    expect(find.text('今日喜欢次数已用完,明天再来'), findsOneWidget);
    // 卡没被划掉:失败后放回队首
    expect(find.text('小红,25'), findsOneWidget);

    await drainToast(tester); // 浮层盖在操作钮上方,先收掉再点
    final posts = adapter.log.where((item) => item.path == '/discovery/swipe').length;
    await tester.tap(find.byKey(const Key('discovery.like')));
    await tester.pump(const Duration(milliseconds: 300));
    await tester.pump(const Duration(milliseconds: 100));
    expect(adapter.log.where((item) => item.path == '/discovery/swipe'), hasLength(posts),
        reason: '额度用完时喜欢按钮应置灰,不该再发请求');
  });
}
