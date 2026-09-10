import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/token_store.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('存取与清空', () async {
    final store = TokenStore();
    await store.save(access: 'a1', refresh: 'r1', userId: 7);
    expect(await store.accessToken, 'a1');
    expect(await store.refreshToken, 'r1');
    expect(await store.userId, 7);

    await store.saveTokens(access: 'a2', refresh: 'r2');
    expect(await store.accessToken, 'a2');
    expect(await store.refreshToken, 'r2');

    await store.clear();
    expect(await store.accessToken, isNull);
    expect(await store.refreshToken, isNull);
    expect(await store.userId, isNull);
  });

  test('clear 会通知监听者(会话过期的传播通道)', () async {
    final store = TokenStore();
    var notified = 0;
    store.addListener(() => notified++);
    await store.clear();
    expect(notified, 1);
  });
}
