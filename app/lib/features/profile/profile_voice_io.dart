import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';

/// 资料语音的本地文件读写:读取待上传的录音、清理临时文件。
///
/// 为什么抽成 provider:widget 测试跑在 `testWidgets` 的假时钟 zone 里,**真实文件
/// IO 的 Future 不会完成**(`File.readAsBytes()` 永远挂在那里),录音卡的上传/取消
/// 就会卡死。测试里 override 成内存实现即可。
class ProfileVoiceIo {
  const ProfileVoiceIo();

  /// 读本地录音的字节。
  Future<Uint8List> read(String path) => File(path).readAsBytes();

  /// 删临时文件;文件不存在或删不掉都按成功处理(系统会回收临时目录)。
  Future<void> delete(String path) async {
    try {
      final file = File(path);
      if (await file.exists()) await file.delete();
    } catch (_) {
      // 忽略:临时文件删不掉不影响业务
    }
  }
}

/// 全局文件读写;测试里 override 成假实现。
final profileVoiceIoProvider =
    Provider<ProfileVoiceIo>((ref) => const ProfileVoiceIo());

/// 录音时长的时钟;测试里 override 成**可拨动**的假钟。
///
/// 为什么也抽成 provider:[VoiceRecordController] 用「松手时刻 − 按下时刻」算时长
/// (`_now().difference(_startedAt)`),而 2026-11-28 之前测试是靠
/// `runAsync(Future.delayed(1.1s))` **真等墙钟**跨过「最短 1 秒」——
/// CPU 被占满时这个窗口会抖,判定就不稳,于是同一文件单跑时随机挂**不同**的用例。
/// 注入假钟后测试把时间拨过去即可,既不等待也不受机器负载影响。
final profileVoiceClockProvider =
    Provider<DateTime Function()>((ref) => DateTime.now);
