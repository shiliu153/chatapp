import 'dart:async';

import 'package:chatapp_app/features/chat/voice_playback.dart';
import 'package:chatapp_app/im/voice_recorder.dart';

/// 测试用录音器:不碰麦克风,记录调用并返回固定路径。
class FakeVoiceRecorder implements VoiceRecorder {
  FakeVoiceRecorder({this.path = '/tmp/voice.m4a', this.permission = true});

  final String path;
  bool permission;
  bool started = false;
  bool cancelled = false;
  String? startPath;

  @override
  Future<bool> hasPermission() async => permission;

  @override
  Future<void> start(String path) async {
    started = true;
    startPath = path;
  }

  @override
  Future<String?> stop() async => started ? path : null;

  @override
  Future<void> cancel() async => cancelled = true;
}

/// 测试用播放器:记录播放源,手动触发「播完」与「进度」。
class FakeVoicePlayer implements VoicePlayer {
  final played = <String>[];
  final stopped = <String>[];
  final _complete = StreamController<void>.broadcast();
  final _position = StreamController<Duration>.broadcast();

  /// 置 true 后 [play] 抛错(模拟地址失效 / 加载失败)。
  bool failPlay = false;

  @override
  Stream<void> get onComplete => _complete.stream;

  @override
  Stream<Duration> get onPosition => _position.stream;

  /// 最近一次播放是否按本地文件播(资料语音卡试听本地录音时为 true)。
  bool? lastIsLocal;

  @override
  Future<void> play(String source, {required bool isLocal}) async {
    if (failPlay) throw Exception('load failed');
    lastIsLocal = isLocal;
    played.add(source);
  }

  @override
  Future<void> stop() async {
    if (played.isNotEmpty) stopped.add(played.last);
  }

  /// 模拟一条播完。
  void finish() => _complete.add(null);

  /// 模拟播放进度回调。
  void emitPosition(Duration position) => _position.add(position);
}
