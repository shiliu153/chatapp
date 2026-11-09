import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_exception.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/theme/heart_colors.dart';
import '../../../core/theme/heart_theme_context.dart';
import '../../../core/widgets/app_dialog.dart';
import '../../../core/widgets/app_section_card.dart';
import '../../../core/widgets/app_toast.dart';
import '../../../im/voice_recorder.dart';
import '../profile_controller.dart';
import '../profile_voice_controller.dart';
import '../profile_voice_io.dart';
import 'voice_intro_bar.dart';

/// 编辑资料页的「语音自我介绍」卡(批次 R)。
///
/// 交互:按住麦克风录音(最长 30 秒自动停)→ 本地试听/重录/保存 → 上传成功后
/// 变成「已保存」(试听/删除/按住重录)。录音状态机在 [ProfileVoiceController],
/// 播放条是 [VoiceIntroBar];本组件只负责排版与提示。
class ProfileVoiceCard extends ConsumerStatefulWidget {
  const ProfileVoiceCard({super.key});

  @override
  ConsumerState<ProfileVoiceCard> createState() => _ProfileVoiceCardState();
}

class _ProfileVoiceCardState extends ConsumerState<ProfileVoiceCard> {
  late final ProfileVoiceController _voice;

  @override
  void initState() {
    super.initState();
    final io = ref.read(profileVoiceIoProvider);
    _voice = ProfileVoiceController(
      recorder: ref.read(voiceRecorderProvider),
      tempPath: ref.read(voiceTempPathProvider),
      onUpload: (path) async {
        final bytes = await io.read(path);
        return ref.read(profileProvider.notifier).uploadVoice(bytes, 'intro.m4a');
      },
      onDelete: () => ref.read(profileProvider.notifier).deleteVoice(),
      deleteFile: io.delete,
      onNotice: (message) {
        if (mounted) AppToast.show(context, message);
      },
      // 进入页面时服务端已有的语音(没有就是 null,不是空对象)
      initialVoice: ref.read(profileProvider).value?.voice,
    )..addListener(_onVoiceChanged);
  }

  void _onVoiceChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _voice
      ..removeListener(_onVoiceChanged)
      ..dispose();
    super.dispose();
  }

  Future<void> _upload() async {
    try {
      await _voice.upload();
      if (!mounted) return;
      AppToast.show(context, '语音已保存');
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    }
  }

  Future<void> _delete() async {
    final confirmed = await showConfirmDialog(
      context,
      title: '删除语音自我介绍?',
      message: '删除后别人就听不到这段语音了,可以重新录。',
      confirmLabel: '删除',
      danger: true,
      confirmKey: const Key('edit.voice.delete.confirm'),
    );
    if (confirmed != true) return;
    try {
      await _voice.remove();
      if (!mounted) return;
      AppToast.show(context, '已删除');
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    final phase = _voice.phase;
    final recording = phase == ProfileVoicePhase.recording;
    return AppSectionCard(
      title: '语音自我介绍',
      children: [
        Text(
          '录一段最长 ${_voice.maxSeconds} 秒的自我介绍,任何能看你资料的人都能听。',
          style: AppText.caption.copyWith(color: colors.text2),
        ),
        Row(
          children: [
            _RecordButton(
              recording: recording,
              enabled: phase != ProfileVoicePhase.uploading,
              onStart: _voice.start,
              onEnd: _voice.stop,
            ),
            const SizedBox(width: AppSpacing.md),
            Expanded(child: _status(context, phase)),
          ],
        ),
        if (recording) _recordingProgress(colors),
        if (phase == ProfileVoicePhase.recorded || phase == ProfileVoicePhase.uploading) ...[
          VoiceIntroBar(
            source: _voice.localPath ?? '',
            durationMs: _voice.localDurationMs,
            isLocal: true,
            keyPrefix: 'edit.voice.local',
          ),
          Row(
            children: [
              Expanded(
                child: _TextButton(
                  buttonKey: const Key('edit.voice.cancel'),
                  label: '取消',
                  onPressed: _voice.busy ? null : _voice.discardLocal,
                ),
              ),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: _TextButton(
                  buttonKey: const Key('edit.voice.upload'),
                  label: _voice.busy ? '上传中…' : '保存语音',
                  primary: true,
                  onPressed: _voice.busy ? null : _upload,
                ),
              ),
            ],
          ),
        ],
        if (phase == ProfileVoicePhase.saved) ...[
          VoiceIntroBar(
            source: _voice.voice?.url ?? '',
            durationMs: _voice.voice?.durationMs ?? 0,
            keyPrefix: 'edit.voice.saved',
          ),
          Align(
            alignment: Alignment.centerLeft,
            child: _TextButton(
              buttonKey: const Key('edit.voice.delete'),
              label: '删除语音',
              danger: true,
              onPressed: _delete,
            ),
          ),
        ],
      ],
    );
  }

  /// 麦克风旁的文案:按住录音 / 倒计时 / 上传中 / 已保存(时长)。
  Widget _status(BuildContext context, ProfileVoicePhase phase) {
    final colors = context.heart;
    final (text, color) = switch (phase) {
      ProfileVoicePhase.recording => ('还剩 ${_voice.remainingSeconds} 秒', colors.brand),
      ProfileVoicePhase.uploading => ('正在上传…', colors.text2),
      ProfileVoicePhase.recorded => ('已录好 ${_voice.localDurationMs ~/ 1000} 秒,可试听或保存',
          colors.text1),
      ProfileVoicePhase.saved => ('已保存 ${_voice.voice?.durationLabel ?? ''}', colors.text1),
      ProfileVoicePhase.idle => ('按住麦克风录音,最长 ${_voice.maxSeconds} 秒', colors.text2),
    };
    return Text(
      text,
      key: phase == ProfileVoicePhase.recording
          ? const Key('edit.voice.timer')
          : const Key('edit.voice.status'),
      style: AppText.caption.copyWith(color: color),
    );
  }

  /// 录制进度:已录时长占 30 秒的比例(替代波形,零动画、可回归)。
  Widget _recordingProgress(HeartColors colors) {
    final total = _voice.maxSeconds;
    final factor = total <= 0 ? 0.0 : (_voice.seconds / total).clamp(0.0, 1.0);
    return SizedBox(
      key: const Key('edit.voice.progress'),
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
            widthFactor: factor,
            child: Container(
              decoration: BoxDecoration(
                color: colors.brand,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 录音按钮:按住录、松手停。始终挂在树上(录制中不换 widget),
/// 否则手势识别器会被销毁,`onLongPressEnd` 收不到。
class _RecordButton extends StatelessWidget {
  const _RecordButton({
    required this.recording,
    required this.enabled,
    required this.onStart,
    required this.onEnd,
  });

  final bool recording;
  final bool enabled;
  final VoidCallback onStart;
  final VoidCallback onEnd;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    final color = !enabled
        ? colors.text3
        : (recording ? colors.brand : colors.text2);
    return GestureDetector(
      key: const Key('edit.voice.mic'),
      behavior: HitTestBehavior.opaque,
      onLongPressStart: enabled ? (_) => onStart() : null,
      onLongPressEnd: enabled ? (_) => onEnd() : null,
      child: Container(
        width: 44,
        height: 44,
        decoration: BoxDecoration(
          color: recording ? colors.brand.withValues(alpha: .12) : colors.divider,
          shape: BoxShape.circle,
        ),
        child: Icon(
          recording ? Icons.mic_rounded : Icons.mic_none_rounded,
          size: 24,
          color: color,
        ),
      ),
    );
  }
}

/// 卡内小按钮(次要/主要/危险三种),高度 40、胶囊圆角,走「心跳」token。
class _TextButton extends StatelessWidget {
  const _TextButton({
    required this.buttonKey,
    required this.label,
    required this.onPressed,
    this.primary = false,
    this.danger = false,
  });

  final Key buttonKey;
  final String label;
  final VoidCallback? onPressed;
  final bool primary;
  final bool danger;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    final disabled = onPressed == null;
    final foreground = disabled
        ? colors.text3
        : (danger ? colors.danger : (primary ? colors.brand : colors.text1));
    return GestureDetector(
      key: buttonKey,
      behavior: HitTestBehavior.opaque,
      onTap: onPressed,
      child: Container(
        height: 40,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: primary && !disabled ? colors.brand.withValues(alpha: .12) : colors.bgCard,
          borderRadius: BorderRadius.circular(AppRadius.full),
          border: Border.all(color: disabled ? colors.divider : foreground.withValues(alpha: .5)),
        ),
        child: Text(label, style: AppText.caption.copyWith(color: foreground)),
      ),
    );
  }
}
