import 'package:flutter/material.dart';

const chatEmojis = [
  '😀', '😄', '😁', '😊', '🥰', '😍', '😘', '😜', '🤗', '🤔',
  '😐', '😴', '😭', '😅', '😂', '🙈', '👍', '👎', '👏', '🙏',
  '💪', '🎉', '❤️', '💔', '🔥', '✨', '🌹', '🍀', '☀️', '🌙',
  '⭐', '🎈', '☕', '🍺', '🍜', '⚽', '🎵', '📷', '✈️', '🚗',
];

/// 基础表情面板:点选把 emoji 回给调用方。
class EmojiPanel extends StatelessWidget {
  const EmojiPanel({super.key, required this.onSelect});

  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context) => Container(
        key: const Key('chat.emoji.panel'),
        height: 220,
        color: const Color(0xFFF7F3F5),
        child: GridView.count(
          crossAxisCount: 8,
          padding: const EdgeInsets.all(8),
          children: [
            for (final emoji in chatEmojis)
              InkWell(
                key: Key('chat.emoji.$emoji'),
                onTap: () => onSelect(emoji),
                child: Center(child: Text(emoji, style: const TextStyle(fontSize: 24))),
              ),
          ],
        ),
      );
}
