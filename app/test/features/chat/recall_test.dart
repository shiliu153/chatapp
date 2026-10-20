import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/chat/recall.dart';
import 'package:chatapp_app/im/im_client.dart';

ChatMessage _msg({
  required bool isSelf,
  required DateTime at,
  ChatMessageKind kind = ChatMessageKind.text,
  bool isPending = false,
  bool isFailed = false,
  bool isRevoked = false,
}) =>
    ChatMessage(
      msgId: 'm1',
      peerId: 'u9',
      isSelf: isSelf,
      timestamp: at.millisecondsSinceEpoch,
      kind: kind,
      text: '你好',
      isPending: isPending,
      isFailed: isFailed,
      isRevoked: isRevoked,
    );

void main() {
  final now = DateTime(2026, 10, 20, 12, 0);

  test('自己 2 分钟内的文字可以撤回', () {
    expect(
        canRecall(_msg(isSelf: true, at: now.subtract(const Duration(seconds: 30))), now: now),
        isTrue);
  });

  test('超过 2 分钟不能撤回', () {
    expect(canRecall(_msg(isSelf: true, at: now.subtract(const Duration(minutes: 3))), now: now),
        isFalse);
  });

  test('对方的消息不能撤回', () {
    expect(canRecall(_msg(isSelf: false, at: now), now: now), isFalse);
  });

  test('发送中/失败/已撤回的消息不能撤回', () {
    expect(canRecall(_msg(isSelf: true, at: now, isPending: true), now: now), isFalse);
    expect(canRecall(_msg(isSelf: true, at: now, isFailed: true), now: now), isFalse);
    expect(canRecall(_msg(isSelf: true, at: now, isRevoked: true), now: now), isFalse);
  });

  test('系统灰条不能撤回', () {
    expect(
        canRecall(_msg(isSelf: true, at: now, kind: ChatMessageKind.matchNotice), now: now),
        isFalse);
  });

  test('图片消息同样可以撤回', () {
    expect(canRecall(_msg(isSelf: true, at: now, kind: ChatMessageKind.image), now: now), isTrue);
  });
}
