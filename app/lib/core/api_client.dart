import 'package:dio/dio.dart';

import 'api_exception.dart';
import 'error_reporting.dart';

/// 薄封装:统一抛 ApiException,调用方直接拿 response.data。
class ApiClient {
  ApiClient(this._dio);

  final Dio _dio;

  Future<dynamic> get(String path, {Map<String, dynamic>? query}) =>
      _guard(() => _dio.get<dynamic>(path, queryParameters: query));

  Future<dynamic> post(String path, {Object? data}) =>
      _guard(() => _dio.post<dynamic>(path, data: data));

  Future<dynamic> patch(String path, {Object? data}) =>
      _guard(() => _dio.patch<dynamic>(path, data: data));

  /// [data] 用于 DELETE 带请求体(注销账号要带手机号做二次确认)。
  Future<dynamic> delete(String path, {Object? data}) =>
      _guard(() => _dio.delete<dynamic>(path, data: data));

  /// 拉全量:响应带 `next_cursor`(游标分页)就顺着游标翻,否则退回 limit/offset。
  ///
  /// 两种协议都支持是有意的:游标接口(`/matches` 等)走 `before`,老接口
  /// (评论、回复、拉黑名单)仍是 offset。首请求**两个参数都不带**,靠响应形状
  /// 判断走哪条路,调用方不用关心。
  Future<List<dynamic>> getAllPages(String path, {int pageSize = 50}) async {
    final items = <dynamic>[];
    var offset = 0;
    String? cursor;
    var legacy = false;
    while (true) {
      final page = await get(path, query: {
        'limit': pageSize,
        'before': ?cursor,
        if (legacy) 'offset': offset,
      }) as Map<String, dynamic>;
      final results = page['results'] as List<dynamic>;
      items.addAll(results);
      if (results.isEmpty) return items;
      if (!legacy && page.containsKey('next_cursor')) {
        cursor = page['next_cursor'] as String?;
        if (cursor == null) return items;
        continue;
      }
      legacy = true;
      offset += results.length;
      if (page['next'] == null) return items;
    }
  }

  Future<dynamic> _guard(Future<Response<dynamic>> Function() request) async {
    try {
      final response = await request();
      // 记下服务端追踪 ID:错误上报会带上它,前后端日志才能按同一个 id 对上
      ErrorReporting.rememberRequestId(response.headers.value('X-Request-Id'));
      return response.data;
    } on DioException catch (error) {
      ErrorReporting.rememberRequestId(
          error.response?.headers.value('X-Request-Id'));
      throw ApiException.from(error);
    }
  }
}
