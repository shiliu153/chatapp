import 'package:flutter/foundation.dart';

import '../../im/voice_recorder.dart';
import '../chat/voice_record_controller.dart';
import 'models.dart';

/// 资料语音自我介绍的上限:**30 秒**(聊天语音是 60 秒,见 [voiceChatMaxDurationMs])。
///
/// 与聊天共用同一个 [VoiceRecordController],只把上限当参数传进去 —— 复制一份
/// 30 秒的控制器会让两边的状态机、权限提示、最短时长校验各走一条路。
const int profileVoiceMaxDurationMs = 30000;

/// 资料语音卡的状态机(见 issue #204 验收口径「空闲 → 录制中 → 已录 → 上传中 → 已保存」)。
enum ProfileVoicePhase {
  /// 本地没有录音,服务端也没有语音。
  idle,

  /// 正在录音(松手或到 30 秒自动停)。
  recording,

  /// 本地已录好、还没上传(可试听、重录、上传)。
  recorded,

  /// 正在上传(按钮禁用,失败回到 [recorded],本地录音保留可重试)。
  uploading,

  /// 服务端已有语音(可试听、删除、重录)。
  saved,
}

/// 资料语音卡的状态机:录音复用 [VoiceRecordController](30 秒上限),
/// 自己只管「本地录音 / 上传 / 已保存」这三件事。
///
/// 上传与删除的副作用通过 [onUpload] / [onDelete] 注入:控制器不碰网络,
/// 单测里可以直接塞假实现;页面侧接到 `ProfileController`。
class ProfileVoiceController extends ChangeNotifier {
  ProfileVoiceController({
    required VoiceRecorder recorder,
    required Future<String> Function() tempPath,
    required this.onUpload,
    required this.onDelete,
    required this.deleteFile,
    required void Function(String message) onNotice,
    VoiceIntro? initialVoice,
    DateTime Function()? now,
    int maxDurationMs = profileVoiceMaxDurationMs,
  }) : _voice = initialVoice {
    _phase = initialVoice == null ? ProfileVoicePhase.idle : ProfileVoicePhase.saved;
    _record = VoiceRecordController(
      recorder: recorder,
      tempPath: tempPath,
      maxDurationMs: maxDurationMs,
      now: now,
      onNotice: onNotice,
      // 聊天侧这里是「上传并发送」;资料侧只是把本地文件收下来,等用户点上传。
      onSend: (path, durationMs) async {
        _localPath = path;
        _localDurationMs = durationMs;
      },
    )..addListener(_onRecordChanged);
  }

  /// 上传本地录音(页面侧接到 `ProfileController.uploadVoice`)。
  final Future<VoiceIntro> Function(String path) onUpload;

  /// 删除服务端语音(页面侧接到 `ProfileController.deleteVoice`)。
  final Future<void> Function() onDelete;

  /// 清理本地临时录音(页面侧接到 [ProfileVoiceIo.delete])。
  final Future<void> Function(String path) deleteFile;
  late final VoiceRecordController _record;

  ProfileVoicePhase _phase = ProfileVoicePhase.idle;
  VoiceIntro? _voice;
  String? _localPath;
  int _localDurationMs = 0;

  /// 当前状态。
  ProfileVoicePhase get phase => _phase;

  /// 服务端已有的语音;没录过为 null。
  VoiceIntro? get voice => _voice;

  /// 本地已录好、尚未上传的临时文件;没有则为 null。
  String? get localPath => _localPath;

  /// 本地录音的时长(毫秒)。
  int get localDurationMs => _localDurationMs;

  /// 已录秒数(向上取整)。
  int get seconds => _record.seconds;

  /// 单段上限秒数(30)。
  int get maxSeconds => _record.maxSeconds;

  /// 录制中还剩几秒(倒计时)。
  int get remainingSeconds => (maxSeconds - seconds).clamp(0, maxSeconds);

  /// 是否正在上传(页面据此禁用按钮)。
  bool get busy => _phase == ProfileVoicePhase.uploading;

  /// 转发录音控制器的变化;并兜住「到 30 秒自动停」——那条路径不经过 [stop],
  /// 录音器自己把相位打回 idle,这里据此把本地录音收成「已录」。
  void _onRecordChanged() {
    if (_phase == ProfileVoicePhase.recording && _record.phase == VoicePhase.idle) {
      _phase = _localPath != null
          ? ProfileVoicePhase.recorded
          : (_voice == null ? ProfileVoicePhase.idle : ProfileVoicePhase.saved);
    }
    notifyListeners();
  }

  /// 开始录音;从「已录」状态开始会先丢掉那段本地录音,已保存的语音不受影响。
  Future<void> start() async {
    if (_phase == ProfileVoicePhase.recording || _phase == ProfileVoicePhase.uploading) return;
    await _discardLocalFile();
    _localPath = null;
    _localDurationMs = 0;
    await _record.start();
    _phase = _record.phase == VoicePhase.recording
        ? ProfileVoicePhase.recording
        : (_voice == null ? ProfileVoicePhase.idle : ProfileVoicePhase.saved);
    notifyListeners();
  }

  /// 结束录音:够长就进「已录」(等用户点上传),太短由 [VoiceRecordController] 提示。
  Future<void> stop() async {
    if (_phase != ProfileVoicePhase.recording) return;
    await _record.stopAndSend();
    _phase = _localPath != null
        ? ProfileVoicePhase.recorded
        : (_voice == null ? ProfileVoicePhase.idle : ProfileVoicePhase.saved);
    notifyListeners();
  }

  /// 上传本地录音;失败时回到「已录」并把异常抛给页面(提示用后端 message)。
  Future<void> upload() async {
    final path = _localPath;
    if (path == null || _phase == ProfileVoicePhase.uploading) return;
    _phase = ProfileVoicePhase.uploading;
    notifyListeners();
    try {
      _voice = await onUpload(path);
      _phase = ProfileVoicePhase.saved;
      await _discardLocalFile();
      _localPath = null;
      _localDurationMs = 0;
    } catch (_) {
      // 本地录音留着,用户可以原地重试;网络错误的 message 由页面弹。
      _phase = ProfileVoicePhase.recorded;
      rethrow;
    } finally {
      notifyListeners();
    }
  }

  /// 删除:服务端有语音就调 DELETE,再清掉本地录音;最终回到 [ProfileVoicePhase.idle]。
  ///
  /// 删除失败时异常原样抛出且状态不变(页面提示「删除失败」,播放条还在)。
  Future<void> remove() async {
    if (_phase == ProfileVoicePhase.recording || _phase == ProfileVoicePhase.uploading) return;
    if (_voice != null) {
      await onDelete();
      _voice = null;
    }
    await _discardLocalFile();
    _localPath = null;
    _localDurationMs = 0;
    _phase = ProfileVoicePhase.idle;
    notifyListeners();
  }

  /// 丢弃本地录音(「重新录制」前调用);已保存的语音不动。
  Future<void> discardLocal() async {
    if (_phase == ProfileVoicePhase.recording || _phase == ProfileVoicePhase.uploading) return;
    await _discardLocalFile();
    _localPath = null;
    _localDurationMs = 0;
    _phase = _voice == null ? ProfileVoicePhase.idle : ProfileVoicePhase.saved;
    notifyListeners();
  }

  Future<void> _discardLocalFile() async {
    final path = _localPath;
    if (path == null) return;
    await deleteFile(path);
  }

  @override
  void dispose() {
    _record
      ..removeListener(_onRecordChanged)
      ..dispose();
    super.dispose();
  }
}
