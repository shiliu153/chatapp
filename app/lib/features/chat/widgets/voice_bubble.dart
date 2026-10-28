import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_typography.dart';
import '../../../im/im_client.dart';
import '../voice_playback.dart';

/// 语音气泡:宽度随时长增长(60→180),播放/暂停图标 + 秒数。
class VoiceBubble extends ConsumerStatefulWidget {
  const VoiceBubble({super.key, required this.message});

  final ChatMessage message;

  @override
  ConsumerState<VoiceBubble> createState() => _VoiceBubbleState();
}

class _VoiceBubbleState extends ConsumerState<VoiceBubble> {
  bool _playing = false;
  late final StreamSubscription<void> _sub;

  @override
  void initState() {
    super.initState();
    _sub = ref.read(voicePlayerProvider).onComplete.listen((_) {
      if (mounted) setState(() => _playing = false);
    });
  }

  @override
  void dispose() {
    _sub.cancel();
    super.dispose();
  }

  Future<void> _toggle() async {
    final player = ref.read(voicePlayerProvider);
    if (_playing) {
      await player.stop();
      if (mounted) setState(() => _playing = false);
      return;
    }
    final message = widget.message;
    final local = message.localPath;
    final hasLocal = local != null && local.isNotEmpty;
    final source = hasLocal ? local : (message.voiceUrl ?? '');
    if (source.isEmpty) return;
    setState(() => _playing = true);
    await player.play(source, isLocal: hasLocal);
  }

  @override
  Widget build(BuildContext context) {
    final seconds = (widget.message.voiceDurationMs / 1000).round().clamp(1, 60);
    final width = (72 + seconds * 2).clamp(96, 200).toDouble();
    final foreground = widget.message.isSelf ? Colors.white : AppColors.text1;
    return GestureDetector(
      key: const Key('voice.bubble'),
      onTap: _toggle,
      child: Container(
        width: width,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
        decoration: BoxDecoration(
          color: widget.message.isSelf ? AppColors.brand : AppColors.bgCard,
          borderRadius: BorderRadius.circular(AppRadius.bubble),
        ),
        child: Row(
          children: [
            Icon(
              _playing ? Icons.pause_rounded : Icons.play_arrow_rounded,
              key: const Key('voice.play'),
              size: 20,
              color: foreground,
            ),
            const SizedBox(width: 6),
            Text('$seconds″', style: AppText.body.copyWith(color: foreground)),
          ],
        ),
      ),
    );
  }
}
