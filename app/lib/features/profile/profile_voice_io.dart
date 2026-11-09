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
