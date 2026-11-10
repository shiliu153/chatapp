import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/discovery/models.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

/// 批次 S:发现页临时筛选。
///
/// 三条口径贯穿全部用例:
/// 1. 面板默认值 = 「想找的人」偏好;
/// 2. 筛选参数是**覆盖**不是替换 —— 没动过的字段一个都不发;
/// 3. 筛选态只活在同一次 App 生命周期里,不写回偏好。
const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

/// 基线偏好:22–30 岁、北京。筛选用例都从它出发,验证「覆盖」。
const _preference = {
  'target_gender': 'female',
  'age_min': 22,
  'age_max': 30,
  'city': '北京',
};

ScriptedAdapter _adapter({List<Map<String, dynamic>>? candidates}) => ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(preference: _preference)),
      'GET /users/tags': (options) => ok([tagJson(1, '旅行'), tagJson(2, '读书')]),
      'GET /discovery/candidates': (options) => ok(candidates ?? [candidateJson(userId: 9)]),
      // 今日精选铺空数组:区块整块不渲染,筛选用例只关心候选池请求。
      // 也刻意**不**铺 GET /posts:广场空态的 HeartRipple 会让未选中的 Tab
      // 一直跑动画(IndexedStack),pumpAndSettle 直接超时(见 docs/pitfalls/testing.md)
      'GET /discovery/daily': (options) => ok(dailyJson()),
      'POST /discovery/swipe': (options) => ok({'matched': false}),
    });

/// 候选池请求(按发生顺序),用来断言 query 参数。
List<RequestOptions> _candidateRequests(ScriptedAdapter adapter) => adapter.log
    .where((options) => options.path == '/discovery/candidates')
    .toList();

Future<void> _openSheet(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('discovery.filter')));
  await tester.pumpAndSettle();
}

void main() {
  group('DiscoveryFilter 查询参数', () {
    test('空筛选:一个参数都不出现(不是发空串)', () {
      expect(DiscoveryFilter.none.toQuery(), isEmpty);
      expect(DiscoveryFilter.none.isEmpty, isTrue);
      expect(const DiscoveryFilter(city: '').toQuery(), isEmpty);
    });

    test('只改城市:不夹带年龄与标签(覆盖语义)', () {
      const filter = DiscoveryFilter(city: '杭州');
      expect(filter.toQuery(), {'city': '杭州'});
      expect(filter.isEmpty, isFalse);
    });

    test('标签拼成逗号分隔;值为空时整条发', () {
      expect(const DiscoveryFilter(ageMin: 25, ageMax: 30, tagIds: [1, 2]).toQuery(),
          {'age_min': 25, 'age_max': 30, 'tag_ids': '1,2'});
    });
  });

  testWidgets('筛选面板默认值来自「想找的人」偏好,未改动时请求不带筛选参数', (tester) async {
    final adapter = _adapter();
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await _openSheet(tester);

    expect(find.text('筛选'), findsWidgets);
    expect(find.text('年龄 22 – 30 岁'), findsOneWidget);
    final city = tester.widget<TextField>(find.descendant(
        of: find.byKey(const Key('filter.city')), matching: find.byType(TextField)));
    expect(city.controller!.text, '北京');

    // 没改任何东西 → 关掉面板后候选池请求仍是老样子
    await tester.tapAt(const Offset(400, 20)); // 点面板外的遮罩关掉
    await tester.pumpAndSettle();
    expect(_candidateRequests(adapter).last.queryParameters, {'limit': 10});
  });

  testWidgets('只填城市 + 选标签 → 请求只带 city 与 tag_ids,年龄继续沿用偏好', (tester) async {
    final adapter = _adapter();
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await _openSheet(tester);
    await tester.enterText(find.byKey(const Key('filter.city')), '杭州');
    await tester.tap(find.text('旅行'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('filter.apply')));
    await tester.pumpAndSettle();

    final query = _candidateRequests(adapter).last.queryParameters;
    expect(query['city'], '杭州');
    expect(query['tag_ids'], '1');
    // 年龄滑块没动过 → 一个参数都不发,后端继续沿用偏好(22–30)
    expect(query.containsKey('age_min'), isFalse);
    expect(query.containsKey('age_max'), isFalse);
  });

  testWidgets('改年龄区间 → 请求带上 age_min/age_max,且与界面显示一致', (tester) async {
    final adapter = _adapter();
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await _openSheet(tester);
    // 拖右滑块:像素 → 数值的换算由 RangeSlider 自己算(按压点决定抓哪个滑块),
    // 所以这里不写死期望值,只断言「确实变了」+「请求参数 == 面板显示的数字」
    final slider = tester.getRect(find.byType(RangeSlider));
    await tester.dragFrom(Offset(slider.right - 24, slider.center.dy), const Offset(-60, 0));
    await tester.pumpAndSettle();

    final title = tester.widget<Text>(find.textContaining('年龄 ')).data!;
    final shownMax = int.parse(RegExp(r'– (\d+) 岁').firstMatch(title)!.group(1)!);
    expect(shownMax, isNot(30), reason: '拖过滑块后上限必须变过,否则 age_min/age_max 不会发');
    expect(shownMax, greaterThan(22));

    await tester.tap(find.byKey(const Key('filter.apply')));
    await tester.pumpAndSettle();

    final query = _candidateRequests(adapter).last.queryParameters;
    expect(query['age_min'], 22);
    expect(query['age_max'], shownMax);
  });

  testWidgets('「重置」→ 请求不带任何筛选参数,面板默认值回到偏好', (tester) async {
    final adapter = _adapter();
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await _openSheet(tester);
    await tester.enterText(find.byKey(const Key('filter.city')), '杭州');
    await tester.tap(find.byKey(const Key('filter.apply')));
    await tester.pumpAndSettle();
    expect(_candidateRequests(adapter).last.queryParameters['city'], '杭州');

    await _openSheet(tester);
    await tester.tap(find.byKey(const Key('filter.reset')));
    await tester.pumpAndSettle();

    expect(_candidateRequests(adapter).last.queryParameters, {'limit': 10});

    // 再打开:默认值回到偏好(城市是北京,不是上一次的杭州)
    await _openSheet(tester);
    final city = tester.widget<TextField>(find.descendant(
        of: find.byKey(const Key('filter.city')), matching: find.byType(TextField)));
    expect(city.controller!.text, '北京');
  });

  testWidgets('筛选后候选池为空 → 空态不崩', (tester) async {
    final adapter = _adapter();
    // 只有带 city 的请求(也就是筛选生效之后)才返回空池
    adapter.routes['GET /discovery/candidates'] = (options) => ok(
        options.queryParameters.containsKey('city')
            ? <Map<String, dynamic>>[]
            : [candidateJson(userId: 9)]);
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    expect(find.text('小红,25'), findsOneWidget);

    await _openSheet(tester);
    await tester.enterText(find.byKey(const Key('filter.city')), '拉萨');
    await tester.tap(find.byKey(const Key('filter.apply')));
    await pumpFrames(tester); // 空态涟漪是无限动画,不能 pumpAndSettle

    expect(find.text('附近暂时没有新的人了'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('页面切走再回来,筛选态不丢', (tester) async {
    final adapter = _adapter();
    // 有筛选时后端给另一个人,好分辨「筛选态还在」还是「悄悄回落到默认池」
    adapter.routes['GET /discovery/candidates'] = (options) =>
        ok(options.queryParameters['city'] == '杭州'
            ? [candidateJson(userId: 11, nickname: '杭州的人')]
            : [candidateJson(userId: 9, nickname: '小红')]);
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await _openSheet(tester);
    await tester.enterText(find.byKey(const Key('filter.city')), '杭州');
    await tester.tap(find.byKey(const Key('filter.apply')));
    await tester.pumpAndSettle();
    expect(find.text('杭州的人,25'), findsOneWidget);
    final before = _candidateRequests(adapter).length;

    await tester.tap(navTab('广场'));
    await pumpFrames(tester);
    await tester.tap(navTab('发现'));
    await pumpFrames(tester);

    // 首页四个 Tab 是 IndexedStack:切回来页面还在,候选池也还是筛过的那一版
    expect(find.text('杭州的人,25'), findsOneWidget);
    // 期间若真的重发了候选池请求,那也必须还带着 city(不能悄悄回落到无筛选)
    expect(
        _candidateRequests(adapter)
            .skip(before)
            .every((options) => options.queryParameters['city'] == '杭州'),
        isTrue);
  });
}
