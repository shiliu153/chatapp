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

/// 测试用播放器:记录播放源 / 跳转 / 倍速,手动触发「播完」与「进度」。
class FakeVoicePlayer implements VoicePlayer {
  final played = <String>[];
  final stopped = <String>[];
  final _complete = StreamController<void>.broadcast();
  final _position = StreamController<Duration>.broadcast();
  final _source = StreamController<String?>.broadcast();

  /// 置 true 后 [play] 抛错(模拟地址失效 / 加载失败)。
  bool failPlay = false;

  /// 进度条松手触发的跳转(按调用顺序)。
  final seeks = <Duration>[];

  /// 倍速设置流水(按调用顺序,如 `[1.5, 2.0]`)。
  final rates = <double>[];

  @override
  Stream<void> get onComplete => _complete.stream;

  @override
  Stream<Duration> get onPosition => _position.stream;

  @override
  Stream<String?> get onSource => _source.stream;

  /// 最近一次播放是否按本地文件播(资料语音卡试听本地录音时为 true)。
  bool? lastIsLocal;

  @override
  Future<void> play(String source, {required bool isLocal}) async {
    if (failPlay) throw Exception('load failed');
    lastIsLocal = isLocal;
    played.add(source);
    // 真实现的 play 也会广播换源:气泡靠它把「在播」挪到自己身上。
    _source.add(source);
  }

  @override
  Future<void> stop() async {
    if (played.isNotEmpty) stopped.add(played.last);
    _source.add(null);
  }

  @override
  Future<void> seek(Duration position) async => seeks.add(position);

  @override
  Future<void> setRate(double rate) async => rates.add(rate);

  /// 模拟一条播完。
  void finish() => _complete.add(null);

  /// 模拟播放进度回调。
  void emitPosition(Duration position) => _position.add(position);
}
