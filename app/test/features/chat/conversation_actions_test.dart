import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/api_exception.dart';
import 'package:chatapp_app/im/im_client.dart';

import '../../support/fake_im_client.dart';
import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

/// 批次 N 验收:会话行长按菜单(置顶 / 免打扰 / 删除会话)。
///
/// 三个动作都是单方行为:置顶 / 免打扰走 imserver HTTP(不加 WS 帧),
/// 删除走既有的 `deleteConversation`(WS 帧早已存在)。

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 3};

ScriptedAdapter _adapter() => ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'POST /im/user_sig': (options) => ok({
            'backend': 'self',
            'token': 'tok',
            'ws_url': 'ws://test/im/ws',
            'http_url': 'http://test/im/api',
            'im_user_id': 'u3',
            'expire': 86400,
          }),
      'GET /matches': (options) => ok(pageJson([
            matchJson(userId: 9, nickname: '小红'),
            matchJson(userId: 8, nickname: '小绿'),
          ])),
      'GET /presence': (options) => ok({'results': []}),
    });

ImConversation _conversation(String peerId, {int unread = 2, bool pinned = false, bool muted = false}) =>
    ImConversation(
      peerId: peerId,
      unreadCount: unread,
      showName: peerId == 'u9' ? '小红' : '小绿',
      pinned: pinned,
      muted: muted,
      lastMessage: ChatMessage(
        msgId: 'm-$peerId',
        peerId: peerId,
        isSelf: false,
        timestamp: DateTime.now().millisecondsSinceEpoch,
        kind: ChatMessageKind.text,
        text: '在吗',
      ),
    );

/// 起 App → 切到消息 Tab。
Future<void> _openChats(WidgetTester tester, FakeImClient fake) async {
  await pumpApp(tester, _adapter(), prefs: _loggedIn, imClient: fake);
  await tester.pumpAndSettle();
  await tester.tap(navTab('消息'));
  await tester.pumpAndSettle();
}

/// 长按某个会话行、等面板弹出。
Future<void> _longPressRow(WidgetTester tester, String peerId) async {
  await tester.longPress(find.byKey(Key('chats.tile:$peerId')));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('长按会话行 → 操作面板三项(置顶 / 免打扰 / 删除会话)', (tester) async {
    final fake = FakeImClient()..conversations = [_conversation('u9')];
    await _openChats(tester, fake);
    await _longPressRow(tester, 'u9');

    expect(find.byKey(const Key('actionSheet.pin')), findsOneWidget);
    expect(find.byKey(const Key('actionSheet.mute')), findsOneWidget);
    expect(find.byKey(const Key('actionSheet.delete')), findsOneWidget);
    expect(find.text('置顶'), findsOneWidget);
    expect(find.text('免打扰'), findsOneWidget);
    expect(find.text('删除会话'), findsOneWidget);
  });

  testWidgets('已置顶 / 已免打扰的行,面板文案变成「取消…」', (tester) async {
    final fake = FakeImClient()
      ..conversations = [_conversation('u9', pinned: true, muted: true)];
    await _openChats(tester, fake);
    await _longPressRow(tester, 'u9');

    expect(find.text('取消置顶'), findsOneWidget);
    expect(find.text('取消免打扰'), findsOneWidget);
  });

  testWidgets('点「置顶」→ 只上行 pinned,会话进「置顶」分组且排最前', (tester) async {
    // 服务端顺序:u8 在前、u9 在后;置顶 u9 后由服务端把它排到最前(Fake 近似同样排序)。
    final fake = FakeImClient()..conversations = [_conversation('u8'), _conversation('u9')];
    await _openChats(tester, fake);
    expect(find.byKey(const Key('chats.groupHeader.pinned')), findsNothing);

    await _longPressRow(tester, 'u9');
    await tester.tap(find.byKey(const Key('actionSheet.pin')));
    await tester.pumpAndSettle();

    // 只传 pinned(true),muted 必须缺省(不能顺带写成 false)
    expect(fake.log, contains('setFlags:u9:pinned=true:muted=-'));
    expect(find.text('已置顶'), findsOneWidget);
    // 分组标题出现,且在 u9 行之上
    final header = find.byKey(const Key('chats.groupHeader.pinned'));
    expect(header, findsOneWidget);
    expect(tester.getTopLeft(header).dy,
        lessThan(tester.getTopLeft(find.byKey(const Key('chats.tile:u9'))).dy));
    expect(tester.getTopLeft(find.byKey(const Key('chats.tile:u9'))).dy,
        lessThan(tester.getTopLeft(find.byKey(const Key('chats.tile:u8'))).dy));

    await drainToast(tester);
  });

  testWidgets('点「免打扰」→ 只上行 muted,显示静音图标,未读只给灰点不给数字', (tester) async {
    final fake = FakeImClient()..conversations = [_conversation('u9', unread: 2)];
    await _openChats(tester, fake);
    // 行角标 + 底栏未读总数,两个 '2'
    expect(find.text('2'), findsNWidgets(2));

    await _longPressRow(tester, 'u9');
    await tester.tap(find.byKey(const Key('actionSheet.mute')));
    await tester.pumpAndSettle();

    expect(fake.log, contains('setFlags:u9:pinned=-:muted=true'));
    expect(find.byKey(const Key('chats.muted:u9')), findsOneWidget);
    expect(find.byKey(const Key('chats.mutedDot:u9')), findsOneWidget);
    // 会话行不再显示数字,只剩底栏那个未读总数
    expect(find.text('2'), findsOneWidget);

    await drainToast(tester);
  });

  testWidgets('服务端已置顶的会话:进列表第一组(客户端不自己排序)', (tester) async {
    final fake = FakeImClient()
      ..conversations = [
        _conversation('u9', pinned: true),
        _conversation('u8'),
      ];
    await _openChats(tester, fake);

    final header = find.byKey(const Key('chats.groupHeader.pinned'));
    expect(header, findsOneWidget);
    expect(tester.getTopLeft(header).dy,
        lessThan(tester.getTopLeft(find.byKey(const Key('chats.tile:u9'))).dy));
  });

  testWidgets('点「删除会话」→ 二次确认 → 行消失 + 提示', (tester) async {
    final fake = FakeImClient()..conversations = [_conversation('u9')];
    await _openChats(tester, fake);

    await _longPressRow(tester, 'u9');
    await tester.tap(find.byKey(const Key('actionSheet.delete')));
    await tester.pumpAndSettle();
    expect(find.text('删除该会话?'), findsOneWidget);
    // 还没确认,什么都没发生
    expect(fake.log.where((line) => line.startsWith('deleteConversation')).length, 0);

    await tester.tap(find.byKey(const Key('chats.delete.confirm')));
    await tester.pumpAndSettle();

    expect(fake.log, contains('deleteConversation:u9'));
    expect(find.byKey(const Key('chats.tile:u9')), findsNothing);
    expect(find.text('会话已删除'), findsOneWidget);

    await drainToast(tester);
  });

  testWidgets('删除确认框点「取消」→ 行还在', (tester) async {
    final fake = FakeImClient()..conversations = [_conversation('u9')];
    await _openChats(tester, fake);

    await _longPressRow(tester, 'u9');
    await tester.tap(find.byKey(const Key('actionSheet.delete')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();

    expect(fake.log.where((line) => line.startsWith('deleteConversation')).length, 0);
    expect(find.byKey(const Key('chats.tile:u9')), findsOneWidget);
  });

  testWidgets('会话已不存在(40401)→ 提示「该会话已不存在」并刷新列表', (tester) async {
    final fake = FakeImClient()..conversations = [_conversation('u9')];
    await _openChats(tester, fake);
    fake.flagsError = const ImException(40401, '会话不存在');
    final fetchesBefore = fake.log.where((line) => line == 'fetchConversations').length;

    await _longPressRow(tester, 'u9');
    await tester.tap(find.byKey(const Key('actionSheet.pin')));
    await tester.pumpAndSettle();

    expect(find.text('该会话已不存在'), findsOneWidget);
    // 刷新了一次列表(把已删除的会话拉掉)
    expect(fake.log.where((line) => line == 'fetchConversations').length, fetchesBefore + 1);

    await drainToast(tester);
  });

  testWidgets('限流(42901)→ 提示太频繁', (tester) async {
    final fake = FakeImClient()..conversations = [_conversation('u9')];
    await _openChats(tester, fake);
    fake.flagsError = ApiException('操作过于频繁', statusCode: 429, code: 42901);

    await _longPressRow(tester, 'u9');
    await tester.tap(find.byKey(const Key('actionSheet.pin')));
    await tester.pumpAndSettle();

    expect(find.text('操作太频繁了,歇一下再试'), findsOneWidget);

    await drainToast(tester);
  });

  testWidgets('写失败 → 保留原状态(不假装置顶成功)', (tester) async {
    final fake = FakeImClient()..conversations = [_conversation('u9')];
    await _openChats(tester, fake);
    fake.flagsError = const ImException(50001, '内部错误');

    await _longPressRow(tester, 'u9');
    await tester.tap(find.byKey(const Key('actionSheet.pin')));
    await tester.pumpAndSettle();

    expect(find.text('内部错误'), findsOneWidget);
    // 没有置顶分组、也没有「已置顶」提示;列表没被写成置顶态
    expect(find.byKey(const Key('chats.groupHeader.pinned')), findsNothing);
    expect(find.text('已置顶'), findsNothing);

    await drainToast(tester);
  });
}
