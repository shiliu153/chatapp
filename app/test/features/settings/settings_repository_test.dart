import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/api_exception.dart';
import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/settings/settings_repository.dart';

import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;

  ProviderContainer makeContainer() {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))
      ..httpClientAdapter = adapter;
    final container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
    ]);
    addTearDown(container.dispose);
    return container;
  }

  // ⚠️ 必须 mock:apiClientProvider 会挂 AuthInterceptor,它读凭证要 SharedPreferences,
  // 不 mock 会抛 MissingPluginException(同 blocked_users_page_test.dart)。
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
  });

  test('deleteAccount 发 DELETE /users/me 并带上手机号', () async {
    adapter.routes['DELETE /users/me'] = (options) => ok({}, status: 204);

    await makeContainer().read(settingsRepositoryProvider).deleteAccount('13800138000');

    final request = adapter.log.single;
    expect(request.method, 'DELETE');
    expect(request.path, '/users/me');
    expect(request.data, {'phone': '13800138000'});
  });

  test('deleteAccount 把 400 翻成 ApiException(手机号不匹配)', () async {
    adapter.routes['DELETE /users/me'] =
        (options) => jsonError(400, '手机号与当前账号不一致');

    await expectLater(
      makeContainer().read(settingsRepositoryProvider).deleteAccount('13900139000'),
      throwsA(isA<ApiException>().having((e) => e.statusCode, 'statusCode', 400)),
    );
  });
}
