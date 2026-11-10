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

  /// 播放进度。聊天气泡的进度条与资料语音条的进度都靠它。
  Stream<Duration> get onPosition;

  /// 播放源切换(null = 停 / 播完)。
  ///
  /// 为什么需要它:播放器是**全局单例**,换一条播放时上一条的气泡收不到任何通知 ——
  /// 它的暂停图标会一直亮着,进度条还会跟着新那条的时间走。有了这个流,每个气泡都能
  /// 判断「现在播的还是不是我这条」,不是就把「在播」与倍速一起复位。
  Stream<String?> get onSource;

  /// 跳到 [position](进度条松手时调用)。
  ///
  /// Args:
  ///   position: 目标位置;超过总时长时播放器自己会截到结尾。
  Future<void> seek(Duration position);

  /// 设置倍速(1.0 / 1.5 / 2.0)。
  ///
  /// Args:
  ///   rate: 播放倍速;换条播放前必须复位 1.0,否则新那条会沿用上一条的倍速。
  Future<void> setRate(double rate);
}

/// `audioplayers` 实现。
class DeviceVoicePlayer implements VoicePlayer {
  DeviceVoicePlayer() {
    _player.onPlayerComplete.listen((_) {
      _complete.add(null);
      _source.add(null);
    });
  }

  final _player = AudioPlayer();
  final _complete = StreamController<void>.broadcast();
  final _source = StreamController<String?>.broadcast();

  @override
  Stream<void> get onComplete => _complete.stream;

  @override
  Stream<Duration> get onPosition => _player.onPositionChanged;

  @override
  Stream<String?> get onSource => _source.stream;

  @override
  Future<void> play(String source, {required bool isLocal}) async {
    await _player.stop();
    // 先播报换源、再真的播:气泡靠这一帧把「在播」状态挪到自己身上。
    _source.add(source);
    await _player.play(isLocal ? DeviceFileSource(source) : UrlSource(source));
  }

  @override
  Future<void> stop() async {
    _source.add(null);
    await _player.stop();
  }

  @override
  Future<void> seek(Duration position) => _player.seek(position);

  @override
  Future<void> setRate(double rate) => _player.setPlaybackRate(rate);
}

/// 全局播放器;测试里 override 成假实现。
final voicePlayerProvider = Provider<VoicePlayer>((ref) {
  final player = DeviceVoicePlayer();
  ref.onDispose(player.stop);
  return player;
});
