import 'package:flutter/material.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/theme/app_typography.dart';
import '../../../core/theme/ember_colors.dart';
import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';
import '../stickers.dart';

const chatEmojis = [
  '😀', '😄', '😁', '😊', '🥰', '😍', '😘', '😜', '🤗', '🤔',
  '😐', '😴', '😭', '😅', '😂', '🙈', '👍', '👎', '👏', '🙏',
  '💪', '🎉', '❤️', '💔', '🔥', '✨', '🌹', '🍀', '☀️', '🌙',
  '⭐', '🎈', '☕', '🍺', '🍜', '⚽', '🎵', '📷', '✈️', '🚗',
];

/// 表情 / 贴纸面板的选择结果(E-5.3 page spec §3「表情面板 / 更多面板 → `EmberSheet`」)。
///
/// 为什么用「返回值」而不是回调:面板是**模态 sheet**,选完就关 —— 把「关掉」这件事
/// 交给面板自己(`Navigator.pop(结果)`),页面只处理结果,不必在两次回调之间维护
/// 「面板还开着吗」的状态(心跳期那两个 `_showEmoji` / `_showMore` 布尔就是这么来的)。
sealed class EmojiSheetResult {
  const EmojiSheetResult();
}

/// 选中一个 emoji(页面插进输入框,**纯文本消息,零协议改动**)。
class EmojiPicked extends EmojiSheetResult {
  /// 构造「选中表情」结果。
  const EmojiPicked(this.emoji);

  /// 选中的表情字符。
  final String emoji;
}

/// 选中一张贴纸(页面**直接发送**,载荷 `{"type":"sticker","id":…}`)。
class StickerPicked extends EmojiSheetResult {
  /// 构造「选中贴纸」结果。
  const StickerPicked(this.stickerId);

  /// 贴纸 id。
  final String stickerId;
}

/// 输入栏「表情」入口拉起的弹层内容:两个 tab —— **表情** 与 **贴纸**。
///
/// 形态由 [EmberSheet] 提供(`surface.card` + 上圆角 24 + 拖把 36×4);本组件只管内容,
/// 所以**不再自带底色与容器高度**(心跳期那版是塞在输入栏下方的常驻面板)。
///
/// 默认停在表情 tab:表情是高频操作,贴纸是「额外一步」。
class EmojiSheet extends StatefulWidget {
  /// 构表面板。
  const EmojiSheet({super.key, this.hasStickers = true});

  /// 是否有贴纸 tab(后端不支持贴纸时传 false,只留表情)。
  final bool hasStickers;

  @override
  State<EmojiSheet> createState() => _EmojiSheetState();
}

class _EmojiSheetState extends State<EmojiSheet> {
  bool _stickerTab = false;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final hasStickers = widget.hasStickers;
    return Column(
      key: const Key('chat.emoji.panel'),
      mainAxisSize: MainAxisSize.min,
      children: [
        if (hasStickers) _tabs(colors),
        Flexible(
          child: _stickerTab && hasStickers ? _stickers(colors) : _emojis(),
        ),
      ],
    );
  }

  /// 顶部两个 tab(纯文字 + 选中下划线,不引入 TabBar 的主题依赖)。
  ///
  /// 选中态用 `brand.default` 下划线 + `text.primary` 字,未选 `text.secondary` ——
  /// 「选中不只靠颜色」由下划线本身承担(§8.4)。
  Widget _tabs(EmberColors colors) {
    Widget item(String label, bool selected, Key key, VoidCallback onTap) => Expanded(
          child: InkWell(
            key: key,
            onTap: onTap,
            child: Container(
              height: tokens.sizeTouchWeb,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                border: Border(
                  bottom: BorderSide(
                    color: selected ? colors.brandDefault : Colors.transparent,
                    width: 2,
                  ),
                ),
              ),
              child: Text(
                label,
                style: AppText.micro.copyWith(
                  color: selected ? colors.textPrimary : colors.textSecondary,
                  fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
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
        padding: EdgeInsets.all(tokens.space12),
        children: [
          for (final emoji in chatEmojis)
            InkWell(
              key: Key('chat.emoji.$emoji'),
              borderRadius: BorderRadius.circular(tokens.radiusXs),
              onTap: () => Navigator.of(context).pop(EmojiPicked(emoji)),
              // 表情是图形不是文字:字号取 24 的图标档(token 里没有「图形字号」这一档,
              // 用 `size.icon.24` 而不是裸 24,守住「禁止裸字号」)。
              child: Center(
                child: Text(
                  emoji,
                  style: TextStyle(fontSize: tokens.sizeIcon24),
                ),
              ),
            ),
        ],
      );

  Widget _stickers(EmberColors colors) => GridView.count(
        crossAxisCount: 4,
        padding: EdgeInsets.all(tokens.space12),
        mainAxisSpacing: tokens.space4,
        crossAxisSpacing: tokens.space4,
        children: [
          for (final sticker in chatStickers)
            InkWell(
              key: Key('chat.sticker.${sticker.id}'),
              borderRadius: BorderRadius.circular(tokens.radiusSm),
              onTap: () => Navigator.of(context).pop(StickerPicked(sticker.id)),
              child: Padding(
                padding: EdgeInsets.all(tokens.space4),
                child: Image.asset(
                  sticker.assetPath,
                  fit: BoxFit.contain,
                  // 资源缺失不该炸整个面板(打包漏了 assets/stickers/ 时看得出来)
                  errorBuilder: (context, error, stack) => Icon(
                    PhosphorIconsRegular.imageBroken,
                    size: tokens.sizeIcon24,
                    color: colors.textTertiary,
                  ),
                ),
              ),
            ),
        ],
      );
}
