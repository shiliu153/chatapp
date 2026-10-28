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

/// 测试用播放器:记录播放源,手动触发「播完」。
class FakeVoicePlayer implements VoicePlayer {
  final played = <String>[];
  final stopped = <String>[];
  final _complete = StreamController<void>.broadcast();

  @override
  Stream<void> get onComplete => _complete.stream;

  @override
  Future<void> play(String source, {required bool isLocal}) async => played.add(source);

  @override
  Future<void> stop() async {
    if (played.isNotEmpty) stopped.add(played.last);
  }

  /// 模拟一条播完。
  void finish() => _complete.add(null);
}
