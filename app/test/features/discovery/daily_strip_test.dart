import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

/// 批次 S:「今日精选」区块。
///
/// 契约要点(discovery.md §3.11):响应是**包装对象** `{date, candidates}`,
/// `candidates` 为空时整块不渲染;卡片字段与候选卡一致。
const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

ScriptedAdapter _adapter({Object? daily}) => ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /users/9': (options) => ok(publicProfileJson(userId: 9, nickname: '小红')),
      'GET /discovery/candidates': (options) => ok([candidateJson(userId: 9)]),
      'GET /discovery/daily': (options) => ok(daily ?? dailyJson()),
    });

List<Map<String, dynamic>> _sixCards() => [
      for (var i = 0; i < 6; i++)
        candidateJson(userId: 20 + i, nickname: '精选$i', city: '杭州'),
    ];

void main() {
  testWidgets('daily 返回 6 张 → 渲染 6 张可横向滚动的卡', (tester) async {
    // 窄屏(360dp):6 张卡放不下一屏,靠横向滚动看后面的人
    tester.view.physicalSize = const Size(360 * 3, 780 * 3);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);

    final adapter = _adapter(daily: dailyJson(candidates: _sixCards()));
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('discovery.daily')), findsOneWidget);
    expect(find.text('今日精选'), findsOneWidget);
    final list = tester.widget<ListView>(find.descendant(
        of: find.byKey(const Key('discovery.daily')), matching: find.byType(ListView)));
    expect(list.scrollDirection, Axis.horizontal);

    // 首卡可见,末卡在屏幕外(懒加载),横向拖动后露出来
    expect(find.byKey(const Key('discovery.daily.card.20')), findsOneWidget);
    expect(find.byKey(const Key('discovery.daily.card.25')), findsNothing);
    await tester.drag(find.byType(ListView).first, const Offset(-420, 0));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('discovery.daily.card.25')), findsOneWidget);
  });

  testWidgets('daily.candidates 为空 → 整块不渲染', (tester) async {
    final adapter = _adapter(daily: dailyJson());
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('discovery.daily')), findsNothing);
    expect(find.text('今日精选'), findsNothing);
    // 滑卡主流程照旧
    expect(find.text('小红,25'), findsOneWidget);
  });

  testWidgets('daily 请求失败 → 整块不渲染,但滑卡不受影响', (tester) async {
    final adapter = _adapter(daily: null);
    adapter.routes['GET /discovery/daily'] = (options) => jsonError(500, '精选拉不动');
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('discovery.daily')), findsNothing);
    expect(find.textContaining('精选拉不动'), findsNothing);
    expect(find.text('小红,25'), findsOneWidget);
  });

  testWidgets('点精选卡 → 进对方资料页', (tester) async {
    final adapter = _adapter(
        daily: dailyJson(candidates: [candidateJson(userId: 9, nickname: '小红')]));
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('discovery.daily.card.9')));
    await tester.pumpAndSettle();

    expect(find.text('ID:u9'), findsOneWidget);
    expect(find.text('喜欢爬山'), findsOneWidget);
  });

  testWidgets('矮屏(600dp)下精选区块 + 空态不溢出', (tester) async {
    // 加了精选区块后卡组区在矮屏会变窄:空态 + 撤销按钮的自然高度可能超出可用高度,
    // 这里钉住「不许抛 RenderFlex overflow」(线上表现为黄黑条 / 内容被截)
    tester.view.physicalSize = const Size(360 * 3, 600 * 3);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);

    final adapter = _adapter(
        daily: dailyJson(candidates: [candidateJson(userId: 9, nickname: '小红')]));
    adapter.routes['POST /discovery/swipe'] = (options) => ok({'matched': false});
    // 第一张划掉后候选池见底(续拉拿回空列表),页面才会落到空态
    var calls = 0;
    adapter.routes['GET /discovery/candidates'] = (options) {
      calls += 1;
      return ok(calls == 1 ? [candidateJson(userId: 9, nickname: '小红')] : []);
    };
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('discovery.like')));
    await pumpFrames(tester);

    expect(tester.takeException(), isNull);
    expect(find.text('附近暂时没有新的人了'), findsOneWidget);
  });

  testWidgets('资料未完善 → 不请求精选,也不渲染区块', (tester) async {
    final adapter = _adapter(
        daily: dailyJson(candidates: [candidateJson(userId: 9, nickname: '小红')]));
    adapter.routes['GET /users/me'] =
        (options) => ok(profileJson(missing: ['nickname', 'birthday']));
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await pumpFrames(tester);

    expect(find.byKey(const Key('discovery.daily')), findsNothing);
    expect(find.text('完善资料后就能开始滑卡'), findsOneWidget);
    // 区块不渲染 → 精选那一次请求都不该发出去
    expect(adapter.log.where((options) => options.path == '/discovery/daily'), isEmpty);
  });
}
