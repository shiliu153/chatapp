import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/auth/session.dart';
import 'package:chatapp_app/features/chat/match_cache.dart';
import 'package:chatapp_app/im/im_manager.dart';
import 'package:chatapp_app/im/im_repository.dart';

import '../../support/fake_im_client.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;

  ProviderContainer makeContainer() {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
      imClientProvider.overrideWithValue(FakeImClient()),
    ]);
    addTearDown(container.dispose);
    return container;
  }

  setUp(() {
    adapter = ScriptedAdapter({});
  });

  test('登录后拉 matches,按 imUserId 建索引', () async {
    SharedPreferences.setMockInitialValues(
        {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 3});
    adapter.routes['POST /auth/token/refresh'] = (options) => ok({'access': 'a2', 'refresh': 'r2'});
    adapter.routes['GET /matches'] = (options) => ok([matchJson(userId: 9, nickname: '小红')]);
    final container = makeContainer();

    await container.read(sessionProvider.notifier).bootstrap();
    final cache = await container.read(matchCacheProvider.future);

    expect(cache['u9']?.nickname, '小红');
    expect(cache['u9']?.userId, 9);
  });

  test('未登录 → 空缓存,不发请求', () async {
    SharedPreferences.setMockInitialValues({});
    final container = makeContainer();

    final cache = await container.read(matchCacheProvider.future);

    expect(cache, isEmpty);
    expect(adapter.log, isEmpty);
  });

  test('显示名:缓存 > IM 名 > id;头像:缓存 > IM 头像', () {
    const cache = {
      'u9': MatchEntry(
        userId: 9,
        imUserId: 'u9',
        nickname: '小红',
        avatarUrl: 'http://cached',
      ),
      'u8': MatchEntry(userId: 8, imUserId: 'u8', nickname: ''), // 缓存里没名字没头像
    };
    expect(displayNameFor(cache, 'u9', imName: 'IM名'), '小红');
    expect(displayNameFor(cache, 'u8', imName: 'IM名'), 'IM名');
    expect(displayNameFor(cache, 'u7'), 'u7');
    expect(displayNameFor(cache, 'system_notice'), '系统通知'); // 特判:不裸奔成 id
    expect(avatarUrlFor(cache, 'u9', imFaceUrl: 'http://im'), 'http://cached');
    expect(avatarUrlFor(cache, 'u8', imFaceUrl: 'http://im'), 'http://im');
    expect(avatarUrlFor(cache, 'u7'), isNull);
  });
}
