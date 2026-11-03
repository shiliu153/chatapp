/// 客户端错误上报(自建端点,零第三方成本)。
///
/// 为什么需要:服务端 Prometheus 只看得见自己返回的 5xx;Flutter 的渲染异常、
/// 异步未捕获异常、原生层崩溃前的错误都发生在设备上,用户不反馈就没人知道(审查 N-7)。
///
/// 设计要点:
/// 1. **fire-and-forget**:上报失败一律吞掉,绝不影响用户流程;
/// 2. **开关走 --dart-define**(`ERROR_REPORTING`),本地与测试默认关;
/// 3. **带 `request_id`**:由 [ErrorReporting.rememberRequestId] 记下最近一次响应的
///    `X-Request-Id`,前后端日志能按同一个 id 对上;
/// 4. **有配额与去重**:单个进程内最多 20 条,同一 message 只报一次 ——
///    渲染循环里抛异常时一秒能抛几百次,不限流等于自己 DDoS 自己。
library;

import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import 'app_info.dart';
import 'config.dart';

/// 真正发请求的函数;测试注入假实现。
typedef ErrorReporter = Future<void> Function(Map<String, dynamic> payload);

/// 前端错误上报:安装全局监听 + 发送。
class ErrorReporting {
  ErrorReporting._();

  /// 上报开关:`--dart-define=ERROR_REPORTING=true` 打开,默认关。
  static const bool enabled =
      bool.fromEnvironment('ERROR_REPORTING', defaultValue: false);

  /// 单进程内的上报上限。
  static const int maxReports = 20;

  /// 与后端序列化器对齐的字段上限。
  static const int maxMessage = 480;
  static const int maxStack = 4000;

  static final Set<String> _seen = <String>{};
  static int _sent = 0;
  static String _requestId = '';
  static ErrorReporter? _sender;

  /// 已经上报的条数(测试用)。
  static int get sent => _sent;

  /// 记下最近一次响应的服务端追踪 ID。
  static void rememberRequestId(String? id) {
    if (id != null && id.isNotEmpty) _requestId = id;
  }

  /// 当前记下的服务端追踪 ID。
  static String get requestId => _requestId;

  /// 安装全局错误监听:`FlutterError.onError` + `PlatformDispatcher.onError`。
  ///
  /// 必须早于 `runApp` 调用,否则启动阶段的错误抓不到。
  ///
  /// [sender] 发送函数(测试注入);[forceEnabled] 覆盖开关(测试用)。
  static void install({ErrorReporter? sender, bool? forceEnabled}) {
    final on = forceEnabled ?? enabled;
    if (!on) return;
    _sender = sender ?? _post;
    _seen.clear();
    _sent = 0;

    // 框架内部错误(构建/布局/绘制):保留原有的红屏与控制台输出,只额外上报
    final previous = FlutterError.onError;
    FlutterError.onError = (details) {
      previous?.call(details);
      report(details.exceptionAsString(), stack: details.stack?.toString() ?? '');
    };

    // 异步未捕获异常(不在框架内的 zone 错误)
    PlatformDispatcher.instance.onError = (error, stack) {
      report(error.toString(), stack: stack.toString());
      return false; // 不吞掉:交给平台默认处理,保持既有崩溃行为
    };
  }

  /// 上报一条错误;同一 message 在本次进程内只报一次,总数封顶 [maxReports]。
  ///
  /// [message] 错误摘要;[stack] 堆栈;[route] 出错页面。
  static void report(String message, {String stack = '', String route = ''}) {
    final sender = _sender;
    if (sender == null || _sent >= maxReports) return;
    final trimmed = _truncate(message, maxMessage);
    if (!_seen.add(trimmed)) return;
    _sent += 1;
    final payload = <String, dynamic>{
      'platform': 'app',
      'message': trimmed,
      'stack': _truncate(stack, maxStack),
      'route': route,
      'app_version': appVersion,
      'request_id': _requestId,
    };
    // 不 await:上报不能阻塞 UI,也不能把异常抛回调用方
    unawaited(sender(payload).catchError((Object _) {}));
  }

  /// 清空计数与去重集合(测试用)。
  @visibleForTesting
  static void reset() {
    _seen.clear();
    _sent = 0;
    _requestId = '';
    _sender = null;
  }

  static String _truncate(String value, int limit) =>
      value.length <= limit ? value : value.substring(0, limit);

  /// 默认发送器:一个不带拦截器的裸 Dio(登录页崩溃时还没有令牌)。
  static Future<void> _post(Map<String, dynamic> payload) async {
    final dio = Dio(BaseOptions(
      connectTimeout: const Duration(seconds: 5),
      receiveTimeout: const Duration(seconds: 5),
      headers: const {'X-Client': 'app'},
    ));
    await dio.post<void>('$apiBase/client-errors', data: payload);
  }
}
