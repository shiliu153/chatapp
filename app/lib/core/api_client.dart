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

  Future<dynamic> _guard(Future<Response<dynamic>> Function() request) async {
    try {
      final response = await request();
      return response.data;
    } on DioException catch (error) {
      throw ApiException.from(error);
    }
  }
}
