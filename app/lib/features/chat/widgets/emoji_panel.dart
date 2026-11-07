import 'package:flutter/material.dart';

import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/theme/heart_colors.dart';
import '../../../core/theme/heart_theme_context.dart';
import '../stickers.dart';

const chatEmojis = [
  '😀', '😄', '😁', '😊', '🥰', '😍', '😘', '😜', '🤗', '🤔',
  '😐', '😴', '😭', '😅', '😂', '🙈', '👍', '👎', '👏', '🙏',
  '💪', '🎉', '❤️', '💔', '🔥', '✨', '🌹', '🍀', '☀️', '🌙',
  '⭐', '🎈', '☕', '🍺', '🍜', '⚽', '🎵', '📷', '✈️', '🚗',
];

/// 输入框下方的面板(批次 J):两个 tab —— **表情** 与 **贴纸**。
///
/// - 表情:点选把 emoji 回给调用方,由页面插进输入框(**纯文本消息,零协议改动**);
/// - 贴纸:点选**直接发送**(`kind=2 custom`,载荷 `{"type":"sticker","id":…}`),
///   资源是打包进客户端的 PNG(`assets/stickers/`),消息里只传 id。
///
/// 默认停在表情 tab:表情是高频操作,贴纸是「额外一步」。
class EmojiPanel extends StatefulWidget {
  const EmojiPanel({super.key, required this.onSelect, this.onSendSticker});

  /// 选中一个 emoji(页面负责插入输入框)。
  final ValueChanged<String> onSelect;

  /// 选中一张贴纸(页面负责直接发送);为 null 时只显示表情 tab。
  final ValueChanged<String>? onSendSticker;

  @override
  State<EmojiPanel> createState() => _EmojiPanelState();
}

class _EmojiPanelState extends State<EmojiPanel> {
  bool _stickerTab = false;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    final hasStickers = widget.onSendSticker != null;
    return Container(
      key: const Key('chat.emoji.panel'),
      height: 248,
      decoration: BoxDecoration(
        color: colors.bgCard,
        border: Border(top: BorderSide(color: colors.divider)),
      ),
      child: Column(
        children: [
          if (hasStickers) _tabs(colors),
          Expanded(
            child: _stickerTab && hasStickers ? _stickers(colors) : _emojis(),
          ),
        ],
      ),
    );
  }

  /// 顶部两个 tab(纯文字 + 选中下划线,不引入 TabBar 的主题依赖)。
  Widget _tabs(HeartColors colors) {
    Widget item(String label, bool selected, Key key, VoidCallback onTap) => Expanded(
          child: InkWell(
            key: key,
            onTap: onTap,
            child: Container(
              height: 40,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                border: Border(
                  bottom: BorderSide(
                    color: selected ? colors.brand : Colors.transparent,
                    width: 2,
                  ),
                ),
              ),
              child: Text(
                label,
                style: AppText.micro.copyWith(
                  color: selected ? colors.text1 : colors.text2,
                ),
              ),
            ),
          ),
        );
    return Row(
      children: [
        item('表情', !_stickerTab, const Key('chat.panel.tab.emoji'),
            () => setState(() => _stickerTab = false)),
        item('贴纸', _stickerTab, const Key('chat.panel.tab.sticker'),
            () => setState(() => _stickerTab = true)),
      ],
    );
  }

  Widget _emojis() => GridView.count(
        crossAxisCount: 8,
        padding: const EdgeInsets.all(AppSpacing.sm),
        children: [
          for (final emoji in chatEmojis)
            InkWell(
              key: Key('chat.emoji.$emoji'),
              onTap: () => widget.onSelect(emoji),
              child: Center(child: Text(emoji, style: const TextStyle(fontSize: 24))),
            ),
        ],
      );

  Widget _stickers(HeartColors colors) => GridView.count(
        crossAxisCount: 4,
        padding: const EdgeInsets.all(AppSpacing.sm),
        mainAxisSpacing: AppSpacing.xs,
        crossAxisSpacing: AppSpacing.xs,
        children: [
          for (final sticker in chatStickers)
            InkWell(
              key: Key('chat.sticker.${sticker.id}'),
              borderRadius: BorderRadius.circular(AppRadius.image),
              onTap: () => widget.onSendSticker?.call(sticker.id),
              child: Padding(
                padding: const EdgeInsets.all(2),
                child: Image.asset(
                  sticker.assetPath,
                  fit: BoxFit.contain,
                  // 资源缺失不该炸整个面板(打包漏了 assets/stickers/ 时看得出来)
                  errorBuilder: (context, error, stack) => Icon(
                    Icons.image_not_supported_rounded,
                    color: colors.text3,
                  ),
                ),
              ),
            ),
        ],
      );
}
