import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/presence/online_dot.dart';
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
      'GET /matches': (options) => ok(pageJson([matchJson(userId: 9, nickname: '小红')])),
      'GET /presence': (options) => ok({'results': []}),
    });

ImConversation _conversation({int unread = 2, String text = '在吗'}) => ImConversation(
      peerId: 'u9',
      unreadCount: unread,
      lastMessage: ChatMessage(
        msgId: 'm1',
        peerId: 'u9',
        isSelf: false,
        timestamp: DateTime.now().millisecondsSinceEpoch,
        kind: ChatMessageKind.text,
        text: text,
      ),
    );

ImConversation _systemConversation({int unread = 1}) => ImConversation(
      peerId: 'system_notice',
      unreadCount: unread,
      lastMessage: ChatMessage(
        msgId: 's1',
        peerId: 'system_notice',
        isSelf: false,
        timestamp: DateTime.now().millisecondsSinceEpoch,
        kind: ChatMessageKind.banNotice,
        text: '您的账号因「发布违规内容」被限制。',
      ),
    );

void main() {
  testWidgets('消息页:昵称来自 matches 缓存,预览和未读都在', (tester) async {
    final fake = FakeImClient()..conversations = [_conversation()];
    await pumpApp(tester, _adapter(), prefs: _loggedIn, imClient: fake);
    await tester.pumpAndSettle();
    await tester.tap(navTab('消息'));
    await tester.pumpAndSettle();

    expect(find.text('小红'), findsNWidgets(2)); // 横滑条 + 列表行
    expect(find.text('在吗'), findsOneWidget);
    // 列表行角标一个、底部 Tab 一个(未读总数),共两个 '2'
    expect(find.text('2'), findsNWidgets(2));
  });

  testWidgets('没有会话 → 空态,无横滑条', (tester) async {
    final fake = FakeImClient();
    await pumpApp(tester, _adapter(), prefs: _loggedIn, imClient: fake);
    await tester.pumpAndSettle();
    await tester.tap(navTab('消息'));
    await tester.pumpAndSettle();

    expect(find.text('还没有消息'), findsOneWidget);
    expect(find.byKey(const Key('chats.strip')), findsNothing);
  });

  testWidgets('IM 登录失败 → 显示原因 + 重试按钮', (tester) async {
    final fake = FakeImClient()..loginError = const ImException(6001, 'boom');
    await pumpApp(tester, _adapter(), prefs: _loggedIn, imClient: fake);
    await tester.pumpAndSettle();
    await tester.tap(navTab('消息'));
    await tester.pumpAndSettle();

    expect(find.textContaining('6001'), findsOneWidget);
    expect(find.byKey(const Key('chats.retry')), findsOneWidget);
  });

  testWidgets('系统通知:置顶在会话列表之上 + 官方标', (tester) async {
    final fake = FakeImClient()..conversations = [_conversation(), _systemConversation()];
    await pumpApp(tester, _adapter(), prefs: _loggedIn, imClient: fake);
    await tester.pumpAndSettle();
    await tester.tap(navTab('消息'));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('chats.systemNotice')), findsOneWidget);
    expect(find.text('系统通知'), findsOneWidget);
    expect(find.text('官方'), findsOneWidget);
    final systemY = tester.getTopLeft(find.byKey(const Key('chats.systemNotice'))).dy;
    final friendY = tester.getTopLeft(find.byKey(const Key('chats.tile:u9'))).dy;
    expect(systemY, lessThan(friendY));
  });

  testWidgets('点列表行 → 进聊天页', (tester) async {
    final fake = FakeImClient()
      ..conversations = [_conversation()]
      ..history = {
        'u9': [
          ChatMessage(
            msgId: 'm1',
            peerId: 'u9',
            isSelf: false,
            timestamp: DateTime.now().millisecondsSinceEpoch,
            kind: ChatMessageKind.text,
            text: '你好呀',
          ),
        ],
      };
    await pumpApp(tester, _adapter(), prefs: _loggedIn, imClient: fake);
    await tester.pumpAndSettle();
    await tester.tap(navTab('消息'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('chats.tile:u9')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('chat.input')), findsOneWidget);
    expect(find.text('你好呀'), findsOneWidget); // 历史里的那条
  });

  testWidgets('点横滑条头像 → 直达聊天页', (tester) async {
    final fake = FakeImClient()..conversations = [_conversation()];
    await pumpApp(tester, _adapter(), prefs: _loggedIn, imClient: fake);
    await tester.pumpAndSettle();
    await tester.tap(navTab('消息'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('chats.stripItem:u9')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('chat.input')), findsOneWidget);
  });

  testWidgets('在线的人头像带绿点;离线与系统通知没有', (tester) async {
    final fake = FakeImClient()..conversations = [_conversation(), _systemConversation()];
    final adapter = _adapter();
    adapter.routes['GET /presence'] = (options) => ok({
          'results': [
            {'user_id': 9, 'online': true, 'last_active_at': '2026-09-13T14:30:00+08:00'},
          ],
        });
    await pumpApp(tester, adapter, prefs: _loggedIn, imClient: fake);
    await tester.pumpAndSettle();
    await tester.tap(navTab('消息'));
    await tester.pumpAndSettle();

    // 横滑条 + 列表行各一个绿点;系统通知(非真人)没有
    expect(find.byType(OnlineDot), findsNWidgets(2));
  });

  testWidgets('离线不显示绿点', (tester) async {
    final fake = FakeImClient()..conversations = [_conversation()];
    final adapter = _adapter();   // 默认 'GET /presence' 返回空
    await pumpApp(tester, adapter, prefs: _loggedIn, imClient: fake);
    await tester.pumpAndSettle();
    await tester.tap(navTab('消息'));
    await tester.pumpAndSettle();

    expect(find.byType(OnlineDot), findsNothing);
  });
}
