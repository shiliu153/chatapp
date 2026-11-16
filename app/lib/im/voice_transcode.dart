import 'dart:async';

import '../core/api_exception.dart';

/// 语音转码三态(`docs/api/im.md` §6.5 与 `docs/api/users.md` §2.13 同一套)。
///
/// M-3 起服务端把「抢不到转码槽」的上传改成异步:上传接口回 `202 + status=pending`,
/// 客户端按 `retry_after` 轮询状态接口,直到 `ready`(拿到可播放地址)或 `failed`。
enum VoiceTranscodeStatus { pending, ready, failed }

/// 解析契约里的 `status` 字符串;认不出来时按 [VoiceTranscodeStatus.pending] 处理。
///
/// 为什么未知值不当成 `failed`:老服务端 / 未来新增中间态都可能带出没见过的值,
/// 立刻判死等于把「还没转完」误报成「失败」;按 pending 走,轮询次数用尽会自然收敛成
/// 超时提示,不会卡住界面。
VoiceTranscodeStatus voiceTranscodeStatusOf(Object? raw) => switch (raw) {
      'ready' => VoiceTranscodeStatus.ready,
      'failed' => VoiceTranscodeStatus.failed,
      _ => VoiceTranscodeStatus.pending,
    };

/// 上传被受理(202)时服务端给的排队信息:`id` 用来轮询,`retry_after` 是建议间隔。
///
/// 形状见 `docs/api/im.md` §6.4 与 `docs/api/users.md` §2.11 的「响应参数(202)」。
class VoiceQueued {
  const VoiceQueued({required this.id, this.retryAfter = defaultRetryAfter});

  /// 默认轮询间隔(契约:服务端默认也是 5 秒)。
  static const defaultRetryAfter = Duration(seconds: 5);

  /// 从 202 响应体解析;`id` 缺失或不是整数时返回 null(调用方按失败处理)。
  static VoiceQueued? parse(Object? json) {
    if (json is! Map) return null;
    final id = json['id'];
    if (id is! int) return null;
    final seconds = json['retry_after'];
    return VoiceQueued(
      id: id,
      retryAfter: seconds is int && seconds > 0
          ? Duration(seconds: seconds)
          : defaultRetryAfter,
    );
  }

  final int id;
  final Duration retryAfter;
}

/// 上传结果:要么同步完成(直接可播放),要么已受理排队转码(只有 id)。
///
/// 聊天语音([ChatVoiceUpload])与资料语音(`VoiceIntro`)共用这一个壳,轮询链路因此只写一份。
sealed class VoiceUploadOutcome<T> {
  const VoiceUploadOutcome();
}

/// 同步路径(`201`):文件已转码落盘,可以直接用。
class VoiceUploadDone<T> extends VoiceUploadOutcome<T> {
  const VoiceUploadDone(this.value);

  final T value;
}

/// 异步路径(`202`):转码排队中,要按 [retryAfter] 轮询状态接口。
class VoiceUploadQueued<T> extends VoiceUploadOutcome<T> {
  const VoiceUploadQueued({required this.id, required this.retryAfter});

  final int id;
  final Duration retryAfter;
}

/// 转码状态接口的响应体(`GET /im/voices/{voice_id}` 与 `GET /users/me/voice` 同形)。
///
/// `pending` / `failed` 时 `url`、`durationMs`、`size` 都是 null;`failed` 的失败原因走
/// [code](业务码,如 `41301` 存储已满)或 [message](可直接展示的中文短文案)。
class VoiceTranscode {
  const VoiceTranscode({
    required this.id,
    required this.status,
    this.url,
    this.durationMs,
    this.size,
    this.code,
    this.message,
  });

  /// 解析状态接口响应;不是对象时返回 null(调用方按「查不到」处理)。
  static VoiceTranscode? parse(Object? json) {
    if (json is! Map) return null;
    return VoiceTranscode(
      id: (json['id'] as num?)?.toInt() ?? 0,
      status: voiceTranscodeStatusOf(json['status']),
      url: json['url'] as String?,
      durationMs: (json['duration_ms'] as num?)?.toInt(),
      size: (json['size'] as num?)?.toInt(),
      code: json['code'] as String?,
      message: json['message'] as String?,
    );
  }

  final int id;
  final VoiceTranscodeStatus status;

  /// `ready` 时的可播放地址(限时签名);否则 null。
  final String? url;

  /// `ready` 时的实测时长(毫秒);否则 null。
  final int? durationMs;

  /// `ready` 时的文件字节数;否则 null。
  final int? size;

  /// `failed` 时的业务码(如 `41301`);否则 null。
  final String? code;

  /// `failed` 时可展示的中文提示;否则 null。
  final String? message;

  /// 是否已经可以播放。
  bool get isReady => status == VoiceTranscodeStatus.ready;

  /// 是否已经失败(需要用户重录)。
  bool get isFailed => status == VoiceTranscodeStatus.failed;
}

/// 转码失败:轮询拿到 `failed`,或轮询本身超时。
///
/// 单独一个类型而不是复用 [ApiException]:它不是一次 HTTP 请求失败,而是「上传已经收下了、
/// 转码没成」,UI 要提示的是「重录 / 重试」而不是「网络异常」。
class VoiceTranscodeException implements Exception {
  const VoiceTranscodeException(this.message, {this.code});

  /// 可直接展示给用户的中文文案。
  final String message;

  /// 服务端业务码(如 `41301`);没有则为 null。
  final String? code;

  @override
  String toString() => 'VoiceTranscodeException($code): $message';
}

/// 转码进度回调:上传器在服务端把本次上传受理为「排队转码」时回调一次。
///
/// [cancelled] 由页面提供 —— 用户离开页面后轮询要在下一个检查点收工,否则会白烧
/// 480 次/小时 的轮询额度,且回来时对着一堆没人看的状态。
class VoiceTranscodeHook {
  const VoiceTranscodeHook({this.onQueued, this.cancelled});

  /// 受理回调:`voiceId` 是轮询要用的主键,`retryAfter` 是服务端建议的间隔。
  final void Function(int voiceId, Duration retryAfter)? onQueued;

  /// 是否已经不需要继续轮询(页面已离开 / 会话已切换)。
  final bool Function()? cancelled;
}

/// 轮询的三种结局。
enum VoicePollOutcome {
  /// 拿到终态(`ready` / `failed`)。
  settled,

  /// 服务端说「没有这条语音」(资料语音的 404):不是错误,是「没录过」。
  missing,

  /// 取消了,或轮询次数用尽。
  aborted,
}

/// [VoiceTranscodePoller.run] 的结果。
class VoicePollResult {
  const VoicePollResult._(this.outcome, [this.status]);

  const VoicePollResult.settled(VoiceTranscode status) : this._(VoicePollOutcome.settled, status);

  const VoicePollResult.missing() : this._(VoicePollOutcome.missing);

  const VoicePollResult.aborted() : this._(VoicePollOutcome.aborted);

  final VoicePollOutcome outcome;

  /// 仅 [VoicePollOutcome.settled] 时有值。
  final VoiceTranscode? status;
}

/// 语音转码轮询器:按 `retry_after` 查状态接口,直到 `ready` / `failed`。
///
/// 三条口径(见 issue #400 验收口径):
/// - **轮询本身失败(网络 / 5xx)不判死**:退避后重试,连续失败超过 [maxConsecutiveErrors]
///   才把异常抛给调用方;
/// - **4xx 立刻抛**:404 / 403 / 429 之类重试没有意义(429 除外,它自带退避语义),原地重试
///   只会白烧限流额度;
/// - **可取消**:[cancelled] 每轮检查一次,页面离开即收工。
///
/// [sleep] 与 [fetch] 都可注入:单测里用假时钟(或直接 no-op)驱动,不必真等 5 秒。
class VoiceTranscodePoller {
  const VoiceTranscodePoller({
    required this.fetch,
    this.cancelled,
    this.sleep,
    this.maxAttempts = defaultMaxAttempts,
    this.maxConsecutiveErrors = defaultMaxConsecutiveErrors,
    this.backoffCap = defaultBackoffCap,
  });

  /// 轮询次数上限:默认 60 次 × 5 秒 ≈ 5 分钟,足够覆盖最慢的一次转码排队。
  static const defaultMaxAttempts = 60;

  /// 连续失败上限:5 次(带指数退避)后判死,避免网络断了还无限重试。
  static const defaultMaxConsecutiveErrors = 5;

  /// 失败退避的上限,免得退到几分钟一次。
  static const defaultBackoffCap = Duration(seconds: 30);

  /// 查一次状态;返回 null 表示「没有这条语音」(不重试,直接收工)。
  final Future<VoiceTranscode?> Function() fetch;

  /// 是否已取消。
  final bool Function()? cancelled;

  /// 等待实现;默认真实 `Future.delayed`,测试里换成 no-op 或假时钟。
  final Future<void> Function(Duration delay)? sleep;

  final int maxAttempts;
  final int maxConsecutiveErrors;
  final Duration backoffCap;

  /// 开始轮询,直到终态 / 没有这条语音 / 取消 / 次数用尽。
  ///
  /// Args:
  ///   retryAfter: 首轮间隔(202 响应里的 `retry_after`);不传用 5 秒。
  ///
  /// Returns:
  ///   三选一的 [VoicePollResult];连续失败超限时把原始异常抛出去。
  Future<VoicePollResult> run({Duration? retryAfter}) async {
    var interval = retryAfter ?? VoiceQueued.defaultRetryAfter;
    var errors = 0;
    for (var attempt = 0; attempt < maxAttempts; attempt++) {
      if (cancelled?.call() ?? false) return const VoicePollResult.aborted();
      try {
        final status = await fetch();
        if (status == null) return const VoicePollResult.missing();
        errors = 0;
        if (status.status != VoiceTranscodeStatus.pending) {
          return VoicePollResult.settled(status);
        }
      } on ApiException catch (error) {
        // 4xx(429 除外)重试无意义;5xx / 网络错误才值得退避后再来
        final code = error.statusCode;
        if (code != null && code >= 400 && code < 500 && code != 429) rethrow;
        errors++;
        if (errors > maxConsecutiveErrors) rethrow;
        interval = _backoff(interval);
      } catch (_) {
        errors++;
        if (errors > maxConsecutiveErrors) rethrow;
        interval = _backoff(interval);
      }
      if (attempt == maxAttempts - 1) break;
      await (sleep ?? Future<void>.delayed)(interval);
    }
    return const VoicePollResult.aborted();
  }

  /// 失败退避:间隔翻倍,但不超过 [backoffCap]。
  Duration _backoff(Duration current) {
    final next = current * 2;
    return next > backoffCap ? backoffCap : next;
  }
}

/// 轮询资料语音 / 聊天语音共用的默认文案。
const String voiceTranscodePendingText = '处理中';
const String voiceTranscodeFailedText = '语音转码失败,请重试';
const String voiceTranscodeTimeoutText = '语音转码超时,请重试';
const String voiceTranscodeMissingText = '语音已不存在,请重新录制';

/// 统一把「轮询结束但没有可播放结果」翻译成一句中文提示(UI 直接用)。
///
/// Args:
///   result: [VoiceTranscodePoller.run] 的结果。
///
/// Returns:
///   `settled` 且失败时用服务端 message(没有就用 [voiceTranscodeFailedText]);
///   `missing` 用 [voiceTranscodeMissingText];`aborted` 用 [voiceTranscodeTimeoutText]。
String voicePollFailureText(VoicePollResult result) => switch (result.outcome) {
      VoicePollOutcome.settled =>
        result.status?.message ?? voiceTranscodeFailedText,
      VoicePollOutcome.missing => voiceTranscodeMissingText,
      VoicePollOutcome.aborted => voiceTranscodeTimeoutText,
    };
