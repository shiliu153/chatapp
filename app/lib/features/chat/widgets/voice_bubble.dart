import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/heart_theme_context.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../im/im_client.dart';
import '../voice_playback.dart';

/// 语音气泡(批次 T-2):播放/暂停 + **可拖进度条** + 剩余/总时长 + 倍速。
///
/// 三条交互口径:
/// - **拖动时不跟手**:按下进度条先置 `_dragging`,这期间播放器回报的进度一律不理会,
///   否则手指还没松开、滑块就被播放进度拽回去(「一边拖一边跳」);
///   松手([Slider.onChangeEnd])才真的 `seek`。
/// - **倍速点一下循环** 1.0x → 1.5x → 2.0x → 1.0x,换条播放**复位 1.0x**
///   —— 播放器是全局单例,不复位的话新那条会沿用上一条的 2.0x,听起来像坏了。
/// - **同一时刻只播一条**:靠 [VoicePlayer.onSource] 判断「现在播的是不是我」,
///   不是就把在播状态、进度、倍速一起复位。
class VoiceBubble extends ConsumerStatefulWidget {
  const VoiceBubble({super.key, required this.message});

  final ChatMessage message;

  @override
  ConsumerState<VoiceBubble> createState() => _VoiceBubbleState();
}

class _VoiceBubbleState extends ConsumerState<VoiceBubble> {
  /// 倍速档位:点一下顺延,到底回 1.0x。
  static const rates = [1.0, 1.5, 2.0];

  bool _playing = false;
  double _rate = 1.0;
  Duration _position = Duration.zero;

  /// 手指正在拖进度条:此时不跟随播放器回报的进度(见类注释)。
  bool _dragging = false;

  /// 拖动过程中的临时位置(秒),松手后作废。
  double _dragSeconds = 0;

  StreamSubscription<void>? _completeSub;
  StreamSubscription<Duration>? _positionSub;
  StreamSubscription<String?>? _sourceSub;

  /// 这条消息的播放源:本地文件优先(刚录完/发送中也能听),否则远程地址。
  String get _source {
    final local = widget.message.localPath;
    if (local != null && local.isNotEmpty) return local;
    return widget.message.voiceUrl ?? '';
  }

  /// 是否按本地文件播放。
  bool get _isLocal {
    final local = widget.message.localPath;
    return local != null && local.isNotEmpty;
  }

  /// 总时长(秒,至少 1 秒:0 会让 Slider 的 max 非法)。
  double get _totalSeconds =>
      (widget.message.voiceDurationMs / 1000).clamp(1, 600).toDouble();

  @override
  void initState() {
    super.initState();
    final player = ref.read(voicePlayerProvider);
    _completeSub = player.onComplete.listen((_) {
      if (!mounted) return;
      setState(() {
        _playing = false;
        _position = Duration.zero;
        _dragging = false;
      });
    });
    _positionSub = player.onPosition.listen((position) {
      // 拖动中不跟手;没在播时也不跟着画(别的气泡在播时不该动)。
      if (!mounted || _dragging || !_playing) return;
      setState(() => _position = position);
    });
    _sourceSub = player.onSource.listen((source) {
      if (!mounted) return;
      final mine = source != null && source == _source;
      if (mine) {
        setState(() => _playing = true);
        return;
      }
      // 换到别人 / 停了:复位在播、进度与倍速(见类注释的第三条)。
      if (_playing || _rate != 1.0 || _position != Duration.zero) {
        setState(() {
          _playing = false;
          _rate = 1.0;
          _position = Duration.zero;
          _dragging = false;
        });
      }
    });
  }

  @override
  void dispose() {
    _completeSub?.cancel();
    _positionSub?.cancel();
    _sourceSub?.cancel();
    super.dispose();
  }

  Future<void> _toggle() async {
    final player = ref.read(voicePlayerProvider);
    if (_playing) {
      await player.stop();
      if (mounted) {
        setState(() {
          _playing = false;
          _position = Duration.zero;
        });
      }
      return;
    }
    if (_source.isEmpty) return;
    setState(() {
      _playing = true;
      _position = Duration.zero;
    });
    try {
      await player.play(_source, isLocal: _isLocal);
      // 每次开始播放都按**本条气泡**的倍速设一遍:换条播放时新气泡的倍速是 1.0,
      // 正好把上一条留下的 2.0x 复位。
      await player.setRate(_rate);
    } catch (_) {
      // 地址失效 / 本地文件没了:退回未播状态,不给「点了没反应还亮着暂停」的假象。
      if (!mounted) return;
      setState(() => _playing = false);
    }
  }

  /// 点倍速按钮:1.0x → 1.5x → 2.0x → 1.0x。
  Future<void> _cycleRate() async {
    final index = rates.indexOf(_rate);
    final next = rates[(index + 1) % rates.length];
    setState(() => _rate = next);
    await ref.read(voicePlayerProvider).setRate(next);
  }

  /// 松手后跳转。
  ///
  /// Args:
  ///   seconds: 滑块上的目标位置(秒)。
  Future<void> _seekTo(double seconds) async {
    final target = Duration(milliseconds: (seconds * 1000).round());
    setState(() => _position = target);
    await ref.read(voicePlayerProvider).seek(target);
  }

  /// 播放中显示剩余、停止时显示总时长(微信口径:一眼知道「这条多长」)。
  String _timeLabel() {
    final total = _totalSeconds.round();
    if (!_playing) return '$total″';
    final left = total - _position.inMilliseconds / 1000;
    return '${left.ceil().clamp(0, total)}″';
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    final seconds = _totalSeconds.round();
    final width = (110 + seconds * 2).clamp(150, 240).toDouble();
    final foreground = widget.message.isSelf ? Colors.white : colors.text1;
    final active = widget.message.isSelf ? Colors.white : colors.brand;
    final inactive =
        widget.message.isSelf ? Colors.white.withValues(alpha: .3) : colors.divider;
    final value = (_dragging ? _dragSeconds : _position.inMilliseconds / 1000)
        .clamp(0.0, _totalSeconds);
    return Container(
      width: width,
      padding: const EdgeInsets.fromLTRB(
          AppSpacing.sm, AppSpacing.xs, AppSpacing.sm, AppSpacing.xs),
      decoration: BoxDecoration(
        color: widget.message.isSelf ? colors.brand : colors.bgCard,
        borderRadius: BorderRadius.circular(AppRadius.bubble),
      ),
      child: Row(
        children: [
          GestureDetector(
            key: const Key('voice.bubble'),
            behavior: HitTestBehavior.opaque,
            onTap: _toggle,
            child: SizedBox(
              width: 28,
              height: 28,
              child: Icon(
                _playing ? Icons.pause_rounded : Icons.play_arrow_rounded,
                key: const Key('voice.play'),
                size: 20,
                color: foreground,
              ),
            ),
          ),
          Expanded(
            child: SliderTheme(
              // 气泡里地方小:轨道细、滑块小,不然一根粗条把秒数挤没了。
              data: SliderTheme.of(context).copyWith(
                trackHeight: 2,
                thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 6),
                overlayShape: const RoundSliderOverlayShape(overlayRadius: 12),
                activeTrackColor: active,
                inactiveTrackColor: inactive,
                thumbColor: active,
              ),
              child: Slider(
                key: const Key('chat.voice.slider'),
                value: value,
                max: _totalSeconds,
                // 按下即进入「拖动」:这期间不跟播放进度走(见类注释)。
                onChangeStart: (next) => setState(() {
                  _dragging = true;
                  _dragSeconds = next;
                }),
                onChanged: (next) => setState(() => _dragSeconds = next),
                onChangeEnd: (next) {
                  setState(() => _dragging = false);
                  unawaited(_seekTo(next));
                },
              ),
            ),
          ),
          Text(
            _timeLabel(),
            key: const Key('chat.voice.time'),
            style: AppText.micro.copyWith(color: foreground),
          ),
          GestureDetector(
            key: const Key('chat.voice.rate'),
            behavior: HitTestBehavior.opaque,
            onTap: _cycleRate,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xs),
              child: Text(
                '${_rate}x',
                style: AppText.micro.copyWith(
                  color: foreground,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
