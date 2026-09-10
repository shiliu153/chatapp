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
      'GET /matches': (options) => ok([matchJson(userId: 9, nickname: '小红')]),
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

void main() {
  testWidgets('会话列表:昵称来自 matches 缓存,预览和未读都在', (tester) async {
    final fake = FakeImClient()..conversations = [_conversation()];
    await pumpApp(tester, _adapter(), prefs: _loggedIn, imClient: fake);
    await tester.pumpAndSettle();
    await tester.tap(navTab('会话'));
    await tester.pumpAndSettle();

    expect(find.text('小红'), findsOneWidget);
    expect(find.text('在吗'), findsOneWidget);
    // 列表项一个、底部 Tab 一个(未读总数),共两个 '2'
    expect(find.text('2'), findsNWidgets(2));
  });

  testWidgets('没有会话 → 空态', (tester) async {
    final fake = FakeImClient();
    await pumpApp(tester, _adapter(), prefs: _loggedIn, imClient: fake);
    await tester.pumpAndSettle();
    await tester.tap(navTab('会话'));
    await tester.pumpAndSettle();

    expect(find.text('还没有会话'), findsOneWidget);
  });

  testWidgets('IM 登录失败 → 显示原因 + 重试按钮', (tester) async {
    final fake = FakeImClient()..loginError = const ImException(6001, 'boom');
    await pumpApp(tester, _adapter(), prefs: _loggedIn, imClient: fake);
    await tester.pumpAndSettle();
    await tester.tap(navTab('会话'));
    await tester.pumpAndSettle();

    expect(find.textContaining('6001'), findsOneWidget);
    expect(find.byKey(const Key('chats.retry')), findsOneWidget);
  });
}
