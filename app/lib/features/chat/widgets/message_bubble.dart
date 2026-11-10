import 'dart:io';

import 'package:flutter/material.dart';

import '../../../core/theme/heart_theme_context.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/app_avatar.dart';
import '../../../im/im_client.dart';
import 'voice_bubble.dart';
import '../../../core/theme/heart_colors.dart';
import '../stickers.dart';

/// 单条消息(「心跳」附录 B.3):自己=brand 实底白字、对方=白底,
/// 圆形头像 40;match_notice/ban_notice 渲染成居中 pill 灰条。
class MessageBubble extends StatelessWidget {
  const MessageBubble({
    super.key,
    required this.message,
    this.peerName,
    this.peerAvatarUrl,
    this.selfAvatarUrl,
    this.onLongPress,
    this.onRetry,
    this.onTapImage,
    this.onTapQuote,
    this.onToggleSelect,
    this.selectable = false,
    this.selected = false,
    this.selectionMode = false,
    this.highlight = false,
    this.isRead = false,
    this.readReceiptEnabled = false,
  });

  final ChatMessage message;
  final String? peerName;
  final String? peerAvatarUrl;
  final String? selfAvatarUrl;
  final VoidCallback? onLongPress;
  final VoidCallback? onRetry;
  final VoidCallback? onTapImage;

  /// 点了气泡上方的引用块:跳到被引用的原消息(批次 L-2)。
  final VoidCallback? onTapQuote;

  /// 多选模式下点气泡本体:切换这条的选中状态(批次 T-2)。
  final VoidCallback? onToggleSelect;

  /// 这条消息**能不能**被多选。已撤回 / 发送中 / 居中灰条都不给勾 ——
  /// 前两者删了没有意义(已撤回本来就不显示内容),灰条没有气泡本体可点。
  final bool selectable;

  /// 多选模式下这条是否已选中。
  final bool selected;

  /// 是否处于多选模式:为真时点本体=切换选中、长按菜单/点图/点引用**全部失效**,
  /// 语音气泡也不播(整块内容 IgnorePointer),免得「想勾选却点开了播放器」。
  final bool selectionMode;

  /// 搜索定位命中的气泡:主色淡底高亮 1.5s 后由外层取消。
  final bool highlight;

  /// 对端已读这条(我方消息才有意义;由 `chatPeerReadSeqProvider` 与 `seq` 比较得出)。
  final bool isRead;

  /// 是否支持已读回执(不支持时宁可不显示,也不要假状态)。
  final bool readReceiptEnabled;

  static const noticeFallback = '你们已互相喜欢,开始聊天吧';

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    if (message.isRevoked) {
      return Padding(
        key: const Key('chat.revoked'),
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
        child: Center(
          child: Text(
            message.isSelf ? '你撤回了一条消息' : '对方撤回了一条消息',
            style: AppText.micro.copyWith(color: colors.text3),
          ),
        ),
      );
    }
    if (message.kind != ChatMessageKind.text &&
        message.kind != ChatMessageKind.image &&
        message.kind != ChatMessageKind.voice &&
        message.kind != ChatMessageKind.sticker) {
      final label = switch (message.kind) {
        ChatMessageKind.matchNotice => message.text.isEmpty ? noticeFallback : message.text,
        ChatMessageKind.banNotice => message.text.isEmpty ? '系统通知' : message.text,
        _ => '[暂不支持的消息]',
      };
      return Padding(
        key: const Key('chat.notice'),
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
        child: Center(
          child: Container(
            padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.md, vertical: 6),
            decoration: BoxDecoration(
              color: colors.divider,
              borderRadius: BorderRadius.circular(AppRadius.full),
            ),
            child: Text(label, style: AppText.micro.copyWith(color: colors.text2)),
          ),
        ),
      );
    }

    final isSelf = message.isSelf;
    final avatar = AppAvatar(
      imageUrl: isSelf ? selfAvatarUrl : peerAvatarUrl,
      size: 40,
      fallbackText: isSelf ? '我' : (peerName ?? ''),
    );
    final tappable = selectionMode && selectable;
    final bubble = GestureDetector(
      // 气泡本体的稳定 key:测试与 integration_test 用它点「这一条」,
      // 而不是点里面的文字 —— 多选模式下文字在被 IgnorePointer 挡住的子树里。
      key: Key('chat.bubble:${message.msgId}'),
      // 多选模式下长按菜单一律失效:此刻唯一动作是「勾选/取消勾选」,
      // 再弹菜单会让手指一抖就变成引用或撤回。
      onLongPress: selectionMode ? null : onLongPress,
      onTap: tappable ? onToggleSelect : null,
      // 只有「可勾」的气泡才整块吃事件;其它情况保持原样(deferToChild),
      // 免得把气泡外的空白也变成点击区。
      behavior: tappable ? HitTestBehavior.opaque : HitTestBehavior.deferToChild,
      // 多选模式下内容整块不吃指针:语音气泡、图片、引用块自己的 onTap 全部让位给
      // 外层的「切换选中」,否则「想勾选却点开了播放器 / 全屏大图」。
      child: IgnorePointer(
        ignoring: selectionMode,
        child: Opacity(
          opacity: message.isPending ? 0.6 : 1,
          child: ConstrainedBox(
            constraints:
                BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * 0.72),
            // 引用块在气泡**上方**(批次 L-2):它是「我在回应什么」,不该抢正文的视线。
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment:
                  isSelf ? CrossAxisAlignment.end : CrossAxisAlignment.start,
              children: [
                if (message.ref != null) _quoteBlock(context, message.ref!),
                _bubbleContent(context),
              ],
            ),
          ),
        ),
      ),
    );

    return AnimatedContainer(
      // 搜索定位命中时整个消息行淡入主色底,1.5s 后由外层把 highlight 置回 false
      key: highlight ? Key('chat.highlight:${message.msgId}') : null,
      duration: const Duration(milliseconds: 300),
      decoration: BoxDecoration(
        color: highlight ? colors.brand.withValues(alpha: 0.08) : Colors.transparent,
        borderRadius: BorderRadius.circular(AppRadius.card),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.md, vertical: AppSpacing.xs),
        child: Row(
          mainAxisAlignment: isSelf ? MainAxisAlignment.end : MainAxisAlignment.start,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 勾选圈与左右无关,一律在最左边(微信口径):多选时视线从左边扫下来
            // 对齐的是勾,不是头像。
            if (selectionMode && selectable) ...[
              _selectMark(colors),
              const SizedBox(width: AppSpacing.sm),
            ],
            if (!isSelf) ...[avatar, const SizedBox(width: AppSpacing.sm)],
            if (isSelf && message.isFailed) ...[
              IconButton(
                key: const Key('chat.retry'),
                onPressed: onRetry,
                icon: Icon(Icons.error_rounded, color: colors.danger, size: 20),
                visualDensity: VisualDensity.compact,
              ),
            ],
            if (isSelf && _statusLabel() != null)
              Padding(
                padding: const EdgeInsets.only(right: AppSpacing.xs),
                child: Text(
                  _statusLabel()!,
                  key: _statusKey(),
                  style: AppText.micro.copyWith(color: colors.text3),
                ),
              ),
            bubble,
            if (isSelf) ...[const SizedBox(width: AppSpacing.sm), avatar],
          ],
        ),
      ),
    );
  }

  /// 多选态的勾选圈(批次 T-2)。
  ///
  /// 选中 = 主色实心圆:这正是主色该出现的「视线锚点」(spec §2.1),未选 = `text3`
  /// 空心。key 挂在圈上,测试按 `chat.select:<msgId>` 断言某一行的勾选态。
  ///
  /// Args:
  ///   colors: 「心跳」色板(浅 / 深两套)。
  Widget _selectMark(HeartColors colors) => Icon(
        selected ? Icons.check_circle_rounded : Icons.radio_button_unchecked_rounded,
        key: Key('chat.select:${message.msgId}'),
        size: 22,
        color: selected ? colors.brand : colors.text3,
      );

  /// 我方气泡左侧的状态词(只会是「发送中」或「已读」,其它情况返回 null)。
  ///
  /// 口径:
  /// - 失败不写字 —— 左侧已有红色重发图标,再写字是重复;
  /// - **未读不写字** —— 微信口径。一屏十几条都挂「未读」是纯噪声,而且区分不了
  ///   「已送达未读 / 没送达」;「有没有『已读』这两个字」本身就是未读的信号;
  /// - 不支持已读回执时一律不显示,不给假状态。
  String? _statusLabel() {
    if (!message.isSelf) return null;
    if (message.isPending) return '发送中';
    if (message.isFailed) return null;
    if (!readReceiptEnabled || message.isRevoked) return null;
    return isRead ? '已读' : null;
  }

  Key? _statusKey() {
    if (message.isPending) return const Key('chat.status.pending');
    if (isRead) return const Key('chat.status.read');
    return null;
  }

  /// 气泡上方的引用块(批次 L-2)。
  ///
  /// 摘要来自**服务端快照**(`ref.text`):文本前 120 字,图片 / 语音 / 贴纸是
  /// `[图片]` / `[语音]` / `[贴纸]`;`revoked` 时只显示「消息已撤回」,不显示原文。
  ///
  /// Args:
  ///   context: 构建上下文(取「心跳」色板)。
  ///   ref: 服务端生成的引用快照。
  ///
  /// Returns:
  ///   可点击的引用块(点击跳回原消息)。
  Widget _quoteBlock(BuildContext context, QuoteRef ref) {
    final colors = context.heart;
    // 一个会话只有两个人:引用块的署名不是对端就是我自己。
    final sender = ref.from == message.peerId ? (peerName ?? '对方') : '我';
    return ClipRRect(
      borderRadius: BorderRadius.circular(AppRadius.chip),
      child: GestureDetector(
        key: Key('chat.quote:${message.msgId}'),
        behavior: HitTestBehavior.opaque,
        onTap: onTapQuote,
        child: Container(
          margin: const EdgeInsets.only(bottom: AppSpacing.xs),
          padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.sm, vertical: 6),
          decoration: BoxDecoration(
            color: colors.divider,
            border: Border(left: BorderSide(color: colors.brand, width: 3)),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(sender, style: AppText.micro.copyWith(color: colors.brand)),
              Text(
                ref.displayText,
                key: ref.revoked ? const Key('chat.quote.revoked') : null,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: AppText.micro.copyWith(color: colors.text2),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _bubbleContent(BuildContext context) {
    final colors = context.heart;
    if (message.kind == ChatMessageKind.voice) {
      return VoiceBubble(message: message);
    }
    if (message.kind == ChatMessageKind.sticker) {
      return _sticker(colors);
    }
    if (message.kind == ChatMessageKind.image) {
      return GestureDetector(
        key: const Key('chat.image'),
        onTap: onTapImage,
        child: ClipRRect(
          borderRadius: BorderRadius.circular(AppRadius.image),
          child: SizedBox(width: 140, height: 140, child: _image()),
        ),
      );
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: message.isSelf ? colors.brand : colors.bgCard,
        borderRadius: BorderRadius.only(
          topLeft: Radius.circular(message.isSelf ? AppRadius.bubble : 6),
          topRight: Radius.circular(message.isSelf ? 6 : AppRadius.bubble),
          bottomLeft: Radius.circular(AppRadius.bubble),
          bottomRight: Radius.circular(AppRadius.bubble),
        ),
      ),
      child: Text(message.text,
          style: AppText.body
              .copyWith(color: message.isSelf ? Colors.white : colors.text1)),
    );
  }

  /// 贴纸气泡(批次 J):**不画气泡底色**,只显示图片本身(贴纸自带描边与圆角)。
  ///
  /// 未知 id(老版本收到新贴纸)降级成 `[贴纸]` 文本 pill,不白屏、不抛异常。
  Widget _sticker(HeartColors colors) {
    final sticker = stickerById(message.stickerId);
    if (sticker == null) {
      return Container(
        key: const Key('chat.sticker.unknown'),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(
          color: colors.divider,
          borderRadius: BorderRadius.circular(AppRadius.bubble),
        ),
        child: Text(unknownStickerLabel,
            style: AppText.body.copyWith(color: colors.text2)),
      );
    }
    return Image.asset(
      sticker.assetPath,
      key: Key('chat.sticker.${sticker.id}'),
      width: 132,
      height: 132,
      fit: BoxFit.contain,
      errorBuilder: (context, error, stack) => Container(
        width: 132,
        height: 132,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: colors.divider,
          borderRadius: BorderRadius.circular(AppRadius.image),
        ),
        child: Text(unknownStickerLabel,
            style: AppText.micro.copyWith(color: colors.text3)),
      ),
    );
  }

  Widget _image() {
    final path = message.localPath;
    if (path != null && path.isNotEmpty) {
      return Image.file(File(path), fit: BoxFit.cover, errorBuilder: _fallback);
    }
    final url = message.imageUrl;
    if (url != null && url.isNotEmpty) {
      return Image.network(url, fit: BoxFit.cover, errorBuilder: _fallback);
    }
    return _fallback(null, null, null);
  }

  Widget _fallback(BuildContext? c, Object? e, StackTrace? s) {
    // errorBuilder 会给回当前上下文,直接取色板(为 null 时退回浅色板,不至于炸)
    final colors = c?.heart ?? HeartColors.light;
    return Container(
      color: colors.divider,
      child: Center(child: Icon(Icons.image_rounded, color: colors.text3)),
    );
  }
}
