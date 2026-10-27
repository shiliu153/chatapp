import 'dart:io';

import 'package:dio/dio.dart';

import '../core/api_client.dart';

/// 语音上传结果,字段与 `POST /api/v1/im/voices` 的响应一一对应。
class ChatVoiceUpload {
  const ChatVoiceUpload({
    required this.id,
    required this.url,
    required this.durationMs,
    required this.size,
  });

  final int id;
  final String url;

  /// 服务端 ffprobe 实测时长(毫秒),可能与客户端声明略有差异。
  final int durationMs;
  final int size;

  /// 组装 WS `send` 帧里的 `voice` 载荷(与 imserver 约定同形)。
  Map<String, dynamic> toPayload() => {
        'url': url,
        'duration_ms': durationMs,
        'size': size,
      };
}

/// 上传器抽象:自建 IM 的语音要先经 Django 转码落盘,再发 WS 消息。
abstract class SelfVoiceUploader {
  Future<ChatVoiceUpload> upload(String localPath, int durationMs);
}

/// 走 Django 的上传实现(复用 ApiClient 的 JWT 与刷新通道)。
class ApiVoiceUploader implements SelfVoiceUploader {
  ApiVoiceUploader(this._api);

  final ApiClient _api;

  @override
  Future<ChatVoiceUpload> upload(String localPath, int durationMs) async {
    final bytes = await File(localPath).readAsBytes();
    final name = localPath.split(Platform.pathSeparator).last;
    final data = await _api.post('/im/voices', data: FormData.fromMap({
      'file': MultipartFile.fromBytes(bytes, filename: name),
      'duration_ms': '$durationMs',
    })) as Map<String, dynamic>;
    return ChatVoiceUpload(
      id: data['id'] as int,
      url: data['url'] as String,
      durationMs: data['duration_ms'] as int,
      size: data['size'] as int,
    );
  }
}
