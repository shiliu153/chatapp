import 'package:dio/dio.dart';

import 'api_exception.dart';

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

  Future<dynamic> delete(String path) => _guard(() => _dio.delete<dynamic>(path));

  /// 跟 LimitOffset 分页约定拉全量:循环请求直到 next 为空,返回 results 拼接。
  Future<List<dynamic>> getAllPages(String path, {int pageSize = 50}) async {
    final items = <dynamic>[];
    var offset = 0;
    while (true) {
      final page = await get(path, query: {'limit': pageSize, 'offset': offset})
          as Map<String, dynamic>;
      final results = page['results'] as List<dynamic>;
      items.addAll(results);
      offset += results.length;
      if (page['next'] == null || results.isEmpty) return items;
    }
  }

  Future<dynamic> _guard(Future<Response<dynamic>> Function() request) async {
    try {
      final response = await request();
      return response.data;
    } on DioException catch (error) {
      throw ApiException.from(error);
    }
  }
}
