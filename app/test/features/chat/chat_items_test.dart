import 'package:flutter_test/flutter_test.dart';
import 'package:chatapp_app/core/format.dart';
import 'package:chatapp_app/features/chat/chat_items.dart';
import 'package:chatapp_app/im/im_client.dart';

ChatMessage _m(String id, DateTime time) => ChatMessage(
      msgId: id,
      peerId: 'u9',
      isSelf: false,
      timestamp: time.millisecondsSinceEpoch,
      kind: ChatMessageKind.text,
      text: id,
    );

void main() {
  test('formatChatTimestamp:今天/昨天/更早', () {
    final now = DateTime(2026, 9, 12, 10, 0);
    expect(formatChatTimestamp(DateTime(2026, 9, 12, 9, 5), now: now), '09:05');
    expect(formatChatTimestamp(DateTime(2026, 9, 11, 22, 30), now: now), '昨天 22:30');
    expect(formatChatTimestamp(DateTime(2026, 3, 1, 8, 0), now: now), '3月1日 08:00');
    expect(formatChatTimestamp(DateTime(2025, 12, 31, 23, 59), now: now), '2025年12月31日 23:59');
  });

  test('buildChatItems:首条必有时间条,间隔超 5 分钟才插新的', () {
    final base = DateTime(2026, 9, 12, 10, 0);
    final items = buildChatItems([
      _m('a', base),
      _m('b', base.add(const Duration(minutes: 5))), // 正好 5 分钟:不插
      _m('c', base.add(const Duration(minutes: 11))), // 超 5 分钟:插
    ], now: base);
    expect(items.whereType<ChatTimeItem>().length, 2);
    expect(items.whereType<ChatMessageItem>().length, 3);
  });

  test('buildChatItems:空列表空输出', () {
    expect(buildChatItems(const [], now: DateTime(2026)), isEmpty);
  });
}
