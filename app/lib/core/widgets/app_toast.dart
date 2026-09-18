import 'dart:async';

import 'package:flutter/material.dart';

import '../theme/app_motion.dart';
import '../theme/app_radius.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';

/// 「心跳」规则 §7 Toast:深色浮层,底栏上方,淡入+上移,2s 自动消失。
abstract final class AppToast {
  static const _showFor = Duration(seconds: 2);

  static void show(BuildContext context, String message) {
    final overlay = Overlay.of(context);
    late OverlayEntry entry;
    entry = OverlayEntry(
      builder: (_) => _ToastView(message: message, onDone: () => entry.remove()),
    );
    overlay.insert(entry);
  }
}

class _ToastView extends StatefulWidget {
  const _ToastView({required this.message, required this.onDone});

  final String message;
  final VoidCallback onDone;

  @override
  State<_ToastView> createState() => _ToastViewState();
}

class _ToastViewState extends State<_ToastView> with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: AppMotion.base)..forward();
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer(AppToast._showFor, () {
      if (mounted) widget.onDone();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Positioned(
        left: 0,
        right: 0,
        bottom: 96, // 悬浮底栏(64+10)上方 12 再留余量
        child: Center(
          child: AnimatedBuilder(
            animation: _c,
            builder: (context, child) => Opacity(
              opacity: _c.value,
              child: Transform.translate(
                offset: Offset(0, 8 * (1 - _c.value)),
                child: child,
              ),
            ),
            child: Container(
              padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.lg,
                vertical: AppSpacing.md,
              ),
              decoration: BoxDecoration(
                color: const Color(0xEB16181D), // rgba(22,24,29,.92)
                borderRadius: BorderRadius.circular(AppRadius.input),
              ),
              child: Text(
                widget.message,
                style: AppText.caption.copyWith(color: Colors.white),
              ),
            ),
          ),
        ),
      );
}
