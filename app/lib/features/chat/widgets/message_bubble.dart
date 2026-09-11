import 'package:flutter/material.dart';

import '../../../im/im_client.dart';

/// 单条消息:文本气泡(自己右、对方左);match_notice 渲染成居中灰条。
class MessageBubble extends StatelessWidget {
  const MessageBubble({super.key, required this.message});

  final ChatMessage message;

  static const noticeFallback = '你们已互相喜欢,开始聊天吧';

  @override
  Widget build(BuildContext context) {
    if (message.kind != ChatMessageKind.text) {
      final label = switch (message.kind) {
        ChatMessageKind.matchNotice => message.text.isEmpty ? noticeFallback : message.text,
        ChatMessageKind.banNotice => message.text.isEmpty ? '系统通知' : message.text,
        _ => '[暂不支持的消息]',
      };
      return Padding(
        key: const Key('chat.notice'),
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Center(
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            decoration: BoxDecoration(
              color: Colors.black12,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Text(label, style: const TextStyle(color: Colors.black54, fontSize: 12)),
          ),
        ),
      );
    }

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      child: Row(
        mainAxisAlignment: message.isSelf ? MainAxisAlignment.end : MainAxisAlignment.start,
        children: [
          Flexible(
            child: Opacity(
              opacity: message.isPending ? 0.6 : 1, // 回执没回来时先淡一点
              child: Container(
                constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * 0.68),
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                decoration: BoxDecoration(
                  color: message.isSelf ? const Color(0xFFFFD9E2) : Colors.white,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(message.text),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
