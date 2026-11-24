import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/theme/ember_colors.dart';
import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;

/// 发现页的「撤销上一次滑卡」按钮(批次 O,discovery.md §3.9)。
///
/// 外观照 E-5.2 page spec §3 / §4 的**撤销钮**:48 圆钮、`surface.card` 底 +
/// `border.divider` 描边,外圈是 **30 秒倒计时环**(底环 `border.divider`、进度弧
/// `brand.default` —— 心跳期的渐变扫光已随渐变一起取消)。倒计时归零后按钮置灰、
/// 不再响应点击 —— 后端同样会在 30 秒后回 `40003`。
///
/// 保留倒计时环的理由(规格 §7 拍板 7):它是**窗口提示**(用户得知道还能撤多久),
/// 不是装饰动效 —— 所以它不属于 §7.3 禁的那类循环动画,也没做成循环。
///
/// 倒计时以「挂载时给的 [remaining]」为起点,由 [AnimationController] 驱动:
/// 页面每次重建都会传一份新的 [remaining],但只有**换了一次滑卡**(key 变)才会
/// 重建 State,所以中途重建不会把倒计时拉回 30 秒。
class UndoButton extends StatefulWidget {
  /// 构造撤销钮。
  const UndoButton({
    super.key,
    required this.remaining,
    required this.onUndo,
  });

  /// 本次还能撤销多久;`<= 0` 表示已经过期(进页面时就已经超时那种)。
  final Duration remaining;

  /// 点按时执行撤销;按钮在它返回之前保持忙碌态(不可再点)。
  final Future<void> Function() onUndo;

  /// 圆钮直径(比「跳过」的 56 小一号:它是次要操作)。
  static const size = 48.0;

  /// 图标 20(与发现页顶栏入口同号,比主操作钮的 24 小)。
  static const _iconSize = 20.0;

  @override
  State<UndoButton> createState() => _UndoButtonState();
}

class _UndoButtonState extends State<UndoButton> with SingleTickerProviderStateMixin {
  late final AnimationController _countdown = AnimationController(
    vsync: this,
    duration: widget.remaining > Duration.zero ? widget.remaining : Duration.zero,
  )..addStatusListener(_onStatus);

  /// 倒计时已经走完(或挂载时就已过期)。
  late bool _expired = widget.remaining <= Duration.zero;

  /// 撤销请求在飞:防连点,也顺手把按钮置灰。
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    if (!_expired) _countdown.forward();
  }

  @override
  void dispose() {
    _countdown.dispose();
    super.dispose();
  }

  void _onStatus(AnimationStatus status) {
    if (status == AnimationStatus.completed && mounted) {
      setState(() => _expired = true);
    }
  }

  Future<void> _handleTap() async {
    if (_expired || _busy) return;
    setState(() => _busy = true);
    try {
      await widget.onUndo();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final enabled = !_expired && !_busy;
    return Semantics(
      button: true,
      enabled: enabled,
      label: enabled ? '撤销上一次滑卡' : '撤销已过期',
      child: GestureDetector(
        key: const Key('discovery.undo'),
        behavior: HitTestBehavior.opaque,
        onTap: enabled ? _handleTap : null,
        child: AnimatedBuilder(
          animation: _countdown,
          builder: (context, child) {
            // 走过的比例越少,剩余弧越长;过期后不画弧(只剩底环)
            final progress =
                _expired ? 0.0 : (1 - _countdown.value).clamp(0.0, 1.0);
            return SizedBox.square(
              dimension: UndoButton.size,
              child: CustomPaint(
                painter: _UndoRingPainter(
                  progress: progress,
                  colors: colors,
                  active: enabled,
                ),
                child: child,
              ),
            );
          },
          child: Center(
            child: Container(
              // 内圈缩进一个描边宽度 + 一点留白,让倒计时环与圆钮之间有缝
              width: UndoButton.size - _UndoRingPainter.stroke * 2 - tokens.space4,
              height: UndoButton.size - _UndoRingPainter.stroke * 2 - tokens.space4,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: colors.surfaceCard,
                border: Border.all(color: colors.borderDivider),
              ),
              child: Icon(
                PhosphorIconsRegular.arrowCounterClockwise,
                size: UndoButton._iconSize,
                color: enabled ? colors.textPrimary : colors.textTertiary,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 外圈倒计时环:底环 `border.divider` 3px,进度弧 `brand.default` 3px,自 12 点顺时针。
class _UndoRingPainter extends CustomPainter {
  _UndoRingPainter({required this.progress, required this.colors, required this.active});

  /// 剩余比例:1 = 满窗,0 = 过期。
  final double progress;

  /// 自绘发生在 paint 阶段(拿不到 BuildContext),色板由外部注入。
  final EmberColors colors;

  /// 置灰时进度弧也退成中性色,呼应「不可点」。
  final bool active;

  static const stroke = 3.0;

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Rect.fromLTWH(
        stroke / 2, stroke / 2, size.width - stroke, size.height - stroke);
    canvas.drawArc(
      rect,
      0,
      math.pi * 2,
      false,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = stroke
        ..color = colors.borderDivider,
    );
    if (progress <= 0) return;
    canvas.drawArc(
      rect,
      -math.pi / 2,
      math.pi * 2 * progress,
      false,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = stroke
        ..strokeCap = StrokeCap.round
        // 环色 = 品牌色实值(§3 撤销钮行):渐变扫光属心跳期做法,已取消。
        ..color = active ? colors.brandDefault : colors.textTertiary,
    );
  }

  @override
  bool shouldRepaint(_UndoRingPainter old) =>
      old.progress != progress || old.active != active || old.colors != colors;
}
