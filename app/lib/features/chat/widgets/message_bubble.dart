import 'dart:io';

import 'package:flutter/material.dart';

import '../../../im/im_client.dart';

/// 单条消息:对方=方头像+白气泡(左),自己=品牌粉气泡+方头像(右);
/// match_notice/ban_notice 渲染成居中灰条。
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

    final isSelf = message.isSelf;
    final avatar = _SquareAvatar(
      name: isSelf ? '我' : (peerName ?? ''),
      url: isSelf ? selfAvatarUrl : peerAvatarUrl,
    );
    final bubble = GestureDetector(
      onLongPress: onLongPress,
      child: Opacity(
        opacity: message.isPending ? 0.6 : 1,
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * 0.66),
          child: _bubbleContent(context),
        ),
      ),
    );

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
      child: Row(
        mainAxisAlignment: isSelf ? MainAxisAlignment.end : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (!isSelf) ...[avatar, const SizedBox(width: 8)],
          if (isSelf && message.isFailed) ...[
            IconButton(
              key: const Key('chat.retry'),
              onPressed: onRetry,
              icon: const Icon(Icons.error, color: Colors.red, size: 20),
              visualDensity: VisualDensity.compact,
            ),
          ],
          bubble,
          if (isSelf) ...[const SizedBox(width: 8), avatar],
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
          borderRadius: BorderRadius.circular(8),
          child: SizedBox(width: 140, height: 140, child: _image()),
        ),
      );
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        color: message.isSelf ? const Color(0xFFFF2C55) : Colors.white,
        borderRadius: BorderRadius.only(
          topLeft: const Radius.circular(10),
          topRight: const Radius.circular(10),
          bottomLeft: Radius.circular(message.isSelf ? 10 : 2),
          bottomRight: Radius.circular(message.isSelf ? 2 : 10),
        ),
      ),
      child: Text(message.text,
          style: TextStyle(
              fontSize: 15,
              color: message.isSelf ? Colors.white : const Color(0xFF26282C))),
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
        color: const Color(0xFFEFE3E7),
        child: const Center(child: Icon(Icons.image_outlined, color: Colors.white70)),
      );
}

/// 方形圆角头像(微信式);无图显示首字。
class _SquareAvatar extends StatelessWidget {
  const _SquareAvatar({required this.name, this.url});

  final String name;
  final String? url;

  @override
  Widget build(BuildContext context) {
    final image = url;
    final placeholder = Center(
      child: Text(name.isEmpty ? '?' : name.substring(0, 1),
          style: const TextStyle(color: Colors.white, fontSize: 15)),
    );
    return Container(
      width: 40,
      height: 40,
      decoration: BoxDecoration(
        color: const Color(0xFFF3B8C8),
        borderRadius: BorderRadius.circular(6),
      ),
      clipBehavior: Clip.antiAlias,
      child: image == null || image.isEmpty
          ? placeholder
          : Image.network(image, fit: BoxFit.cover,
              errorBuilder: (c, e, s) => placeholder),
    );
  }
}
