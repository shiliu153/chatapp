import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/api_client.dart';
import 'package:chatapp_app/core/api_exception.dart';
import 'package:chatapp_app/im/im_repository.dart';

import '../support/sample_data.dart';
import '../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;
  late ImRepository repository;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    repository = ImRepository(ApiClient(dio));
  });

  test('fetchUserSig 解析签名信息(sdkappid 是字符串也要收)', () async {
    adapter.routes['POST /im/user_sig'] = (options) => ok({
          'user_sig': 'sig-abc',
          'sdkappid': '1600161711',
          'im_user_id': 'u3',
          'expire': 604800,
        });

    final sig = await repository.fetchUserSig();

    expect(sig.userSig, 'sig-abc');
    expect(sig.sdkAppId, 1600161711);
    expect(sig.imUserId, 'u3');
    expect(adapter.log.single.path, '/im/user_sig');
  });

  test('fetchMatches 解析配对列表', () async {
    adapter.routes['GET /matches'] = (options) => ok(
        pageJson([matchJson(userId: 9, nickname: '小红'), matchJson(userId: 10, nickname: '小刚')]));

    final matches = await repository.fetchMatches();

    expect(matches.map((entry) => entry.imUserId), ['u9', 'u10']);
    expect(matches.first.nickname, '小红');
    expect(matches.first.userId, 9);
  });

  test('fetchMatches 跟 next 拉完所有页(分页约定)', () async {
    adapter.routes['GET /matches'] = (options) {
      final offset = options.uri.queryParameters['offset'] ?? '0';
      if (offset == '0') {
        return ok(pageJson([matchJson(userId: 9, nickname: '小红')], hasNext: true));
      }
      return ok(pageJson([matchJson(userId: 10, nickname: '小刚')]));
    };

    final matches = await repository.fetchMatches();

    expect(matches.map((entry) => entry.userId), [9, 10]);
    expect(adapter.log.length, 2);                                  // 拉了 2 页
    expect(adapter.log.last.uri.queryParameters['offset'], '1');    // 第二页 offset=第一页实际条数
  });

  test('接口报错时抛 ApiException(message 是后端中文提示)', () async {
    adapter.routes['POST /im/user_sig'] = (options) => jsonError(403, '账号已被封禁');

    expect(
      () => repository.fetchUserSig(),
      throwsA(isA<ApiException>().having((e) => e.message, 'message', '账号已被封禁')),
    );
  });
}
