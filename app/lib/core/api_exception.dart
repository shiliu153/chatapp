import 'package:dio/dio.dart';

/// 统一的接口错误:message 一定是可直接展示给用户的中文。
class ApiException implements Exception {
  ApiException(this.message, {this.statusCode});

  /// 把任意异常翻译成 ApiException;后端错误体固定是 {code, message}。
  factory ApiException.from(Object error) {
    if (error is ApiException) return error;
    if (error is DioException) {
      final response = error.response;
      final data = response?.data;
      if (data is Map && data['message'] is String) {
        return ApiException(data['message'] as String,
            statusCode: response?.statusCode);
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

  final String message;
  final int? statusCode;

  @override
  String toString() => 'ApiException($statusCode): $message';
}
