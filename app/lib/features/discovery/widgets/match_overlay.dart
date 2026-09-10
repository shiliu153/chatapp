import 'package:flutter/material.dart';

import '../models.dart';

/// 配对成功动效:双方头像 + 爱心 + 文案,点「继续滑卡」关闭。
class MatchOverlay extends StatelessWidget {
  const MatchOverlay({
    super.key,
    required this.candidate,
    this.myAvatarUrl,
    required this.onClose,
    this.onGoChat,
  });

  final Candidate candidate;
  final String? myAvatarUrl;
  final VoidCallback onClose;

  /// 有值才显示「去聊天」按钮。
  final VoidCallback? onGoChat;

  @override
  Widget build(BuildContext context) {
    final theirAvatarUrl = candidate.photos.isEmpty ? null : candidate.photos.first.url;
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                _Avatar(url: myAvatarUrl, radius: 44),
                Transform.translate(
                  offset: const Offset(-14, 0),
                  child: _Avatar(url: theirAvatarUrl, radius: 44),
                ),
              ],
            ),
            const SizedBox(height: 20),
            const Icon(Icons.favorite, color: Colors.pinkAccent, size: 40),
            const SizedBox(height: 16),
            const Text(
              '你们已互相喜欢',
              style: TextStyle(color: Colors.white, fontSize: 24, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            Text('和 ${candidate.nickname} 打个招呼吧',
                style: const TextStyle(color: Colors.white70, fontSize: 15)),
            const SizedBox(height: 32),
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (onGoChat != null) ...[
                  FilledButton(
                    key: const Key('match.goChat'),
                    onPressed: onGoChat,
                    child: const Text('去聊天'),
                  ),
                  const SizedBox(width: 12),
                ],
                OutlinedButton(
                  key: const Key('match.continue'),
                  onPressed: onClose,
                  child: const Text('继续滑卡'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _Avatar extends StatelessWidget {
  const _Avatar({required this.url, required this.radius});

  final String? url;
  final double radius;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        border: Border.all(color: Colors.white, width: 3),
      ),
      child: CircleAvatar(
        radius: radius,
        backgroundColor: Colors.white24,
        backgroundImage: url == null ? null : NetworkImage(url!),
        onBackgroundImageError: url == null ? null : (error, stack) {},
        child: url == null ? const Icon(Icons.person, color: Colors.white, size: 40) : null,
      ),
    );
  }
}

/// 弹配对动效;等它关闭后 future 才完成。
Future<void> showMatchOverlay(
  BuildContext context, {
  required Candidate candidate,
  String? myAvatarUrl,
  VoidCallback? onGoChat,
}) =>
    showGeneralDialog<void>(
      context: context,
      barrierDismissible: false,
      barrierLabel: '配对成功',
      barrierColor: Colors.black.withValues(alpha: 0.85),
      transitionDuration: const Duration(milliseconds: 350),
      pageBuilder: (dialogContext, animation, secondary) => MatchOverlay(
        candidate: candidate,
        myAvatarUrl: myAvatarUrl,
        onClose: () => Navigator.of(dialogContext).pop(),
        // 先关弹层再跳,不然路由推在弹层下面
        onGoChat: onGoChat == null
            ? null
            : () {
                Navigator.of(dialogContext).pop();
                onGoChat();
              },
      ),
      transitionBuilder: (context, animation, secondary, child) => FadeTransition(
        opacity: animation,
        child: ScaleTransition(
          scale: Tween<double>(begin: 0.85, end: 1)
              .animate(CurvedAnimation(parent: animation, curve: Curves.easeOutBack)),
          child: child,
        ),
      ),
    );
