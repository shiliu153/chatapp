import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:chatapp_app/features/chat/widgets/message_bubble.dart';
import 'package:chatapp_app/im/im_client.dart';

ChatMessage _m({
  bool isSelf = false,
  ChatMessageKind kind = ChatMessageKind.text,
  String text = '你好',
  bool isFailed = false,
  String? localPath,
}) =>
    ChatMessage(
      msgId: 'm1',
      peerId: 'u9',
      isSelf: isSelf,
      timestamp: 1,
      kind: kind,
      text: text,
      isFailed: isFailed,
      localPath: localPath,
    );

Future<void> _pump(WidgetTester tester, Widget child) =>
    tester.pumpWidget(MaterialApp(home: Scaffold(body: child)));

void main() {
  testWidgets('对方气泡:头像首字 + 白色气泡', (tester) async {
    await _pump(tester, MessageBubble(message: _m(), peerName: '小红'));
    expect(find.text('小'), findsOneWidget); // 头像占位
    expect(find.text('你好'), findsOneWidget);
  });

  testWidgets('失败态:出现重发叹号,点击回调', (tester) async {
    var retried = 0;
    await _pump(tester,
        MessageBubble(message: _m(isSelf: true, isFailed: true), onRetry: () => retried++));
    await tester.tap(find.byKey(const Key('chat.retry')));
    expect(retried, 1);
  });

  testWidgets('图片消息:本地文件不存在也走 errorBuilder 不炸', (tester) async {
    await _pump(
        tester,
        MessageBubble(
            message: _m(kind: ChatMessageKind.image, text: '', localPath: 'not_exist.png')));
    await tester.pump(); // 让 errorBuilder 生效
    expect(find.byKey(const Key('chat.image')), findsOneWidget);
  });

  testWidgets('match_notice 仍是居中灰条', (tester) async {
    await _pump(
        tester,
        MessageBubble(
            message: _m(kind: ChatMessageKind.matchNotice, text: '你们已互相喜欢,开始聊天吧')));
    expect(find.byKey(const Key('chat.notice')), findsOneWidget);
  });
}
