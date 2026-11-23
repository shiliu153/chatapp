import 'dart:async';

import 'package:flutter/material.dart';

import '../theme/ember_motion.dart';
import '../theme/ember_theme_context.dart';
import '../theme/tokens.g.dart' as tokens;
import 'ember_component_sizes.dart';

/// Toast:`overlay.scrim` 底 + 白字 13 + `radius.md`;底栏上方 12;淡入 + 上移 8;
/// 2s 自动消失;**不可堆叠**(新的顶替旧的)(spec §8.2 / §8.3)。
///
/// 用 Overlay 而不是 SnackBar:SnackBar 会排队、会推开内容,而规范要求「轻量结果
/// 反馈(不打断)」且同一时刻只有一条(§9.3)。
abstract final class EmberToast {
  static OverlayEntry? _current;
  static Timer? _timer;

  /// 弹一条 Toast;已有一条时先把它撤掉(§8.3「不可堆叠」)。
  ///
  /// 参数说明:
  /// - [context] 用于找 Overlay(必须挂在 `MaterialApp` 之下)。
  /// - [message] 文案(13 号白字,一行放不下会省略)。
  static void show(BuildContext context, String message) {
    final overlay = Overlay.maybeOf(context);
    if (overlay == null) return;

    hide();

    final entry = OverlayEntry(
      builder: (context) => Positioned(
        left: 0,
        right: 0,
        // 底栏高度 + 底距 + 规范给的 12:贴在悬浮胶囊上方(§8.3)。
        bottom: tokens.sizeNavHeight +
            EmberComponentSizes.navBottomInset +
            EmberComponentSizes.toastBottomInset,
        child: Center(child: ToastPill(message: message)),
      ),
    );
    _current = entry;
    overlay.insert(entry);
    _timer = Timer(
      const Duration(milliseconds: EmberComponentSizes.toastDurationMs),
      hide,
    );
  }

  /// 立刻撤掉当前 Toast(重复调用安全)。
  static void hide() {
    _timer?.cancel();
    _timer = null;
    _current?.remove();
    _current = null;
  }
}

/// Toast 的视觉本体(不含定位):淡入 + 上移 8;减弱动态效果时只淡入不位移。
///
/// 单独暴露成组件是为了能直接写断言(定位交给 Overlay),也方便配对成功这类
/// 「情感时刻」以外的场景在自定义 Overlay 里复用。
class ToastPill extends StatefulWidget {
  /// 构造一条 Toast。
  const ToastPill({super.key, required this.message});

  /// 文案。
  final String message;

  @override
  State<ToastPill> createState() => _ToastPillState();
}

class _ToastPillState extends State<ToastPill>
    with SingleTickerProviderStateMixin {
  static const _fadeDuration = Duration(milliseconds: 160);

  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: _fadeDuration,
  );
  var _started = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // 减弱动态效果:120ms 线性淡入、不位移(§8.4)。
    _controller.duration =
        EmberMotion.reducedOf(context) ? EmberMotion.reduced : _fadeDuration;
    if (!_started) {
      _started = true;
      _controller.forward();
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final reduced = EmberMotion.reducedOf(context);
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, child) => Opacity(
        opacity: _controller.value,
        // 首帧透明度是 0:不加这个标志,读屏会**拿不到**这条播报(Opactiy 为 0 时
        // 默认丢弃子树的语义),而「谁提示了什么」正是这里最该播出去的信息。
        alwaysIncludeSemantics: true,
        child: Transform.translate(
          offset: Offset(
            0,
            reduced ? 0 : EmberComponentSizes.toastRise * (1 - _controller.value),
          ),
          child: child,
        ),
      ),
      child: Semantics(
        liveRegion: true,
        label: widget.message,
        child: Container(
          padding: EdgeInsets.symmetric(
            horizontal: tokens.space16,
            vertical: tokens.space12,
          ),
          decoration: BoxDecoration(
            color: colors.overlayScrim,
            borderRadius: BorderRadius.circular(tokens.radiusMd),
          ),
          child: Text(
            widget.message,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
              fontSize: tokens.fontSizeCaption,
              color: Colors.white,
            ),
          ),
        ),
      ),
    );
  }
}
