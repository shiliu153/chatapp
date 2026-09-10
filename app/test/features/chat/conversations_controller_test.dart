import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/chat/conversations_controller.dart';
import 'package:chatapp_app/im/im_client.dart';
import 'package:chatapp_app/im/im_manager.dart';

import '../../support/fake_im_client.dart';
import '../../support/scripted_adapter.dart';

ImConversation conv(String peerId, {int unread = 0}) =>
    ImConversation(peerId: peerId, unreadCount: unread);

void main() {
  late ScriptedAdapter adapter;
  late FakeImClient fake;

  ProviderContainer makeContainer() {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
      imClientProvider.overrideWithValue(fake),
    ]);
    addTearDown(container.dispose);
    return container;
  }

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({
      'POST /im/user_sig': (options) => ok({
            'user_sig': 'sig',
            'sdkappid': '1600161711',
            'im_user_id': 'u3',
            'expire': 604800,
          }),
    });
    fake = FakeImClient();
    addTearDown(fake.dispose);
  });

  test('IM 登录后拉会话列表;会话变化事件触发刷新', () async {
    fake.conversations = [conv('u9', unread: 2)];
    final container = makeContainer();

    await container.read(imStatusProvider.notifier).login();
    final list = await container.read(conversationsProvider.future);
    expect(list.single.peerId, 'u9');
    expect(container.read(unreadTotalProvider), 2);

    fake.conversations = [conv('u9', unread: 5)];
    fake.emit(const ImConversationsChanged());
    await pumpEventQueue();

    expect(container.read(unreadTotalProvider), 5);
  });

  test('未登录 → 空列表,不碰 SDK', () async {
    final container = makeContainer();

    final list = await container.read(conversationsProvider.future);

    expect(list, isEmpty);
    expect(fake.log, isEmpty);
  });
}
