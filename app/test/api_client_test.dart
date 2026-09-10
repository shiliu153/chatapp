import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:chatapp_app/core/api_client.dart';

import 'fake_adapter.dart';

void main() {
  test('health returns ok from api', () async {
    final dio = Dio()..httpClientAdapter = FakeAdapter();
    final api = ApiClient(baseUrl: 'http://x/api/v1', dio: dio);
    expect(await api.health(), 'ok');
  });
}
