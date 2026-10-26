import 'dart:io';

import 'package:dio/dio.dart';

import '../core/api_client.dart';

/// 聊天图片上传结果,字段与 `POST /api/v1/im/images` 的响应一一对应。
class ChatImageUpload {
  const ChatImageUpload({
    required this.id,
    required this.url,
    required this.thumbUrl,
    required this.width,
    required this.height,
    required this.size,
  });

  final int id;
  final String url;
  final String thumbUrl;
  final int width;
  final int height;
  final int size;

  /// 组装 WS `send` 帧里的 `image` 载荷(与 imserver 约定同形)。
  Map<String, dynamic> toPayload() => {
        'url': url,
        'thumb_url': thumbUrl,
        'width': width,
        'height': height,
        'size': size,
      };
}

/// 上传器抽象:自建 IM 的图片要先经 Django 落盘,再发 WS 消息。
abstract class SelfImageUploader {
  Future<ChatImageUpload> upload(String localPath);
}

/// 走 Django 的上传实现(复用 ApiClient 的 JWT 与刷新通道)。
class ApiImageUploader implements SelfImageUploader {
  ApiImageUploader(this._api);

  final ApiClient _api;

  @override
  Future<ChatImageUpload> upload(String localPath) async {
    final bytes = await File(localPath).readAsBytes();
    final name = localPath.split(Platform.pathSeparator).last;
    final data = await _api.post('/im/images', data: FormData.fromMap({
      'file': MultipartFile.fromBytes(bytes, filename: name),
    })) as Map<String, dynamic>;
    return ChatImageUpload(
      id: data['id'] as int,
      url: data['url'] as String,
      thumbUrl: data['thumb_url'] as String,
      width: data['width'] as int,
      height: data['height'] as int,
      size: data['size'] as int,
    );
  }
}
