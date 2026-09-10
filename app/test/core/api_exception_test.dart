import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/api_exception.dart';

void main() {
  test('把后端的 {code,message} 取成中文提示', () {
    final error = DioException(
      requestOptions: RequestOptions(path: '/users/me'),
      response: Response(
        requestOptions: RequestOptions(path: '/users/me'),
        statusCode: 403,
        data: {'code': 403, 'message': '账号已被限制,暂时无法滑卡'},
      ),
      type: DioExceptionType.badResponse,
    );
    final apiError = ApiException.from(error);
    expect(apiError.message, '账号已被限制,暂时无法滑卡');
    expect(apiError.statusCode, 403);
  });

  test('网络不通时给统一中文提示', () {
    final error = DioException(
      requestOptions: RequestOptions(path: '/health'),
      type: DioExceptionType.connectionError,
      error: 'offline',
    );
    expect(ApiException.from(error).message, '网络不给力,请检查网络后重试');
  });

  test('已经是 ApiException 就原样返回', () {
    final original = ApiException('原样', statusCode: 400);
    expect(ApiException.from(original), same(original));
  });
}
