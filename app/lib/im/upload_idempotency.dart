import 'dart:collection';
import 'dart:math';

import '../core/api_exception.dart';

/// 上传幂等键的请求头名(口径:`docs/api/conventions.md`「幂等键」一节)。
///
/// 只有三个上传接口认它:`POST /im/images`(聊天图)、`POST /im/voices`(聊天语音)、
/// `POST /users/me/voice`(资料语音)。作用域由服务端按「接口 + 账号 + key」区分,
/// 所以同一个 key 用在不同接口 / 不同账号上互不影响,客户端不必自己拼前缀。
const String idempotencyKeyHeader = 'Idempotency-Key';

/// 「同 key 并发、上一次还没处理完」的业务码(`409` + `40901`)。
///
/// 它**不是失败**:服务端只是还没把第一次的结果写完,退避 1–2 秒后用**同一个 key**
/// 再打一次,通常就能拿到第一次完成后的重放结果(同一个 `id`,不会多落一份文件)。
/// 客户端若把它当普通 4xx 立刻冒泡,用户看到的就是「上传失败」,而磁盘上其实已经有一份。
const int idempotencyConflictCode = 40901;

final Random _keyRandom = Random();

/// 进程内序号:兜住「同一微秒内连发」(`DateTime.now()` 在 Windows / 模拟器上分辨率很粗,
/// 同一毫秒里生成两次是常态,单靠时间戳会撞)。
int _keySequence = 0;

/// 生成一个新的一次性上传幂等键。
///
/// 为什么不引 `package:uuid`:`uuid` 只是 `pubspec.lock` 里的传递依赖,`pubspec.yaml`
/// 没有直接依赖它 —— 按工单口径「不新增第三方依赖」,自己拼一个够用的即可。
///
/// 形状 `app-<微秒时间戳>-<36 进制序号>-<6 位十六进制随机>`,字符全落在服务端白名单
/// (`A-Z a-z 0-9 . _ : -`,长度 1–128)内。三段拼在一起的用意:时间戳给跨进程的粗粒度
/// 唯一性,序号兜住同进程同微秒,随机兜住两个进程同时启动。
///
/// 参数说明:
/// - [now] 取时间的注入点,单测用固定时钟驱动;缺省 `DateTime.now`。
/// - [random] 随机源注入点,单测用定种子;缺省进程级 `Random()`。
///
/// 返回参数:
/// - 可直接塞进 [idempotencyKeyHeader] 头的字符串(形如 `app-1758000000123456-1-3f9a2c`)。
String newUploadIdempotencyKey({DateTime Function()? now, Random? random}) {
  final clock = now ?? DateTime.now;
  final micros = clock().microsecondsSinceEpoch;
  final seq = (_keySequence = (_keySequence + 1) & 0xffffff).toRadixString(36);
  final suffix = (random ?? _keyRandom)
      .nextInt(1 << 24)
      .toRadixString(16)
      .padLeft(6, '0');
  return 'app-$micros-$seq-$suffix';
}

/// 「一次用户发起的上传」到「一个幂等键」的映射:同一次上传的所有重试复用同一个 key,
/// 换图 / 重录(本地来源变了)才换新 key。
///
/// 为什么不能「每次调用上传器都新生成一个 key」:重试不只在一次调用内部发生 ——
/// 聊天图片上传成功但 WS 帧没送达时,用户点「重发」会再调一次上传;若换了新 key,
/// 服务端就把同一张图又落一盘,正好是幂等键要消除的那份孤儿文件。所以身份取「本地来源」:
/// 选图 / 录音产生的临时路径每次都是新的,同一路径重试 = 同一次上传。
///
/// 只保留最近 [maxEntries] 条(进程内 LRU,不落盘):服务端映射 24 小时后过期,
/// 过期后再复用同一个 key 最多变成一次「新上传」;进程重启后重新生成的 key 同理。
/// 幂等键是尽力而为的去重,不是正确性依赖。
class UploadKeyCache {
  /// 参数说明:
  /// - [maxEntries] 最多记住多少条(至少 1),超出丢弃最久没用的那条。
  /// - [now] / [random] 透传给 [newUploadIdempotencyKey] 的注入点,单测用。
  UploadKeyCache({this.maxEntries = 32, this._now, this._random});

  /// 最多记住多少条。
  final int maxEntries;

  final DateTime Function()? _now;
  final Random? _random;

  /// 键是 `scope + 分隔符 + source`,分隔符用 `\u0000` 防止两个来源拼出同一个键。
  final LinkedHashMap<String, String> _keys = LinkedHashMap<String, String>();

  /// 取(必要时生成)[scope] 接口上、[source] 这次上传的幂等键。
  ///
  /// 参数说明:
  /// - [scope] 接口标识(如 `im/images`):同一份本地来源用在不同接口上各记一条。
  /// - [source] 本次上传的本地来源(图片 / 录音的临时路径):同一来源恒得同一个 key。
  ///
  /// 返回参数:
  /// - 该次上传的幂等键;调用方把它原样放进 [idempotencyKeyHeader] 头。
  String keyFor(String scope, String source) {
    final cacheKey = '$scope\u0000$source';
    // remove + 回插 = 命中即续命,否则 LRU 会淘汰正在重试的那个 key
    final existing = _keys.remove(cacheKey);
    if (existing != null) {
      _keys[cacheKey] = existing;
      return existing;
    }
    final key = newUploadIdempotencyKey(now: _now, random: _random);
    _keys[cacheKey] = key;
    if (maxEntries > 0 && _keys.length > maxEntries) _keys.remove(_keys.keys.first);
    return key;
  }

  /// 当前记住了几条(单测断言 LRU 用)。
  int get length => _keys.length;
}

/// 上传失败的退避重试。
///
/// 判据与 Web 端 `web/src/im/self/image.ts::imageUploadRetryDelay` 同一套,免得两端对
/// 「什么值得再试一次」有两种说法:
/// 1. 请求没到服务端(断网 / 超时,`statusCode` 为空)→ 退避再试;
/// 2. `429` 限流 → 按服务端 `Retry-After` 等(超过 [maxDelay] 就按 [maxDelay] 等),
///    没给就用退避值;
/// 3. `409` + [idempotencyConflictCode] → 等 [conflictDelay](契约要求 1–2 秒),
///    **同一个 key** 再打一次;
/// 4. `5xx` → 退避再试(服务端重启中,再问一次大概率就好了)。
///
/// 其余(`400` 格式 / 像素超限、`413` 配额满、`401` / `403` / `404`)一律**立刻冒泡** ——
/// 重复上传只会再错一次,早点把服务端的中文原因交给用户比多转两圈有用。
class UploadRetry {
  /// 参数说明:
  /// - [attempts] 最多试几次(含第一次)。
  /// - [baseDelay] 首次退避,之后翻倍。
  /// - [maxDelay] 退避上限(含 `Retry-After` 的封顶)。
  /// - [conflictDelay] `409` + [idempotencyConflictCode] 的等待时长。
  /// - [sleep] 等待的注入点,单测用它记账而不真等;缺省 `Future.delayed`。
  UploadRetry({
    this.attempts = 3,
    this.baseDelay = const Duration(milliseconds: 500),
    this.maxDelay = const Duration(seconds: 4),
    this.conflictDelay = const Duration(milliseconds: 1200),
    Future<void> Function(Duration delay)? sleep,
  }) : _sleep = sleep ?? _delayed;

  /// 最多试几次(含第一次)。3 次足够扛过抖动,再多只会让用户干等。
  final int attempts;

  /// 首次退避,之后翻倍。
  final Duration baseDelay;

  /// 退避上限。
  final Duration maxDelay;

  /// `409` + [idempotencyConflictCode] 的等待时长(契约:1–2 秒)。
  final Duration conflictDelay;

  final Future<void> Function(Duration delay) _sleep;

  static Future<void> _delayed(Duration delay) => Future<void>.delayed(delay);

  /// 跑一次带幂等键的上传:[attempt] 每次调用都拿到**同一个** [key]。
  ///
  /// 上传体(如 `FormData`)必须在 [attempt] 内部**每次重建**:Dio 的 multipart 流只能
  /// 消费一次,复用同一个实例重试会发出空文件。
  ///
  /// 参数说明:
  /// - [key] 这次上传的幂等键,原样透传给每次尝试。
  /// - [attempt] 真正发请求的闭包,失败抛 [ApiException]。
  ///
  /// 返回参数:
  /// - 第一次成功的结果;重试用尽或遇到不可重试的错误则原样抛出该 [ApiException]。
  Future<T> run<T>(String key, Future<T> Function(String key) attempt) async {
    var backoff = baseDelay;
    for (var tried = 1;; tried++) {
      try {
        return await attempt(key);
      } on ApiException catch (error) {
        final delay = delayFor(error, backoff);
        if (delay == null || tried >= attempts) rethrow;
        await _sleep(delay);
        backoff = _doubled(backoff);
      }
    }
  }

  /// 这次失败值不值得退避重试;**值得就返回要等多久**,不值得返回 `null`(立刻冒泡)。
  ///
  /// 参数说明:
  /// - [error] 上一次上传抛出的异常。
  /// - [backoff] 本次退避建议值(调用方按尝试次数翻倍)。
  ///
  /// 返回参数:
  /// - 要等的时长;`null` 表示「再试也一样」。
  Duration? delayFor(ApiException error, Duration backoff) {
    final status = error.statusCode;
    // 没有 HTTP 状态码 = 请求没到服务端(断网 / 超时),值得退避再试一次
    if (status == null) return _capped(backoff);
    if (status == 429) return _capped(error.retryAfter ?? backoff);
    if (status == 409 && error.code == idempotencyConflictCode) return conflictDelay;
    if (status >= 500) return _capped(backoff);
    // 400 / 413 / 401 / 403 / 404:再问也一样,把服务端的中文原因直接交给用户
    return null;
  }

  Duration _capped(Duration delay) => delay > maxDelay ? maxDelay : delay;

  Duration _doubled(Duration delay) => _capped(delay * 2);
}
