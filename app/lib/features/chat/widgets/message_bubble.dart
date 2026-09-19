import 'dart:io';

import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/app_avatar.dart';
import '../../../im/im_client.dart';

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
  });

  final ChatMessage message;
  final String? peerName;
  final String? peerAvatarUrl;
  final String? selfAvatarUrl;
  final VoidCallback? onLongPress;
  final VoidCallback? onRetry;
  final VoidCallback? onTapImage;

  static const noticeFallback = '你们已互相喜欢,开始聊天吧';

  @override
  Widget build(BuildContext context) {
    if (message.kind != ChatMessageKind.text && message.kind != ChatMessageKind.image) {
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
              color: AppColors.divider,
              borderRadius: BorderRadius.circular(AppRadius.full),
            ),
            child: Text(label, style: AppText.micro.copyWith(color: AppColors.text2)),
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
    final bubble = GestureDetector(
      onLongPress: onLongPress,
      child: Opacity(
        opacity: message.isPending ? 0.6 : 1,
        child: ConstrainedBox(
          constraints:
              BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * 0.72),
          child: _bubbleContent(context),
        ),
      ),
    );

    return Padding(
      padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md, vertical: AppSpacing.xs),
      child: Row(
        mainAxisAlignment: isSelf ? MainAxisAlignment.end : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (!isSelf) ...[avatar, const SizedBox(width: AppSpacing.sm)],
          if (isSelf && message.isFailed) ...[
            IconButton(
              key: const Key('chat.retry'),
              onPressed: onRetry,
              icon: const Icon(Icons.error_rounded, color: AppColors.danger, size: 20),
              visualDensity: VisualDensity.compact,
            ),
          ],
          bubble,
          if (isSelf) ...[const SizedBox(width: AppSpacing.sm), avatar],
        ],
      ),
    );
  }

  Widget _bubbleContent(BuildContext context) {
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
        color: message.isSelf ? AppColors.brand : AppColors.bgCard,
        borderRadius: BorderRadius.only(
          topLeft: Radius.circular(message.isSelf ? AppRadius.bubble : 6),
          topRight: Radius.circular(message.isSelf ? 6 : AppRadius.bubble),
          bottomLeft: Radius.circular(AppRadius.bubble),
          bottomRight: Radius.circular(AppRadius.bubble),
        ),
      ),
      child: Text(message.text,
          style: AppText.body
              .copyWith(color: message.isSelf ? Colors.white : AppColors.text1)),
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

  Widget _fallback(BuildContext? c, Object? e, StackTrace? s) => Container(
        color: AppColors.divider,
        child: const Center(child: Icon(Icons.image_rounded, color: AppColors.text3)),
      );
}
