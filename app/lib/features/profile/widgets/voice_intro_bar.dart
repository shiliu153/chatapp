import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/theme/app_typography.dart';
import '../../../core/theme/ember_colors.dart';
import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';
import '../../chat/voice_playback.dart';
import '../models.dart';
import '../profile_component_sizes.dart';

/// 资料语音播放条(E-5.4 page spec §3「语音介绍卡」):播放/暂停 + 进度 + 时长。
///
/// **形态保留、只换皮**(§7 拍板结果 4):结构仍是「圆钮 + 波形条 + 时长文案」,
/// 换掉的是取色(心跳 `colors.brand` → 语义 `brand.default`)、图标(Material
/// `play_arrow_rounded` → Phosphor `play` / `pause`)与动效(按压走 `spring.fast`,
/// 由 [EmberPressable] 提供)。
///
/// 读屏口径(page spec §6 第 3 条):整条读「语音介绍,N 秒」—— 播放键另有自己的
/// 「播放 / 暂停」,两者用 `container` 分层,不会互相顶掉。
///
/// 编辑资料页(本地文件试听 / 已保存语音)与他人资料页(公开地址)共用:
/// 播放走全局 [voicePlayerProvider](与聊天气泡同一个播放器,同一时刻只播一条)。
class VoiceIntroBar extends ConsumerStatefulWidget {
  /// 构造播放条。
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

  /// 读屏播报的时长:毫秒 → 整秒(规范口径是「N 秒」,不念 `0:18`)。
  int get _secondsLabel => (widget.durationMs / 1000).round();

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final totalMs = widget.durationMs <= 0 ? 0 : widget.durationMs;
    final progress = totalMs <= 0
        ? 0.0
        : (_position.inMilliseconds / totalMs).clamp(0.0, 1.0);
    final elapsed = _position.inMilliseconds > totalMs
        ? totalMs
        : _position.inMilliseconds;
    return Row(
      children: [
        EmberPressable(
          key: Key('${widget.keyPrefix}.play'),
          onTap: _toggle,
          pressedScale: 0.97,
          borderRadius: BorderRadius.circular(tokens.radiusPill),
          semanticLabel: _failed ? '重试播放' : (_playing ? '暂停' : '播放'),
          builder: (context, state) => _playButton(colors),
        ),
        SizedBox(width: tokens.space12),
        Expanded(
          // 读屏一句话「语音介绍,N 秒」(page spec §6 第 3 条):时长与进度对
          // 读屏用户是同一件事,合成一条;播放键自己的「播放 / 暂停」不被吞掉。
          child: Semantics(
            container: true,
            excludeSemantics: true,
            label: '语音介绍，$_secondsLabel 秒',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  key: Key('${widget.keyPrefix}.progress'),
                  height: ProfileComponentSizes.voiceWaveHeight,
                  width: double.infinity,
                  child: Stack(
                    children: [
                      DecoratedBox(
                        decoration: BoxDecoration(
                          color: colors.borderDivider,
                          borderRadius: BorderRadius.circular(
                            ProfileComponentSizes.voiceWaveHeight / 2,
                          ),
                        ),
                        child: const SizedBox.expand(),
                      ),
                      FractionallySizedBox(
                        widthFactor: progress,
                        child: DecoratedBox(
                          decoration: BoxDecoration(
                            // 播放中波形高亮 `brand.default`(page spec §4 语音介绍行)。
                            color: colors.brandDefault,
                            borderRadius: BorderRadius.circular(
                              ProfileComponentSizes.voiceWaveHeight / 2,
                            ),
                          ),
                          child: const SizedBox.expand(),
                        ),
                      ),
                    ],
                  ),
                ),
                SizedBox(height: tokens.space8),
                Text(
                  _failed
                      ? '播放失败,点击重试'
                      : '${formatVoiceDuration(elapsed)} / ${formatVoiceDuration(totalMs)}',
                  key: Key('${widget.keyPrefix}.hint'),
                  style: AppText.micro.copyWith(
                    color: _failed ? colors.statusDanger : colors.textSecondary,
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  /// 圆形播放键:触控 48([EmberPressable] 外层撑到 48),可视圆 40。
  Widget _playButton(EmberColors colors) {
    final icon = _failed
        ? PhosphorIconsRegular.arrowClockwise
        : (_playing ? PhosphorIconsFill.pause : PhosphorIconsFill.play);
    final foreground = _failed ? colors.textSecondary : colors.brandDefault;
    return SizedBox(
      width: tokens.sizeTouchApp,
      height: tokens.sizeTouchApp,
      child: Center(
        child: Container(
          width: ProfileComponentSizes.voicePlayDiameter,
          height: ProfileComponentSizes.voicePlayDiameter,
          decoration: BoxDecoration(
            // 底取 `brand.default` @12%(§18.6「光晕 / 强调由组件层算」同一口径)。
            color: _failed
                ? colors.surfaceSunken
                : colors.brandDefault.withValues(alpha: 0.12),
            shape: BoxShape.circle,
          ),
          child: Icon(icon, size: tokens.sizeIcon20, color: foreground),
        ),
      ),
    );
  }
}
