import 'dart:async';

import 'package:flutter/foundation.dart';

import '../../im/voice_recorder.dart';

/// 录音状态(契约见 docs/superpowers/specs/2026-11-01-voice-recording-interaction-design.md §4)。
enum VoicePhase { idle, requesting, recording, sending }

/// 提示文案:与 Web 端 useVoiceRecorder.ts 的 VOICE_TEXT 逐字对应。
const String voiceTextPermissionDenied = '需要麦克风权限才能发语音';
const String voiceTextNoDevice = '未检测到麦克风';
const String voiceTextUnsupported = '当前浏览器不支持录音（需 HTTPS）';
const String voiceTextStartFailed = '录音启动失败，请重试';
const String voiceTextTooShort = '说话时间太短';
const String voiceTextSendFailed = '语音发送失败，点击重试';

const int _minDurationMs = 1000;
const int _maxDurationMs = 60000;

/// 录音控制器:把原来埋在输入栏里的录音逻辑收拢成可单测的状态机。
///
/// 时间来源可注入([now]),测试里用假时钟驱动「满 1 秒 / 60 秒自动结束」,
/// 不必真的等两秒。
class VoiceRecordController extends ChangeNotifier {
  VoiceRecordController({
    required VoiceRecorder recorder,
    required Future<String> Function() tempPath,
    required void Function(String message) onNotice,
    required Future<void> Function(String path, int durationMs) onSend,
    DateTime Function()? now,
  })  : _recorder = recorder,
        _tempPath = tempPath,
        _onNotice = onNotice,
        _onSend = onSend,
        _now = now ?? DateTime.now;

  final VoiceRecorder _recorder;
  final Future<String> Function() _tempPath;
  final void Function(String message) _onNotice;
  final Future<void> Function(String path, int durationMs) _onSend;
  final DateTime Function() _now;

  VoicePhase _phase = VoicePhase.idle;
  VoicePhase get phase => _phase;

  bool _cancelArmed = false;
  bool get cancelArmed => _cancelArmed;

  DateTime _startedAt = DateTime.fromMillisecondsSinceEpoch(0);
  Timer? _ticker;
  Timer? _autoStop;
  bool _disposed = false;

  /// 已录秒数(向上取整,0–60)。
  int get seconds {
    if (_phase == VoicePhase.idle) return 0;
    final ms = _now().difference(_startedAt).inMilliseconds;
    return (ms / 1000).ceil().clamp(0, 60);
  }

  @override
  void notifyListeners() {
    if (_disposed) return;
    super.notifyListeners();
  }

  /// 开始录音:申请权限 → 启动设备 → 起计时与 60 秒上限。
  Future<void> start() async {
    if (_phase != VoicePhase.idle) return;
    _phase = VoicePhase.requesting;
    notifyListeners();
    if (!await _recorder.hasPermission()) {
      _phase = VoicePhase.idle;
      notifyListeners();
      _onNotice(voiceTextPermissionDenied);
      return;
    }
    final path = await _tempPath();
    try {
      await _recorder.start(path);
    } catch (_) {
      _phase = VoicePhase.idle;
      notifyListeners();
      _onNotice(voiceTextStartFailed);
      return;
    }
    _phase = VoicePhase.recording;
    _cancelArmed = false;
    _startedAt = _now();
    _ticker = Timer.periodic(const Duration(milliseconds: 200), (_) => notifyListeners());
    _autoStop = Timer(const Duration(milliseconds: _maxDurationMs), () {
      unawaited(stopAndSend());
    });
    notifyListeners();
  }

  /// 上滑取消态:由手势层把「是否已滑入取消区」告诉控制器。
  void updateCancelArm(bool armed) {
    if (_cancelArmed == armed) return;
    _cancelArmed = armed;
    notifyListeners();
  }

  /// 结束并发送;不足 1 秒只提示不发送。
  Future<void> stopAndSend() async {
    if (_phase != VoicePhase.recording) return;
    _autoStop?.cancel();
    _ticker?.cancel();
    final durationMs = _now().difference(_startedAt).inMilliseconds;
    if (_cancelArmed) {
      await cancel();
      return;
    }
    _phase = VoicePhase.sending;
    notifyListeners();

    final path = await _recorder.stop();
    if (path == null || durationMs < _minDurationMs) {
      try {
        await _recorder.cancel();
      } catch (_) {}
      _phase = VoicePhase.idle;
      notifyListeners();
      _onNotice(path == null ? voiceTextStartFailed : voiceTextTooShort);
      return;
    }
    try {
      await _onSend(path, durationMs);
    } catch (_) {
      _onNotice(voiceTextSendFailed);
    } finally {
      _phase = VoicePhase.idle;
      notifyListeners();
    }
  }

  /// 丢弃当前录音(取消按钮 / 页面离开)。
  Future<void> cancel() async {
    if (_phase == VoicePhase.idle) return;
    _autoStop?.cancel();
    _ticker?.cancel();
    _cancelArmed = false;
    _phase = VoicePhase.idle;
    try {
      await _recorder.cancel();
    } catch (_) {}
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _autoStop?.cancel();
    _ticker?.cancel();
    // 录音中直接销毁必须停掉设备,否则麦克风会一直采集
    if (_phase == VoicePhase.recording || _phase == VoicePhase.sending) {
      unawaited(_recorder.cancel().catchError((_) {}));
    }
    super.dispose();
  }
}
