import 'package:flutter/material.dart';
import 'package:flutter/physics.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/theme/ember_motion.dart';
import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';
import '../../presence/models.dart';
import '../models.dart';
import 'profile_card.dart';

/// 一次滑卡的处理函数;返回是否配对成功。
typedef DecideCallback = Future<bool> Function(Candidate candidate, {required bool like});

/// 卡组:顶层卡可拖拽,松手超出阈值 → 飞出并回调 [onDecide];没超出 → 弹回。
///
/// 动效口径(「余烬 Ember」§7.1 / E-5.2 page spec §4):
/// - 飞出与弹回都是 **`spring.standard`**(有位移 → spatial 弹簧,不再有 250ms
///   定长 easeOut 曲线);弹簧可被下一次手势续接,手感比定长曲线软;
/// - 卡片按下 **`scale .98`**(`spring.fast`),松手 / 开始拖拽即回弹;
/// - 操作钮换成 [EmberActionButton]:喜欢钮是朱砂实底 + `emberGlow`,**没有心跳脉冲**
///   (装饰性循环动画已被 spec §7.3 取消)。
///
/// 业务语义一行没动:[onDecide] 返回 false(失败 / 后端拒)时卡会摆回原位,
/// 额度用完只置灰按钮、拖拽仍交给后端判定。
class SwipeDeck extends StatefulWidget {
  /// 构造卡组。
  const SwipeDeck({
    super.key,
    required this.candidates,
    required this.onDecide,
    this.presenceById = const {},
    this.undoAction,
    this.likeBlocked = false,
    this.onOpenProfile,
  });

  /// 待滑的候选(第一个是顶层卡)。
  final List<Candidate> candidates;

  /// 滑卡回调(左滑 / 跳过 → `like: false`)。
  final DecideCallback onDecide;

  /// 在线状态,按 userId 索引。
  final Map<int, Presence> presenceById;

  /// 卡面下方最左侧的次要操作(发现页放撤销按钮);为 null 时不给它留位置。
  final Widget? undoAction;

  /// 每日喜欢额度用完(429 + 42904):喜欢钮置灰不可点,拖拽仍交给后端判定。
  final bool likeBlocked;

  /// 点卡面进对方资料页(E-5.2 page spec §7 拍板 3:本单只做**普通 push**,
  /// Hero 转场留给 E-5.4)。为 null 时不响应点击。
  final ValueChanged<Candidate>? onOpenProfile;

  /// 操作钮之间的间距(E-5.2 page spec §3 的操作钮行)。
  static const actionGap = 44.0;

  /// 操作钮行的高度(大档 64 + 上下留白,给按压缩放留余量)。
  static const actionRowHeight = 88.0;

  @override
  State<SwipeDeck> createState() => _SwipeDeckState();
}

class _SwipeDeckState extends State<SwipeDeck> with TickerProviderStateMixin {
  /// 拖过卡宽的多少比例算「滑出去」。
  static const _thresholdFraction = 0.25;

  /// 位置动画(飞出 / 弹回):值域 0→1,映射到起点→终点。
  late final AnimationController _slide = AnimationController(vsync: this, value: 0);

  /// 按压缩放:值域 .98↔1。
  late final AnimationController _press =
      AnimationController(vsync: this, value: 1, duration: const Duration(milliseconds: 1));

  Animation<Offset>? _animation;
  Offset _offset = Offset.zero;
  bool _flying = false;
  int? _flightId;

  @override
  void dispose() {
    _slide.dispose();
    _press.dispose();
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

  /// 用弹簧把位置从 [from] 推到 [to];减弱动态效果时直接落到终点(§7.3)。
  Future<void> _animateTo(Offset target) async {
    final from = _offset;
    if (from == target) return;
    final animation = Tween<Offset>(begin: from, end: target).animate(_slide);
    _animation = animation;
    animation.addListener(_onTick);
    _slide.value = 0;
    if (EmberMotion.reducedOf(context)) {
      // 减弱动态效果:不位移,直接落终点(value 的 setter 会通知监听者重绘)。
      _slide.value = 1;
    } else {
      await _slide.animateWith(
        SpringSimulation(EmberMotion.standard, 0, 1, 0),
      );
    }
    animation.removeListener(_onTick);
    _animation = null;
  }

  void _onTick() {
    final animation = _animation;
    if (animation == null) return;
    setState(() => _offset = animation.value);
  }

  /// 按压反馈:顶层卡缩到 .98(spec §8.2 卡片 pressed),`spring.fast`。
  void _setPressed(bool pressed) {
    final target = pressed ? EmberComponentSizes.cardPressedScale : 1.0;
    if (EmberMotion.reducedOf(context)) {
      _press.value = 1;
      return;
    }
    _press.animateWith(
      SpringSimulation(EmberMotion.fast, _press.value, target, _press.velocity),
    );
  }

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
    await _animateTo(Offset(like ? _width * 1.5 : -_width * 1.5, _offset.dy + tokens.space32));
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
            padding: EdgeInsets.fromLTRB(
              tokens.space20,
              tokens.space8,
              tokens.space20,
              0,
            ),
            child: Stack(
              fit: StackFit.expand,
              children: [
                if (second != null)
                  Transform.scale(
                    scale: 0.95,
                    child: ProfileCard(
                      candidate: second,
                      presence: widget.presenceById[second.userId],
                    ),
                  ),
                AnimatedBuilder(
                  animation: Listenable.merge([_slide, _press]),
                  builder: (context, child) => Transform.translate(
                    offset: _offset,
                    child: Transform.rotate(
                      angle: _offset.dx / _width * 0.3,
                      child: Transform.scale(scale: _press.value, child: child),
                    ),
                  ),
                  child: GestureDetector(
                    key: const Key('deck.topCard'),
                    // 必须 opaque:默认 deferToChild 时,照片区没有命中目标,按在照片上拖不动
                    behavior: HitTestBehavior.opaque,
                    onTapDown: _flying ? null : (_) => _setPressed(true),
                    onTapUp: _flying ? null : (_) => _setPressed(false),
                    onTapCancel: _flying ? null : () => _setPressed(false),
                    onTap: _flying || widget.onOpenProfile == null
                        ? null
                        : () => widget.onOpenProfile!(top),
                    onPanUpdate: _flying ? null : _onPanUpdate,
                    onPanEnd: _flying ? null : _onPanEnd,
                    child: ProfileCard(
                      candidate: top,
                      presence: widget.presenceById[top.userId],
                      // 只有顶卡参与 Hero:它才是「点下去的那张卡」,也是点进资料页
                      // 的飞行起点(E-5.4 page spec §3 Hero 三条入口之一)。
                      heroTag: 'photo-user-${top.userId}',
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
        SizedBox(
          height: SwipeDeck.actionRowHeight,
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              if (widget.undoAction != null) ...[
                widget.undoAction!,
                const SizedBox(width: SwipeDeck.actionGap),
              ],
              EmberActionButton(
                key: const Key('discovery.pass'),
                icon: PhosphorIconsRegular.x,
                semanticLabel: '跳过',
                size: EmberActionButtonSize.small,
                onPressed: _flying ? null : () => _flyOut(like: false),
              ),
              const SizedBox(width: SwipeDeck.actionGap),
              EmberActionButton(
                key: const Key('discovery.like'),
                icon: PhosphorIconsFill.heart,
                semanticLabel: '喜欢',
                variant: EmberActionButtonVariant.primary,
                size: EmberActionButtonSize.large,
                // 额度用完:置灰(无光晕无按压),但拖拽右滑仍交给后端判定
                onPressed: _flying || widget.likeBlocked ? null : () => _flyOut(like: true),
              ),
            ],
          ),
        ),
        SizedBox(height: tokens.space20),
      ],
    );
  }
}
