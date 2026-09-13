import 'package:flutter/material.dart';

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
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
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
        Padding(
          padding: const EdgeInsets.only(top: 8, bottom: 24),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              IconButton.filledTonal(
                key: const Key('discovery.pass'),
                iconSize: 30,
                onPressed: _flying ? null : () => _flyOut(like: false),
                icon: const Icon(Icons.close),
              ),
              const SizedBox(width: 48),
              IconButton.filled(
                key: const Key('discovery.like'),
                iconSize: 30,
                onPressed: _flying ? null : () => _flyOut(like: true),
                icon: const Icon(Icons.favorite),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
