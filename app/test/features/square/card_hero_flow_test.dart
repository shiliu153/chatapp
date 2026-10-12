import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/card_hero.dart';
import 'package:chatapp_app/features/square/post_detail_page.dart';
import 'package:chatapp_app/features/square/widgets/post_card.dart';
import 'package:chatapp_app/features/square/widgets/post_detail_skeleton.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

ScriptedAdapter _adapter() => ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /posts': (options) => ok(pageJson([
            postJson(id: 1, authorId: 9, nickname: 'Alice', text: '正文甲'),
            postJson(id: 2, authorId: 9, nickname: 'Alice', text: '正文乙'),
          ])),
      'GET /posts/1': (options) =>
          ok(postJson(id: 1, authorId: 9, nickname: 'Alice', text: '正文甲')),
      'GET /posts/1/comments': (options) => ok(pageJson([])),
      'GET /presence': (options) => ok({'results': []}),
    });

/// 读被盖住的列表页里某条动态的卡参数(默认 finder 跳过 offstage,这里必须显式打开)。
PostCard _card(WidgetTester tester, int postId) => tester
    .widgetList<PostCard>(find.byType(PostCard, skipOffstage: false))
    .firstWhere((card) => card.post.id == postId);

/// 全树(含被盖页)里带 tag 的整卡 Hero。
Iterable<CardHero> _taggedCardHeroes(WidgetTester tester) => tester
    .widgetList<CardHero>(find.byType(CardHero, skipOffstage: false))
    .where((hero) => hero.tag != null);

void main() {
  testWidgets('点卡:seed 首帧直出真卡(非骨架),详情顶卡带整卡 tag', (tester) async {
    final adapter = _adapter();
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('广场'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('post.card.1')));
    await tester.pump(); // push 第一帧:provider 仍 loading

    // seed 直出:正文可见、没有骨架(Hero 只扫一次,目标首帧必须已有真卡)
    expect(find.text('正文甲'), findsWidgets);
    expect(find.byType(PostDetailSkeleton), findsNothing);

    await tester.pumpAndSettle();
    expect(find.byType(PostDetailPage), findsOneWidget);
    // 详情页顶卡带整卡 tag(被盖的列表页也有一份同 tag,限定详情页内查)
    final detailTags = tester
        .widgetList<CardHero>(find.descendant(
            of: find.byType(PostDetailPage), matching: find.byType(CardHero)))
        .map((hero) => hero.tag);
    expect(detailTags, contains('card-post-1'));
    expect(tester.takeException(), isNull); // Hero 嵌套断言不崩
  });

  testWidgets('互斥:飞行中的卡切整卡态(头像让位),其余卡不受影响', (tester) async {
    final adapter = _adapter();
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('广场'));
    await tester.pumpAndSettle();

    // 飞行前:两张卡都是头像 Hero 态
    expect(_card(tester, 1).heroTag, 'avatar-post-1');
    expect(_card(tester, 1).cardHeroTag, isNull);
    expect(_card(tester, 2).heroTag, 'avatar-post-2');

    await tester.tap(find.byKey(const Key('post.card.1')));
    await tester.pump(); // 飞行首帧

    // 飞行中:卡 1 让位给整卡 Hero;卡 2 原样(每张卡任意时刻至多一个 Hero)
    expect(_card(tester, 1).heroTag, isNull);
    expect(_card(tester, 1).cardHeroTag, 'card-post-1');
    expect(_card(tester, 2).heroTag, 'avatar-post-2');
    expect(_card(tester, 2).cardHeroTag, isNull);

    await tester.pumpAndSettle();
  });

  testWidgets('返回后:列表卡还原头像 Hero 态,整卡 tag 卸下', (tester) async {
    final adapter = _adapter();
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('广场'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('post.card.1')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('post.back')));
    await tester.pumpAndSettle();

    expect(find.byType(PostDetailPage), findsNothing);
    expect(_card(tester, 1).heroTag, 'avatar-post-1');
    expect(_card(tester, 1).cardHeroTag, isNull);
    expect(_taggedCardHeroes(tester), isEmpty);
  });

  testWidgets('我的动态进详情:无 extra → 两端都不带整卡 tag', (tester) async {
    final adapter = _adapter();
    adapter.routes['GET /posts/mine'] =
        (options) => ok(pageJson([postJson(id: 7, authorId: 7, text: '我的')]));
    adapter.routes['GET /posts/7'] =
        (options) => ok(postJson(id: 7, authorId: 7, text: '我的'));
    adapter.routes['GET /posts/7/comments'] = (options) => ok(pageJson([]));
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('my.row.posts')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('post.card.7')));
    await tester.pumpAndSettle();

    expect(find.byType(PostDetailPage), findsOneWidget);
    // 无飞行源:全树都没有带 tag 的整卡 Hero(PostCard 内部的 null 包装不算)
    expect(_taggedCardHeroes(tester), isEmpty);
    // 详情页骨架期已过,正文直出
    expect(find.text('我的'), findsWidgets);
  });
}
