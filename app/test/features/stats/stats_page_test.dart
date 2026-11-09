import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/heart_colors.dart';
import 'package:chatapp_app/features/stats/stats_page.dart';

import '../../support/harness.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

/// 一周的报告响应(与 `docs/api/stats.md` §1.1 的示例同位)。
Map<String, Object> statsJson({
  String period = 'week',
  String start = '2026-11-09',
  String end = '2026-11-15',
  int matches = 2,
  int likesGiven = 14,
  int likesReceived = 9,
  int visits = 6,
  int posts = 3,
  int postLikes = 11,
  int newFollowers = 1,
}) =>
    {
      'period': period,
      'start': start,
      'end': end,
      'matches': matches,
      'likes_given': likesGiven,
      'likes_received': likesReceived,
      'visits': visits,
      'posts': posts,
      'post_likes': postLikes,
      'new_followers': newFollowers,
    };

/// 按 `period` 回不同区间的假后端:切周期要能看到区间标签跟着变。
ScriptedAdapter _adapter() => ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /stats/me': (options) {
        final period = options.queryParameters['period'] as String? ?? 'week';
        return switch (period) {
          'month' => ok(statsJson(
              period: 'month',
              start: '2026-11-01',
              end: '2026-11-30',
              matches: 8,
            )),
          'year' => ok(statsJson(
              period: 'year',
              start: '2026-01-01',
              end: '2026-12-31',
              matches: 42,
            )),
          _ => ok(statsJson()),
        };
      },
    });

/// 请求过的周期序列(证明「切换即请求」)。
List<String?> _requestedPeriods(ScriptedAdapter adapter) => adapter.log
    .where((request) => request.path == '/stats/me')
    .map((request) => request.queryParameters['period'] as String?)
    .toList();

void main() {
  testWidgets('默认按周请求:七张数字卡 + 周期区间', (tester) async {
    final adapter = _adapter();
    await pumpPage(tester, adapter, const StatsPage(), prefs: _loggedIn);
    await pumpFrames(tester);

    expect(_requestedPeriods(adapter), ['week']);
    expect(find.text('2026-11-09 ~ 2026-11-15'), findsOneWidget);

    for (final key in [
      'matches',
      'likes_given',
      'likes_received',
      'visits',
      'posts',
      'post_likes',
      'new_followers',
    ]) {
      expect(find.byKey(Key('stats.card.$key')), findsOneWidget,
          reason: '缺少数字卡 $key');
    }
    for (final label in ['新的配对', '喜欢给出', '喜欢收到', '访客', '动态', '动态获赞', '新粉丝']) {
      expect(find.text(label), findsOneWidget, reason: '缺少标签 $label');
    }

    // 数字逐张对得上(0 以外的值)
    expect(find.text('14'), findsOneWidget); // 喜欢给出
    expect(find.text('11'), findsOneWidget); // 动态获赞
  });

  testWidgets('切到月 / 年:各重新请求一次,区间标签跟着变', (tester) async {
    final adapter = _adapter();
    await pumpPage(tester, adapter, const StatsPage(), prefs: _loggedIn);
    await pumpFrames(tester);

    await tester.tap(find.text('月'));
    await pumpFrames(tester);
    expect(_requestedPeriods(adapter), ['week', 'month']);
    expect(find.text('2026-11-01 ~ 2026-11-30'), findsOneWidget);
    expect(find.text('8'), findsOneWidget); // 配对 8

    await tester.tap(find.text('年'));
    await pumpFrames(tester);
    expect(_requestedPeriods(adapter), ['week', 'month', 'year']);
    expect(find.text('2026-01-01 ~ 2026-12-31'), findsOneWidget);
    expect(find.text('42'), findsOneWidget);

    // 再切回周:又发一次请求(报告 provider 按周期重建,不复用旧结果)
    await tester.tap(find.text('周'));
    await pumpFrames(tester);
    expect(_requestedPeriods(adapter), ['week', 'month', 'year', 'week']);
    expect(find.text('2026-11-09 ~ 2026-11-15'), findsOneWidget);
  });

  testWidgets('全是 0 时正常显示 0(不做「—」之类的替换)', (tester) async {
    final adapter = _adapter()
      ..routes['GET /stats/me'] = (options) => ok(statsJson(
            matches: 0,
            likesGiven: 0,
            likesReceived: 0,
            visits: 0,
            posts: 0,
            postLikes: 0,
            newFollowers: 0,
          ));
    await pumpPage(tester, adapter, const StatsPage(), prefs: _loggedIn);
    await pumpFrames(tester);

    expect(find.text('0'), findsNWidgets(7));
    for (final key in ['matches', 'post_likes', 'new_followers']) {
      expect(
        tester.widget<Text>(find.byKey(Key('stats.value.$key'))).data,
        '0',
      );
    }
  });

  testWidgets('加载中先出骨架,拿到数据后换成数字卡', (tester) async {
    final gate = Completer<void>();
    final adapter = _adapter()
      ..routes['GET /stats/me'] = (options) async {
        await gate.future;
        return ok(statsJson());
      };
    await pumpPage(tester, adapter, const StatsPage(), prefs: _loggedIn);
    await pumpFrames(tester, frames: 3);
    expect(find.byKey(const Key('stats.skeleton')), findsOneWidget);
    expect(find.byKey(const Key('stats.card.matches')), findsNothing);

    gate.complete();
    await pumpFrames(tester);
    expect(find.byKey(const Key('stats.skeleton')), findsNothing);
    expect(find.byKey(const Key('stats.card.matches')), findsOneWidget);
  });

  testWidgets('加载失败 → AppErrorView,重试成功后出数字卡', (tester) async {
    final adapter = _adapter()
      ..routes['GET /stats/me'] = (options) => jsonError(500, '服务器开小差了');
    await pumpPage(tester, adapter, const StatsPage(), prefs: _loggedIn);
    await pumpFrames(tester);

    expect(find.byKey(const Key('stats.retry')), findsOneWidget);
    expect(find.text('服务器开小差了'), findsOneWidget); // 只说中文 message,不露异常串
    expect(find.byKey(const Key('stats.card.matches')), findsNothing);

    // 分段控件在失败态下仍在,用户可以直接换周期
    expect(find.text('月'), findsOneWidget);

    adapter.routes['GET /stats/me'] = (options) => ok(statsJson());
    await tester.tap(find.byKey(const Key('stats.retry')));
    await pumpFrames(tester);
    expect(find.byKey(const Key('stats.retry')), findsNothing);
    expect(find.byKey(const Key('stats.card.matches')), findsOneWidget);
  });

  testWidgets('失败态下换周期也会重新请求(按新周期)', (tester) async {
    final adapter = _adapter()
      ..routes['GET /stats/me'] = (options) => jsonError(500, '服务器开小差了');
    await pumpPage(tester, adapter, const StatsPage(), prefs: _loggedIn);
    await pumpFrames(tester);

    adapter.routes['GET /stats/me'] = (options) => ok(statsJson(period: 'month'));
    await tester.tap(find.text('月'));
    await pumpFrames(tester);
    expect(_requestedPeriods(adapter), ['week', 'month']);
    expect(find.byKey(const Key('stats.card.matches')), findsOneWidget);
  });

  testWidgets('暗色:Scaffold 底色是深色 bgPage,数字卡与区间正常渲染', (tester) async {
    final adapter = _adapter();
    await pumpPage(tester, adapter, const StatsPage(),
        prefs: _loggedIn, brightness: Brightness.dark);
    await pumpFrames(tester);

    final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
    expect(scaffold.backgroundColor, HeartColors.dark.bgPage);
    expect(find.text('2026-11-09 ~ 2026-11-15'), findsOneWidget);
    expect(find.byKey(const Key('stats.card.new_followers')), findsOneWidget);
  });
}
