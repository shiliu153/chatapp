import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_gradients.dart';
import '../../../core/theme/app_motion.dart';
import '../../../core/theme/app_shadows.dart';
import '../../../core/theme/app_spacing.dart';
import '../../presence/models.dart';
import '../models.dart';
import 'profile_card.dart';

/// 一次滑卡的处理函数;返回是否配对成功。
typedef DecideCallback = Future<bool> Function(Candidate candidate, {required bool like});

/// 卡组:顶层卡可拖拽,松手超出阈值 → 飞出并回调 [onDecide];没超出 → 弹回。
class SwipeDeck extends StatefulWidget {
  const SwipeDeck({super.key, required this.candidates, required this.onDecide,
      this.presenceById = const {}});

  final List<Candidate> candidates;
  final DecideCallback onDecide;
  final Map<int, Presence> presenceById;

  @override
  State<SwipeDeck> createState() => _SwipeDeckState();
}

class _SwipeDeckState extends State<SwipeDeck> with SingleTickerProviderStateMixin {
  /// 拖过卡宽的多少比例算「滑出去」。
  static const _thresholdFraction = 0.25;

  late final AnimationController _controller =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 250));
  Animation<Offset>? _animation;
  Offset _offset = Offset.zero;
  bool _flying = false;
  int? _flightId;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  void didUpdateWidget(covariant SwipeDeck oldWidget) {
    super.didUpdateWidget(oldWidget);
    // 飞出去的那张已经不在顶层了(列表换人,或父级原地删了它)→ 复位,新卡从居中开始。
    // 只读新列表:老 widget 的列表可能是被父级原地改过的同一个对象,读不得。
    if (_flying && _topId(widget.candidates) != _flightId) {
      _offset = Offset.zero;
      _flying = false;
    }
  }

  static int? _topId(List<Candidate> candidates) =>
      candidates.isEmpty ? null : candidates.first.userId;

  double get _width => MediaQuery.sizeOf(context).width;

  Future<void> _animateTo(Offset target) async {
    _controller.reset();
    final animation = Tween<Offset>(begin: _offset, end: target)
        .animate(CurvedAnimation(parent: _controller, curve: Curves.easeOut));
    _animation = animation;
    animation.addListener(_onTick);
    await _controller.forward();
    animation.removeListener(_onTick);
  }

  void _onTick() => setState(() => _offset = _animation!.value);

  void _onPanUpdate(DragUpdateDetails details) =>
      setState(() => _offset += Offset(details.delta.dx, 0));

  void _onPanEnd(DragEndDetails details) {
    if (_offset.dx.abs() > _width * _thresholdFraction) {
      _flyOut(like: _offset.dx > 0);
    } else {
      _snapBack();
    }
  }

  /// 弹回原位;不算一次滑卡。
  Future<void> _snapBack() async {
    if (_flying) return;
    await _animateTo(Offset.zero);
  }

  /// 飞出屏幕;动画结束后回调 [onDecide](等它返回,失败时卡会被放回来)。
  Future<void> _flyOut({required bool like}) async {
    if (_flying || widget.candidates.isEmpty) return;
    final candidate = widget.candidates.first;
    _flying = true;
    _flightId = candidate.userId;
    await _animateTo(Offset(like ? _width * 1.5 : -_width * 1.5, _offset.dy + 32));
    if (!mounted) return;
    try {
      await widget.onDecide(candidate, like: like);
    } finally {
      // 顶层还是这张(比如滑卡失败被放回)→ 摆回居中;
      // 已经换下一张的话,didUpdateWidget 早就复位过了,这里别碰新卡的状态
      if (mounted && _topId(widget.candidates) == candidate.userId) {
        setState(() {
          _offset = Offset.zero;
          _flying = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final candidates = widget.candidates;
    if (candidates.isEmpty) return const SizedBox.shrink();
    final top = candidates.first;
    final second = candidates.length > 1 ? candidates[1] : null;
    return Column(
      children: [
        Expanded(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(
                AppSpacing.pageH, AppSpacing.sm, AppSpacing.pageH, 0),
            child: Stack(
              fit: StackFit.expand,
              children: [
                if (second != null)
                  Transform.scale(
                      scale: 0.95,
                      child: ProfileCard(
                          candidate: second,
                          presence: widget.presenceById[second.userId])),
                GestureDetector(
                  key: const Key('deck.topCard'),
                  // 必须 opaque:默认 deferToChild 时,照片区没有命中目标,按在照片上拖不动
                  behavior: HitTestBehavior.opaque,
                  onPanUpdate: _flying ? null : _onPanUpdate,
                  onPanEnd: _flying ? null : _onPanEnd,
                  child: Transform.translate(
                    offset: _offset,
                    child: Transform.rotate(
                      angle: _offset.dx / _width * 0.3,
                      child: ProfileCard(
                          candidate: top, presence: widget.presenceById[top.userId]),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
        SizedBox(
          height: 88,
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              _DeckActionButton(
                buttonKey: const Key('discovery.pass'),
                icon: Icons.close_rounded,
                size: 56,
                foreground: AppColors.text3,
                background: AppColors.bgCard,
                borderColor: AppColors.divider,
                shadow: AppShadows.card,
                onPressed: _flying ? null : () => _flyOut(like: false),
              ),
              const SizedBox(width: 44),
              _DeckActionButton(
                buttonKey: const Key('discovery.like'),
                icon: Icons.favorite_rounded,
                size: 64,
                foreground: Colors.white,
                gradient: AppGradients.heart,
                shadow: AppShadows.primaryButton,
                pulse: true,
                onPressed: _flying ? null : () => _flyOut(like: true),
              ),
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.lg),
      ],
    );
  }
}

/// 附录 A.1 滑卡操作钮:圆钮 + 按压 .96;喜欢钮带心跳脉冲 1→1.25→1。
class _DeckActionButton extends StatefulWidget {
  const _DeckActionButton({
    required this.buttonKey,
    required this.icon,
    required this.size,
    required this.foreground,
    this.background,
    this.gradient,
    this.borderColor,
    required this.shadow,
    this.pulse = false,
    this.onPressed,
  });

  final Key buttonKey;
  final IconData icon;
  final double size;
  final Color foreground;
  final Color? background;
  final Gradient? gradient;
  final Color? borderColor;
  final List<BoxShadow> shadow;
  final bool pulse;
  final VoidCallback? onPressed;

  @override
  State<_DeckActionButton> createState() => _DeckActionButtonState();
}

class _DeckActionButtonState extends State<_DeckActionButton>
    with SingleTickerProviderStateMixin {
  late final AnimationController _pulse =
      AnimationController(vsync: this, duration: AppMotion.base);
  var _pressed = false;

  @override
  void dispose() {
    _pulse.dispose();
    super.dispose();
  }

  void _handleTap() {
    if (widget.onPressed == null) return;
    if (widget.pulse) _pulse.forward(from: 0); // 与飞出并行,不阻塞
    widget.onPressed!();
  }

  @override
  Widget build(BuildContext context) {
    final enabled = widget.onPressed != null;
    return GestureDetector(
      key: widget.buttonKey,
      behavior: HitTestBehavior.opaque,
      onTapDown: enabled ? (_) => setState(() => _pressed = true) : null,
      onTapUp: enabled ? (_) => setState(() => _pressed = false) : null,
      onTapCancel: enabled ? () => setState(() => _pressed = false) : null,
      onTap: _handleTap,
      child: AnimatedScale(
        scale: _pressed ? 0.96 : 1,
        duration: AppMotion.fast,
        child: AnimatedBuilder(
          animation: _pulse,
          builder: (context, child) => Transform.scale(
            key: widget.pulse ? const Key('deck.pulse') : null,
            scale: 1 + 0.25 * math.sin(math.pi * _pulse.value),
            child: child,
          ),
          child: Container(
            width: widget.size,
            height: widget.size,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: widget.background,
              gradient: widget.gradient,
              border: widget.borderColor == null
                  ? null
                  : Border.all(color: widget.borderColor!, width: 1.5),
              boxShadow: widget.shadow,
            ),
            child: Icon(widget.icon, size: 24, color: widget.foreground),
          ),
        ),
      ),
    );
  }
}
