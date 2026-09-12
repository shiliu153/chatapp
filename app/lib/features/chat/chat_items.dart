import '../../core/format.dart';
import '../../im/im_client.dart';

sealed class ChatItem {
  const ChatItem();
}

class ChatMessageItem extends ChatItem {
  const ChatMessageItem(this.message);
  final ChatMessage message;
}

class ChatTimeItem extends ChatItem {
  const ChatTimeItem(this.label);
  final String label;
}

/// 相邻消息间隔 > 5 分钟(或首条)插一条时间条;输入/输出均为旧→新。
List<ChatItem> buildChatItems(List<ChatMessage> messages, {DateTime? now}) {
  const gapMs = 5 * 60 * 1000;
  final items = <ChatItem>[];
  int? prevTimestamp;
  for (final message in messages) {
    if (prevTimestamp == null || message.timestamp - prevTimestamp > gapMs) {
      items.add(ChatTimeItem(formatChatTimestamp(
          DateTime.fromMillisecondsSinceEpoch(message.timestamp), now: now)));
    }
    items.add(ChatMessageItem(message));
    prevTimestamp = message.timestamp;
  }
  return items;
}
