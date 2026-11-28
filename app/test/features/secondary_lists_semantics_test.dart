import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/chat/search_page.dart';
import 'package:chatapp_app/features/notifications/notifications_page.dart';
import 'package:chatapp_app/features/square/post_likes_page.dart';
import 'package:chatapp_app/im/im_client.dart';

import '../support/fake_im_client.dart';
import '../support/harness.dart';
import '../support/sample_data.dart';
import '../support/scripted_adapter.dart';

/// 二级页·列表组 Semantics 断言(E-5.6d / issue #509 验收第 3 条)。
///
/// 三条播报口径(规范 §8.4「读屏播报」+ page spec §6 第 3 条):
/// 1. 列表项读「标题,摘要,时间」—— 通知行是「正文,时间」,点赞行是「昵称,时间」,
///    搜索命中是「会话名,片段,时间」;
/// 2. 空态读「标题,说明」([EmberEmpty] 自己播报);
/// 3. 顶栏返回键读「返回」([EmberPageScaffold] 给)。
///
/// 为什么按 `find.bySemanticsLabel` 判而不截图:金图只能证明「看起来对」,
/// 读屏能不能念出来只有语义树知道(§8.4「颜色不是唯一线索」)。
void main() {
  const loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

  ScriptedAdapter base() => ScriptedAdapter({
        'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
        'GET /users/me': (options) => ok(profileJson(nickname: '小明')),
        'GET /presence': (options) => ok({'results': []}),
      });

  testWidgets('通知行读「正文,时间」,返回键读「返回」', (tester) async {
    final handle = tester.ensureSemantics();
    final adapter = base()
      ..routes['GET /notifications'] = (options) => ok(cursorPageJson([
            notificationJson(
              id: 3,
              text: '小红 赞了你的动态',
              targetKind: 'post',
              targetId: 9,
            ),
          ]));
    await pumpPage(tester, adapter, const NotificationsPage(), prefs: loggedIn);
    await pumpFrames(tester);

    expect(
      find.bySemanticsLabel(RegExp(r'^小红 赞了你的动态，.+$')),
      findsOneWidget,
    );
    // 返回键:图标按钮必须带读屏标签(§8.4)。
    expect(find.bySemanticsLabel('返回'), findsOneWidget);
    handle.dispose();
  });

  testWidgets('通知空态读「标题,说明」', (tester) async {
    final handle = tester.ensureSemantics();
    final adapter = base()
      ..routes['GET /notifications'] = (options) => ok(cursorPageJson([]));
    await pumpPage(tester, adapter, const NotificationsPage(), prefs: loggedIn);
    await pumpFrames(tester);

    expect(
      find.bySemanticsLabel(RegExp('还没有通知，有人赞你')),
      findsOneWidget,
    );
    handle.dispose();
  });

  testWidgets('点赞行读「昵称,时间」', (tester) async {
    final handle = tester.ensureSemantics();
    final adapter = base()
      ..routes['GET /posts/1/likes'] = (options) => ok(cursorPageJson([
            postLikerJson(userId: 8, nickname: '小雨8'),
          ]));
    await pumpPage(tester, adapter, const PostLikesPage(postId: 1),
        prefs: loggedIn);
    await pumpFrames(tester);

    expect(find.bySemanticsLabel(RegExp(r'^小雨8，.+$')), findsOneWidget);
    handle.dispose();
  });

  testWidgets('点赞空态读「标题,说明」', (tester) async {
    final handle = tester.ensureSemantics();
    final adapter = base()
      ..routes['GET /posts/1/likes'] = (options) => ok(cursorPageJson([]));
    await pumpPage(tester, adapter, const PostLikesPage(postId: 1),
        prefs: loggedIn);
    await pumpFrames(tester);

    expect(
      find.bySemanticsLabel(RegExp('还没有人点赞，第一个喜欢的人')),
      findsOneWidget,
    );
    handle.dispose();
  });

  testWidgets('搜索命中读「会话名,片段,时间」', (tester) async {
    final handle = tester.ensureSemantics();
    final fake = FakeImClient()
      ..searchHits = [
        ImSearchHit(
          msgId: '42',
          seq: 7,
          peerId: 'u9',
          text: '晚上吃火锅吗',
          timestamp: DateTime(2026, 11, 10, 21, 12).millisecondsSinceEpoch,
          peerName: '阿九',
        ),
      ];
    await pumpPage(tester, base(), const SearchPage(),
        prefs: loggedIn, imClient: fake);
    await pumpFrames(tester);
    await tester.enterText(find.byKey(const Key('search.input')), '火锅');
    await tester.pump(const Duration(milliseconds: 350)); // 过防抖
    await pumpFrames(tester);

    expect(
      find.bySemanticsLabel(RegExp(r'^阿九，晚上吃火锅吗，.+$')),
      findsOneWidget,
    );
    handle.dispose();
  });
}
