import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

/// 录音抽象:测试注入假实现,避免依赖真实麦克风。
abstract class VoiceRecorder {
  /// 是否有麦克风权限(没有时会向系统申请一次)。
  Future<bool> hasPermission();

  /// 开始录音到 [path](m4a)。
  Future<void> start(String path);

  /// 停止录音并返回文件路径;没有录到内容时返回 null。
  Future<String?> stop();

  /// 放弃本次录音并删除文件。
  Future<void> cancel();
}

/// `record` 包实现:AAC-LC / 单声道 16kHz,输出 m4a。
class DeviceVoiceRecorder implements VoiceRecorder {
  final _recorder = AudioRecorder();

  @override
  Future<bool> hasPermission() => _recorder.hasPermission();

  @override
  Future<void> start(String path) => _recorder.start(
        const RecordConfig(
          encoder: AudioEncoder.aacLc,
          bitRate: 64000,
          sampleRate: 16000,
          numChannels: 1,
        ),
        path: path,
      );

  @override
  Future<String?> stop() => _recorder.stop();

  @override
  Future<void> cancel() => _recorder.cancel();
}

/// 全局录音器;测试里 override 成假实现。
final voiceRecorderProvider =
    Provider<VoiceRecorder>((ref) => DeviceVoiceRecorder());

/// 录音文件落在系统临时目录,发送成功或取消后由页面删除。
Future<String> voiceTempPath() async {
  final dir = await getTemporaryDirectory();
  return '${dir.path}${Platform.pathSeparator}voice-'
      '${DateTime.now().microsecondsSinceEpoch}.m4a';
}

/// 临时文件路径工厂;测试里 override 成固定路径(避免依赖 path_provider 插件)。
final voiceTempPathProvider =
    Provider<Future<String> Function()>((ref) => voiceTempPath);
