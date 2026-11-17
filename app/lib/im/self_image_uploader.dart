import 'dart:io';

import 'package:dio/dio.dart';

import '../core/api_client.dart';
import 'upload_idempotency.dart';

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
///
/// 每次上传带 `Idempotency-Key`(口径 `docs/api/conventions.md`「幂等键」):
/// 同一张图的**所有重试**(网络抖动 / `429` / `409`+`40901` / `5xx`)复用同一个 key,
/// 服务端据此重放第一次的结果,而不是把同一张图再落一份、白吃存储配额。
/// 换一张图(本地临时路径变了)才会是新 key。
class ApiImageUploader implements SelfImageUploader {
  /// 参数说明:
  /// - [_api] 业务请求通道(JWT / 刷新都在这一层)。
  /// - [keys] 幂等键缓存,缺省每个上传器一份;单测可注入固定种子。
  /// - [retry] 退避重试策略,缺省 [UploadRetry];单测注入假 sleep 免得真等。
  ApiImageUploader(this._api, {UploadKeyCache? keys, UploadRetry? retry})
      : _keys = keys ?? UploadKeyCache(),
        _retry = retry ?? UploadRetry();

  final ApiClient _api;
  final UploadKeyCache _keys;
  final UploadRetry _retry;

  /// 幂等键的作用域就是接口路径(服务端按「接口 + 账号 + key」区分)。
  static const String idempotencyScope = 'im/images';

  @override
  Future<ChatImageUpload> upload(String localPath) async {
    // 读文件放在重试之外:文件没了再试一百遍也还是没了,该立刻冒泡
    final bytes = await File(localPath).readAsBytes();
    final name = localPath.split(Platform.pathSeparator).last;
    final key = _keys.keyFor(idempotencyScope, localPath);
    final data = await _retry.run(
      key,
      // FormData 必须每次重建:multipart 流只能消费一次,复用会发出空文件
      (key) => _api.post('/im/images',
          headers: {idempotencyKeyHeader: key},
          data: FormData.fromMap({
            'file': MultipartFile.fromBytes(bytes, filename: name),
          })),
    ) as Map<String, dynamic>;
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
