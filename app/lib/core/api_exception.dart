import 'package:dio/dio.dart';

/// 单设备登录冲突:后端在别的设备登录后给本设备回的专用业务码。
const singleDeviceCode = 40101;

/// 统一的接口错误:message 一定是可直接展示给用户的中文。
class ApiException implements Exception {
  ApiException(this.message, {this.statusCode, this.code, this.retryAfter});

  /// 把任意异常翻译成 ApiException;后端错误体固定是 {code, message}。
  factory ApiException.from(Object error) {
    if (error is ApiException) return error;
    if (error is DioException) {
      final response = error.response;
      final data = response?.data;
      if (data is Map && data['message'] is String) {
        return ApiException(
          data['message'] as String,
          statusCode: response?.statusCode,
          code: data['code'] is int ? data['code'] as int : null,
          retryAfter: _retryAfterOf(response),
        );
      }
      switch (error.type) {
        case DioExceptionType.connectionTimeout:
        case DioExceptionType.sendTimeout:
        case DioExceptionType.receiveTimeout:
        case DioExceptionType.connectionError:
          return ApiException('网络不给力,请检查网络后重试');
        default:
          return ApiException('请求失败,请稍后再试');
      }
    }
    return ApiException('出错了,请稍后再试');
  }

  /// 读 `Retry-After` 头(delta-seconds 形式,后端 429 一律给秒数)。
  ///
  /// 只认正整数;HTTP-date 形式或缺失都返回 null,调用方按「拿不到就不硬等」处理。
  static Duration? _retryAfterOf(Response<dynamic>? response) {
    final raw = response?.headers.value('Retry-After');
    final seconds = raw == null ? null : int.tryParse(raw.trim());
    if (seconds == null || seconds <= 0) return null;
    return Duration(seconds: seconds);
  }

  final String message;
  final int? statusCode;

  /// 后端业务码(如 40101 单设备登录冲突);普通错误与 HTTP 状态码一致。
  final int? code;

  /// 后端要求的等待时长(429 的 `Retry-After`,如每日喜欢额度用完要等到次日 0 点)。
  final Duration? retryAfter;

  @override
  String toString() => 'ApiException($statusCode/$code): $message';
}

/// 错误展示统一入口:ApiException 取其中文 message,其他异常兜底。
String apiMessageOf(Object error) =>
    error is ApiException ? error.message : '加载失败,稍后再试';
