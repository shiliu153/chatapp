import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/client_header.dart';
import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/im/self_transport.dart';

import '../support/scripted_adapter.dart';

/// App 端统一上报端类型(批次 K / K-4)。
///
/// 断言一律走**生产路径**:这里用的是 `baseDioProvider` / `refreshDioProvider` /
/// `apiClientProvider` 的默认实现(拦截器就是生产那套),只把底层 adapter 换成
/// 录制式假网络 —— 所以「请求头里有 `X-Client: app`」证明的是真实装配,
/// 而不是测试自己手写的 Dio。
void main() {
  late ScriptedAdapter adapter;
  late ProviderContainer container;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({
      'GET /users/me': (options) => ok({'user_id': 'u1'}),
      'POST /auth/sms/send': (options) => ok({'status': 'ok'}),
      'POST /auth/sms/verify': (options) => ok({
            'access': 'a1',
            'refresh': 'r1',
            'is_new_user': false,
            'user_id': 'u1',
          }),
      'POST /im/images': (options) => ok({'url': 'http://test/x.jpg', 'thumb_url': 'http://test/t.jpg'}),
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /conversations': (options) => ok({'results': <dynamic>[]}),
    });
    container = ProviderContainer();
    // 只换网络层:拦截器、超时、证书绑定都还是生产那套
    container.read(baseDioProvider).httpClientAdapter = adapter;
    container.read(refreshDioProvider).httpClientAdapter = adapter;
  });

  tearDown(() => container.dispose());

  test('普通 GET / POST 请求都带 X-Client: app', () async {
    final api = container.read(apiClientProvider);

    await api.get('/users/me');
    await api.post('/auth/sms/send', data: {'phone': '13800000000'});

    expect(adapter.log.map((options) => options.method), ['GET', 'POST']);
    for (final options in adapter.log) {
      expect(options.headers[ClientHeaderInterceptor.headerName], appClientType,
          reason: '${options.method} ${options.path} 漏了端类型头');
    }
  });

  test('multipart 上传也带 X-Client: app(逐处手写最容易漏的就是这条)', () async {
    final api = container.read(apiClientProvider);

    await api.post('/im/images', data: FormData.fromMap({
      'file': MultipartFile.fromBytes(const [1, 2, 3], filename: 'a.jpg'),
    }));

    final request = adapter.log.single;
    // 先确认它真的是 multipart:否则这条用例只是把普通请求又跑了一遍
    expect('${request.headers[Headers.contentTypeHeader]}', contains('multipart/form-data'));
    expect(request.headers[ClientHeaderInterceptor.headerName], appClientType);
  });

  test('调用方显式设了 X-Client 就不覆盖(便于联调 / 测试冒充 web 端)', () async {
    final dio = container.read(baseDioProvider);

    await dio.post<dynamic>(
      '/auth/sms/verify',
      data: {'phone': '13800000000', 'code': '123456'},
      options: Options(headers: {ClientHeaderInterceptor.headerName: 'web'}),
    );
    await dio.get<dynamic>('/users/me', options: Options(headers: {'x-client': 'web'}));

    expect(adapter.log.first.headers[ClientHeaderInterceptor.headerName], 'web');
    // 小写写法同样算「已显式设置」:不能既保留 web 又补一个 app
    final lowerCased = adapter.log.last.headers;
    expect(lowerCased['x-client'], 'web');
    expect(
      lowerCased.keys.where((key) => key.toLowerCase() == 'x-client'),
      hasLength(1),
      reason: '同一个头只应出现一次,补头的逻辑不能和调用方的写法叠成两条',
    );
  });

  test('token 刷新(裸 Dio,不经 AuthInterceptor)也带 X-Client: app', () async {
    final tokenStore = container.read(tokenStoreProvider);
    await tokenStore.saveTokens(access: 'a1', refresh: 'r1');

    final newAccess = await container.read(tokenRefresherProvider).refresh();

    expect(newAccess, 'a2');
    expect(adapter.log.single.path, '/auth/token/refresh');
    expect(adapter.log.single.headers[ClientHeaderInterceptor.headerName], appClientType);
  });

  test('IM 的 HTTP 调用(历史 / 会话列表)也带 X-Client: app', () async {
    final http = DioSelfHttpClient('http://test/im/api', 'im-token');
    http.dio.httpClientAdapter = adapter;

    await http.get('/conversations', const {});

    expect(adapter.log.single.headers[ClientHeaderInterceptor.headerName], appClientType);
  });
}
