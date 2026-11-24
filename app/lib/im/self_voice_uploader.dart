import 'dart:io';

import 'package:dio/dio.dart';

import '../core/api_client.dart';
import '../core/api_exception.dart';
import 'local_file_name.dart';
import 'upload_idempotency.dart';
import 'voice_transcode.dart';

/// 语音上传结果,字段与 `POST /api/v1/im/voices` 的 `201` 响应一一对应。
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
///
/// 返回的永远是**可播放**的上传结果 —— `202`(排队转码)由实现内部按 `retry_after`
/// 轮询到 `ready` 再说,调用方(WS 发送链路)不需要知道异步这回事。转码失败时抛
/// [VoiceTranscodeException](文案可直接展示)。
abstract class SelfVoiceUploader {
  /// 上传并等到可播放。
  ///
  /// Args:
  ///   localPath: 本地录音文件。
  ///   durationMs: 客户端测得的时长,**服务端会与实测值比对**(差超过 2 秒回 400)。
  ///   hook: 转码进度回调;服务端受理为排队转码时回调 `onQueued`,页面离开时靠
  ///     `cancelled` 让轮询收工。
  Future<ChatVoiceUpload> upload(String localPath, int durationMs,
      {VoiceTranscodeHook? hook});
}

/// 走 Django 的上传实现(复用 ApiClient 的 JWT 与刷新通道)。
///
/// 两条路径(`docs/api/im.md` §6.4):
/// - 抢到转码槽 → `201 + {id,url,duration_ms,size,status:ready}`,直接用;
/// - 槽被占 → `202 + {id,status:pending,retry_after}`,文件已落临时区、转码在 Celery 里排队,
///   这里按 `retry_after` 轮询 §6.5 直到 `ready`(或 `failed`)。
///
/// 上传请求本身带 `Idempotency-Key`(口径 `docs/api/conventions.md`「幂等键」):
/// 同一段录音的所有重试复用同一个 key,服务端据此重放第一次的结果(同一个 `id`),
/// 不再为「响应没回来」的重试多转码一份文件;重录(本地临时路径变了)才是新 key。
/// 轮询是 `GET`,不带幂等键 —— 它只读,重复问没有副作用。
class ApiVoiceUploader implements SelfVoiceUploader {
  /// 参数说明:
  /// - [_api] 业务请求通道(JWT / 刷新都在这一层)。
  /// - [pollRetryAfter] 首轮轮询间隔的兜底(测试里调小,免得真等 5 秒);
  ///   不传就用 202 响应里的 `retry_after`。
  /// - [sleep] 轮询等待;测试里注入 no-op,真实运行走 `Future.delayed`。
  /// - [maxAttempts] 轮询次数上限。
  /// - [keys] 幂等键缓存,缺省每个上传器一份;单测可注入固定种子。
  /// - [retry] 上传的退避重试策略,缺省 [UploadRetry];单测注入假 sleep 免得真等。
  ApiVoiceUploader(
    this._api, {
    this.pollRetryAfter,
    this.sleep,
    this.maxAttempts = VoiceTranscodePoller.defaultMaxAttempts,
    UploadKeyCache? keys,
    UploadRetry? retry,
  })  : _keys = keys ?? UploadKeyCache(),
        _retry = retry ?? UploadRetry();

  final ApiClient _api;

  /// 首轮轮询间隔的兜底(测试里调小,免得真等 5 秒);不传就用 202 响应里的 `retry_after`。
  final Duration? pollRetryAfter;

  /// 轮询等待;测试里注入 no-op,真实运行走 `Future.delayed`。
  final Future<void> Function(Duration delay)? sleep;

  final int maxAttempts;

  final UploadKeyCache _keys;
  final UploadRetry _retry;

  /// 幂等键的作用域就是接口路径(服务端按「接口 + 账号 + key」区分)。
  static const String idempotencyScope = 'im/voices';

  @override
  Future<ChatVoiceUpload> upload(String localPath, int durationMs,
      {VoiceTranscodeHook? hook}) async {
    // 读文件放在重试之外:文件没了再试一百遍也还是没了,该立刻冒泡
    final bytes = await File(localPath).readAsBytes();
    // 文件名按「路径里出现过的分隔符」取,不按本机平台取:Windows 上 `Platform.pathSeparator`
    // 是 `\`,而临时目录 / 部分插件给的路径用 `/` 拼,切不动就会把整条路径当文件名发出去。
    final name = localFileName(localPath);
    final key = _keys.keyFor(idempotencyScope, localPath);
    final data = await _retry.run(
      key,
      // FormData 必须每次重建:multipart 流只能消费一次,复用会发出空文件
      (key) => _api.post('/im/voices',
          headers: {idempotencyKeyHeader: key},
          data: FormData.fromMap({
            // .m4a 不在 mime 包里,不显式声明会退化成 application/octet-stream 被服务端拒绝
            'file': MultipartFile.fromBytes(bytes, filename: name,
                contentType: DioMediaType('audio', 'mp4')),
            'duration_ms': '$durationMs',
          })),
    ) as Map<String, dynamic>;

    // 202 与 201 的判别用响应体里的 `status`:契约里 202 **恒为** status=pending,
    // 201 恒为 ready(docs/api/im.md §6.4)。不走 HTTP 状态码 —— ApiClient 只回 body,
    // 而 body 已经足够区分,少一个耦合面。
    final queued = data['status'] == 'pending' ? VoiceQueued.parse(data) : null;
    if (queued == null) return _uploadOf(data, durationMs);

    hook?.onQueued?.call(queued.id, queued.retryAfter);
    final result = await VoiceTranscodePoller(
      fetch: () => _status(queued.id),
      cancelled: hook?.cancelled,
      sleep: sleep,
      maxAttempts: maxAttempts,
    ).run(retryAfter: pollRetryAfter ?? queued.retryAfter);
    final status = result.status;
    if (result.outcome == VoicePollOutcome.settled && status != null && status.isReady) {
      return ChatVoiceUpload(
        id: status.id == 0 ? queued.id : status.id,
        url: status.url ?? '',
        durationMs: status.durationMs ?? durationMs,
        size: status.size ?? 0,
      );
    }
    throw VoiceTranscodeException(voicePollFailureText(result), code: status?.code);
  }

  /// 查一次聊天语音转码状态(`GET /im/voices/{voice_id}`)。
  ///
  /// Returns:
  ///   状态响应体;404(语音不存在 / 不是本人上传)原样抛 [ApiException],轮询器按 4xx 立即收工。
  Future<VoiceTranscode?> _status(int voiceId) async =>
      VoiceTranscode.parse(await _api.get('/im/voices/$voiceId'));

  /// 解析 `201` 响应体。
  ///
  /// Args:
  ///   data: `POST /im/voices` 的响应体。
  ///   declaredDurationMs: 客户端声明的时长,服务端没回 `duration_ms` 时兜底。
  ChatVoiceUpload _uploadOf(Map<String, dynamic> data, int declaredDurationMs) {
    final url = data['url'] as String?;
    if (url == null || url.isEmpty) {
      throw const VoiceTranscodeException(voiceTranscodeFailedText);
    }
    return ChatVoiceUpload(
      id: (data['id'] as num?)?.toInt() ?? 0,
      url: url,
      durationMs: (data['duration_ms'] as num?)?.toInt() ?? declaredDurationMs,
      size: (data['size'] as num?)?.toInt() ?? 0,
    );
  }
}
