import 'dart:async';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// 语音播放抽象:单例,同一时刻只播一条。
abstract class VoicePlayer {
  /// 播放 [source];[isLocal] 为 true 时按本地文件播放,否则按 URL 播放。
  Future<void> play(String source, {required bool isLocal});

  /// 停止当前播放。
  Future<void> stop();

  /// 一条播完时触发(用于复位气泡图标)。
  Stream<void> get onComplete;

  /// 播放进度;资料语音播放条用它画进度。默认空流:只关心「播没播完」的实现
  /// (聊天气泡)不必实现它。
  Stream<Duration> get onPosition => const Stream<Duration>.empty();
}

/// `audioplayers` 实现。
class DeviceVoicePlayer implements VoicePlayer {
  DeviceVoicePlayer() {
    _player.onPlayerComplete.listen((_) => _complete.add(null));
  }

  final _player = AudioPlayer();
  final _complete = StreamController<void>.broadcast();

  @override
  Stream<void> get onComplete => _complete.stream;

  @override
  Stream<Duration> get onPosition => _player.onPositionChanged;

  @override
  Future<void> play(String source, {required bool isLocal}) async {
    await _player.stop();
    await _player.play(isLocal ? DeviceFileSource(source) : UrlSource(source));
  }

  @override
  Future<void> stop() => _player.stop();
}

/// 全局播放器;测试里 override 成假实现。
final voicePlayerProvider = Provider<VoicePlayer>((ref) {
  final player = DeviceVoicePlayer();
  ref.onDispose(player.stop);
  return player;
});
