import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/avatar_hero.dart';
import 'package:chatapp_app/features/profile/user_profile_page.dart';
import 'package:chatapp_app/features/square/post_detail_page.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

void main() {
  testWidgets('广场:头像 Hero tag 为 avatar-post-{id};跳资料页后 tag 一致', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /posts': (options) => ok(pageJson([
            postJson(id: 1, authorId: 9, nickname: 'Alice', text: '你好'),
          ])),
      'GET /users/9': (options) => ok(publicProfileJson(userId: 9, nickname: 'Alice')),
      'GET /presence': (options) => ok({'results': []}),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(navTab('广场'));
    await tester.pumpAndSettle();

    // 来源侧:头像被 AvatarHero 包住,tag 用来源自身 id(不是 userId)
    final source = tester.widget<AvatarHero>(find.ancestor(
        of: find.byKey(const Key('post.avatar.1')),
        matching: find.byType(AvatarHero)));
    expect(source.tag, 'avatar-post-1');

    await tester.tap(find.byKey(const Key('post.avatar.1')));
    await tester.pumpAndSettle();

    // 目标侧:同一 tag 落在资料页头图上(限定在目标页内查找——
    // 被 push 盖住的广场页仍在树里,全局 find 会撞到它自己的 AvatarHero)
    expect(find.byType(UserProfilePage), findsOneWidget);
    final target = tester.widget<AvatarHero>(find.descendant(
        of: find.byType(UserProfilePage), matching: find.byType(AvatarHero)));
    expect(target.tag, 'avatar-post-1');
  });

  testWidgets('广场:同作者两条动态 → tag 不重复(否则 Hero 抛重复 tag)', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /posts': (options) => ok(pageJson([
            postJson(id: 1, authorId: 9, nickname: 'Alice', text: '第一条'),
            postJson(id: 2, authorId: 9, nickname: 'Alice', text: '第二条'),
          ])),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(navTab('广场'));
    await tester.pumpAndSettle();

    // 两个 Hero tag 必须不同(用 userId 派生会撞,debug 下直接抛异常)
    final tags = tester
        .widgetList<AvatarHero>(find.byType(AvatarHero))
        .map((hero) => hero.tag)
        .toList();
    expect(tags.length, 2);
    expect(tags.toSet().length, tags.length);
    expect(tester.takeException(), isNull);
  });

  testWidgets('动态详情:作者与评论的头像 tag 各自独立', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /posts': (options) => ok(pageJson([
            postJson(id: 1, authorId: 9, nickname: 'Alice', text: '正文'),
          ])),
      'GET /posts/1': (options) =>
          ok(postJson(id: 1, authorId: 9, nickname: 'Alice', text: '正文')),
      'GET /posts/1/comments': (options) => ok(pageJson([
            commentJson(id: 5, authorId: 11, nickname: 'Bob', text: '好漂亮'),
          ])),
      'GET /presence': (options) => ok({'results': []}),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(navTab('广场'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('post.card.1')));
    await tester.pumpAndSettle();

    // 限定在详情页内:被盖住的广场页仍在树里,全局 find 会连它的一起算进来
    final tags = tester
        .widgetList<AvatarHero>(find.descendant(
            of: find.byType(PostDetailPage), matching: find.byType(AvatarHero)))
        .map((hero) => hero.tag)
        .toSet();
    // 批次⑤整卡 Hero:经广场点卡进详情走「整卡态」,作者头像 Hero 让位
    // (SDK 禁 Hero 嵌套),评论头像 tag 不受影响;返回列表后作者头像 Hero 恢复
    // (互斥还原,见 card_hero_flow_test 的「返回后」用例)。
    // 深链/我的动态进详情(无整卡 Hero)时作者头像 Hero 仍在 —— 见下方用例。
    expect(tags, contains('avatar-comment-5'));
    expect(tags, isNot(contains('avatar-post-1')));
    expect(tester.takeException(), isNull);
  });

  testWidgets('动态详情(无整卡 Hero 来源):作者头像 Hero 仍在', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /posts': (options) => ok(pageJson([])),
      'GET /posts/mine': (options) => ok(pageJson([
            postJson(id: 7, authorId: 9, nickname: 'Alice', text: '正文'),
          ])),
      'GET /posts/7': (options) =>
          ok(postJson(id: 7, authorId: 9, nickname: 'Alice', text: '正文')),
      'GET /posts/7/comments': (options) => ok(pageJson([])),
      'GET /presence': (options) => ok({'results': []}),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await pumpFrames(tester); // 广场空态涟漪在 IndexedStack 隐藏页一直跑,禁 settle

    await tester.tap(navTab('我的'));
    await pumpFrames(tester);
    await tester.tap(find.byKey(const Key('my.row.posts')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('post.card.7')));
    await tester.pumpAndSettle();

    final tags = tester
        .widgetList<AvatarHero>(find.descendant(
            of: find.byType(PostDetailPage), matching: find.byType(AvatarHero)))
        .map((hero) => hero.tag)
        .toSet();
    expect(tags, contains('avatar-post-7'));
    expect(tester.takeException(), isNull);
  });
}
