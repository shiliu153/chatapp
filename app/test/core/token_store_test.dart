import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/token_storage.dart';
import 'package:chatapp_app/core/token_store.dart';

/// 永远抛异常的实现:模拟 Keystore 损坏 / 平台通道缺失。
class _BrokenStorage implements TokenStorage {
  @override
  Future<String?> read(String key) async => throw StateError('keystore 不可用');

  @override
  Future<void> write(String key, String value) async => throw StateError('keystore 不可用');

  @override
  Future<void> delete(String key) async => throw StateError('keystore 不可用');
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('存取与清空', () async {
    final storage = InMemoryTokenStorage();
    final store = TokenStore(storage: storage, legacy: SharedPreferencesTokenStorage());
    await store.save(access: 'a1', refresh: 'r1', userId: 7);
    expect(await store.accessToken, 'a1');
    expect(await store.refreshToken, 'r1');
    expect(await store.userId, 7);
    expect(storage.values, containsPair('auth.access', 'a1'));

    await store.saveTokens(access: 'a2', refresh: 'r2');
    expect(await store.accessToken, 'a2');
    expect(await store.refreshToken, 'r2');

    await store.clear();
    expect(await store.accessToken, isNull);
    expect(await store.refreshToken, isNull);
    expect(await store.userId, isNull);
  });

  test('clear 会通知监听者(会话过期的传播通道)', () async {
    final store = TokenStore(
      storage: InMemoryTokenStorage(),
      legacy: SharedPreferencesTokenStorage(),
    );
    var notified = 0;
    store.addListener(() => notified++);
    await store.clear();
    expect(notified, 1);
  });

  test('迁移:老 SharedPreferences 里的令牌搬进安全存储并删除旧键', () async {
    SharedPreferences.setMockInitialValues({
      'auth.access': 'old-access',
      'auth.refresh': 'old-refresh',
      'auth.user_id': 7,
    });
    final storage = InMemoryTokenStorage();
    final store = TokenStore(storage: storage, legacy: SharedPreferencesTokenStorage());

    expect(await store.refreshToken, 'old-refresh');
    expect(storage.values['auth.refresh'], 'old-refresh');
    expect(storage.values['auth.user_id'], '7');

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.get('auth.access'), isNull);
    expect(prefs.get('auth.refresh'), isNull);
    expect(prefs.get('auth.user_id'), isNull);
  });

  test('迁移幂等:重复读取不会覆盖安全存储里的新值', () async {
    SharedPreferences.setMockInitialValues({'auth.access': 'old'});
    final storage = InMemoryTokenStorage({'auth.access': 'new'});
    final store = TokenStore(storage: storage, legacy: SharedPreferencesTokenStorage());

    expect(await store.accessToken, 'new');
    expect(await store.accessToken, 'new');
    expect(storage.values['auth.access'], 'new');
  });

  test('安全存储不可用时降级读 SharedPreferences,不让用户登不进来', () async {
    SharedPreferences.setMockInitialValues({'auth.refresh': 'legacy-refresh'});
    final store = TokenStore(storage: _BrokenStorage(), legacy: SharedPreferencesTokenStorage());

    expect(await store.refreshToken, 'legacy-refresh');
  });

  test('安全存储写入失败时降级写 SharedPreferences', () async {
    final store = TokenStore(storage: _BrokenStorage(), legacy: SharedPreferencesTokenStorage());

    await store.save(access: 'a', refresh: 'r', userId: 9);

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('auth.refresh'), 'r');
    expect(await store.userId, 9);
  });
}
