import 'package:dio/dio.dart';

class ApiException implements Exception {
  ApiException(this.message);
  final String message;

  @override
  String toString() => 'ApiException: $message';
}

class ApiClient {
  ApiClient({required this.baseUrl, Dio? dio})
      : _dio = dio ??
            Dio(BaseOptions(
              baseUrl: baseUrl,
              connectTimeout: const Duration(seconds: 10),
              receiveTimeout: const Duration(seconds: 10),
            ));

  final String baseUrl;
  final Dio _dio;

  Future<String> health() async {
    final resp = await _dio.get('/health');
    if (resp.statusCode != 200) {
      throw ApiException('HTTP ${resp.statusCode}');
    }
    return resp.data['status'] as String;
  }
}
