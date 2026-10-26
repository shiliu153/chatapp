import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/im/im_client.dart';

import '../../support/fake_im_client.dart';
import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 3};

ScriptedAdapter _adapter() => ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'POST /im/user_sig': (options) => ok({
            'user_sig': 'sig',
            'sdkappid': '1600161711',
            'im_user_id': 'u3',
            'expire': 604800,
          }),
      'GET /matches': (options) => ok(pageJson([])),
      'GET /presence': (options) => ok({'results': []}),
    });

void main() {
  late FakeImClient fake;

  Future<void> pumpSearch(WidgetTester tester) async {
    fake = await pumpApp(tester, _adapter(), prefs: _loggedIn);
    await tester.pumpAndSettle();
    await tester.tap(navTab('消息'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('chats.search')));
    await tester.pumpAndSettle();
  }

  testWidgets('消息页有搜索入口,点击进入搜索页', (tester) async {
    await pumpSearch(tester);
    expect(find.byKey(const Key('search.input')), findsOneWidget);
    expect(find.text('搜索聊天记录'), findsWidgets); // 标题 + 输入框 hint
  });

  testWidgets('输入关键词后展示命中并高亮', (tester) async {
    await pumpSearch(tester);
    fake.searchHits = [
      ImSearchHit(
        msgId: '42',
        seq: 7,
        peerId: 'u9',
        text: '晚上吃火锅吗',
        timestamp: DateTime.now().millisecondsSinceEpoch,
        peerName: '阿九',
      ),
    ];
    await tester.enterText(find.byKey(const Key('search.input')), '火锅');
    await tester.pump(const Duration(milliseconds: 350)); // 过防抖
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('search.hit:42')), findsOneWidget);
    expect(find.text('阿九'), findsOneWidget);
    expect(find.textContaining('火锅'), findsWidgets);
    expect(fake.log, contains('search:火锅'));
  });

  testWidgets('无命中显示空态', (tester) async {
    await pumpSearch(tester);
    fake.searchHits = const [];
    await tester.enterText(find.byKey(const Key('search.input')), '不存在');
    await tester.pump(const Duration(milliseconds: 350));
    await tester.pumpAndSettle();

    expect(find.text('没有找到相关消息'), findsOneWidget);
  });

  testWidgets('搜索失败显示错误态,可重试', (tester) async {
    await pumpSearch(tester);
    fake.searchError = const ImException(50001, '内部错误');
    await tester.enterText(find.byKey(const Key('search.input')), '火锅');
    await tester.pump(const Duration(milliseconds: 350));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('search.retry')), findsOneWidget);

    fake.searchError = null;
    fake.searchHits = [
      ImSearchHit(
        msgId: '42',
        seq: 7,
        peerId: 'u9',
        text: '晚上吃火锅吗',
        timestamp: DateTime.now().millisecondsSinceEpoch,
      ),
    ];
    await tester.tap(find.byKey(const Key('search.retry')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('search.hit:42')), findsOneWidget);
  });

  testWidgets('has_more 时显示加载更多并翻页', (tester) async {
    await pumpSearch(tester);
    fake.searchHandler = (keyword, limit, beforeId) {
      if (beforeId == null) {
        return ImSearchResult(
          items: List.generate(
            20,
            (i) => ImSearchHit(
              msgId: 'm$i',
              seq: i,
              peerId: 'u9',
              text: '$keyword-$i',
              timestamp: DateTime.now().millisecondsSinceEpoch,
            ),
          ),
          hasMore: true,
        );
      }
      return ImSearchResult(
        items: [
          ImSearchHit(
            msgId: 'old',
            seq: 0,
            peerId: 'u9',
            text: '$keyword-更早',
            timestamp: DateTime.now().millisecondsSinceEpoch,
          ),
        ],
        hasMore: false,
      );
    };
    await tester.enterText(find.byKey(const Key('search.input')), '火锅');
    await tester.pump(const Duration(milliseconds: 350));
    await tester.pumpAndSettle();
    // 调试:确认第一页渲染出来了
    expect(find.textContaining('火锅-0'), findsOneWidget);
    expect(find.byKey(const Key('search.more')), findsOneWidget);

    await tester.tap(find.byKey(const Key('search.more')));
    await tester.pumpAndSettle();
    // 第二页请求已发出,且 hasMore=false 后按钮消失
    expect(fake.log.where((e) => e.startsWith('search')).length, 2);
    expect(find.byKey(const Key('search.more')), findsNothing);
    expect(find.byKey(const Key('search.more')), findsNothing);
  });

  testWidgets('点结果带 focus 跳聊天页', (tester) async {
    await pumpSearch(tester);
    fake.searchHits = [
      ImSearchHit(
        msgId: '42',
        seq: 7,
        peerId: 'u9',
        text: '晚上吃火锅吗',
        timestamp: DateTime.now().millisecondsSinceEpoch,
      ),
    ];
    fake.history['u9'] = [
      ChatMessage(
        msgId: '42',
        seq: 7,
        peerId: 'u9',
        isSelf: false,
        timestamp: DateTime.now().millisecondsSinceEpoch,
        kind: ChatMessageKind.text,
        text: '晚上吃火锅吗',
      ),
    ];
    await tester.enterText(find.byKey(const Key('search.input')), '火锅');
    await tester.pump(const Duration(milliseconds: 350));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('search.hit:42')));
    // 聊天页含呼吸点动画,不能 pumpAndSettle;逐帧推进直到高亮出现(定位完成)
    var highlighted = false;
    for (var i = 0; i < 60; i++) {
      await tester.pump(const Duration(milliseconds: 100));
      if (find.byKey(const Key('chat.highlight:42')).evaluate().isNotEmpty) {
        highlighted = true;
        break;
      }
    }
    expect(highlighted, isTrue);
    // 再泵 2s 让 1.5s 高亮 Timer 跑完,避免 testWidgets 因 pending timer 失败
    for (var i = 0; i < 25; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
  });
}
