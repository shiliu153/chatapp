import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/theme/heart_theme_context.dart';
import '../../chat/voice_playback.dart';
import '../models.dart';

/// 资料语音播放条:播放/暂停 + 进度 + 时长。
///
/// 编辑资料页(本地文件试听 / 已保存语音)与他人资料页(公开地址)共用:
/// 播放走全局 [voicePlayerProvider](与聊天气泡同一个播放器,同一时刻只播一条)。
class VoiceIntroBar extends ConsumerStatefulWidget {
  const VoiceIntroBar({
    super.key,
    required this.source,
    required this.durationMs,
    this.isLocal = false,
    this.keyPrefix = 'voice',
  });

  /// 播放源:本地临时文件路径,或服务端给的公开绝对地址。
  final String source;

  /// 服务端实测时长(毫秒)。
  final int durationMs;

  /// [source] 是本地文件(刚录完还没上传)时为 true。
  final bool isLocal;

  /// 测试 key 前缀(`{prefix}.play` / `{prefix}.progress` / `{prefix}.hint`)。
  final String keyPrefix;

  @override
  ConsumerState<VoiceIntroBar> createState() => _VoiceIntroBarState();
}

class _VoiceIntroBarState extends ConsumerState<VoiceIntroBar> {
  VoicePlayer? _player;
  StreamSubscription<void>? _completeSub;
  StreamSubscription<Duration>? _positionSub;
  bool _playing = false;
  bool _failed = false;
  Duration _position = Duration.zero;

  @override
  void dispose() {
    _completeSub?.cancel();
    _positionSub?.cancel();
    // 离开页面就停:资料页/编辑页退出后不该继续出声(播放器是全局单例)。
    if (_playing) unawaited(_player?.stop() ?? Future<void>.value());
    super.dispose();
  }

  /// 首次播放时才取播放器并挂监听:没点过播放就不构造设备播放器(测试/暗色巡检友好)。
  VoicePlayer _ensurePlayer() {
    final VoicePlayer player = _player ?? ref.read(voicePlayerProvider);
    _player = player;
    _completeSub ??= player.onComplete.listen((_) {
      if (!mounted) return;
      setState(() {
        _playing = false;
        _position = Duration.zero;
      });
    });
    _positionSub ??= player.onPosition.listen((position) {
      if (!mounted) return;
      setState(() => _position = position);
    });
    return player;
  }

  Future<void> _toggle() async {
    final player = _ensurePlayer();
    if (_playing) {
      await player.stop();
      if (!mounted) return;
      setState(() {
        _playing = false;
        _position = Duration.zero;
      });
      return;
    }
    if (widget.source.isEmpty) {
      setState(() => _failed = true);
      return;
    }
    setState(() {
      _failed = false;
      _playing = true;
      _position = Duration.zero;
    });
    try {
      await player.play(widget.source, isLocal: widget.isLocal);
    } catch (_) {
      // 加载失败(地址 404 / 签名过期 / 本地文件没了):给出可重试的失败态。
      if (!mounted) return;
      setState(() {
        _playing = false;
        _failed = true;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    final totalMs = widget.durationMs <= 0 ? 0 : widget.durationMs;
    final progress =
        totalMs <= 0 ? 0.0 : (_position.inMilliseconds / totalMs).clamp(0.0, 1.0);
    final elapsed = _position.inMilliseconds > totalMs ? totalMs : _position.inMilliseconds;
    return Row(
      children: [
        GestureDetector(
          key: Key('${widget.keyPrefix}.play'),
          behavior: HitTestBehavior.opaque,
          onTap: _toggle,
          child: Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: _failed ? colors.divider : colors.brand.withValues(alpha: .12),
              shape: BoxShape.circle,
            ),
            child: Icon(
              _failed
                  ? Icons.refresh_rounded
                  : (_playing ? Icons.pause_rounded : Icons.play_arrow_rounded),
              size: 22,
              color: _failed ? colors.text2 : colors.brand,
            ),
          ),
        ),
        const SizedBox(width: AppSpacing.md),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                key: Key('${widget.keyPrefix}.progress'),
                height: 4,
                width: double.infinity,
                child: Stack(
                  children: [
                    Container(
                      decoration: BoxDecoration(
                        color: colors.divider,
                        borderRadius: BorderRadius.circular(2),
                      ),
                    ),
                    FractionallySizedBox(
                      widthFactor: progress,
                      child: Container(
                        decoration: BoxDecoration(
                          color: colors.brand,
                          borderRadius: BorderRadius.circular(2),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: AppSpacing.sm),
              Text(
                _failed
                    ? '播放失败,点击重试'
                    : '${formatVoiceDuration(elapsed)} / ${formatVoiceDuration(totalMs)}',
                key: Key('${widget.keyPrefix}.hint'),
                style: AppText.micro.copyWith(
                    color: _failed ? colors.danger : colors.text2),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
