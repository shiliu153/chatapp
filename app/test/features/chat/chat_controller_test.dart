import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/chat/chat_controller.dart';
import 'package:chatapp_app/im/im_client.dart';
import 'package:chatapp_app/im/im_manager.dart';

import '../../support/fake_im_client.dart';
import '../../support/scripted_adapter.dart';

ChatMessage msg(String id, {required bool isSelf, String text = 'hi'}) => ChatMessage(
      msgId: id,
      peerId: 'u9',
      isSelf: isSelf,
      timestamp: DateTime.now().millisecondsSinceEpoch,
      kind: ChatMessageKind.text,
      text: text,
    );

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

  test('打开会话:拉历史 + 标记已读', () async {
    fake.history = {
      'u9': [msg('m1', isSelf: false, text: '你好')],
    };
    final container = makeContainer();
    await container.read(imStatusProvider.notifier).login();

    final list = await container.read(chatProvider('u9').future);

    expect(list.single.text, '你好');
    expect(fake.log, contains('read:u9'));
  });

  test('实时消息追加并去重(多端回显同一条不重复上屏)', () async {
    final container = makeContainer();
    await container.read(imStatusProvider.notifier).login();
    await container.read(chatProvider('u9').future);

    fake.emitIncoming('u9', '在吗');
    await pumpEventQueue();
    expect(container.read(chatProvider('u9')).value!.single.text, '在吗');

    fake.emit(ImNewMessage(container.read(chatProvider('u9')).value!.single));
    await pumpEventQueue();
    expect(container.read(chatProvider('u9')).value, hasLength(1));
  });

  test('别的会话的消息不会串进来', () async {
    final container = makeContainer();
    await container.read(imStatusProvider.notifier).login();
    await container.read(chatProvider('u9').future);

    fake.emitIncoming('u8', '嗨');
    await pumpEventQueue();

    expect(container.read(chatProvider('u9')).value, isEmpty);
  });

  test('发送:乐观上屏后用服务器消息替换', () async {
    final container = makeContainer();
    await container.read(imStatusProvider.notifier).login();
    await container.read(chatProvider('u9').future);

    await container.read(chatProvider('u9').notifier).send('你好呀');

    final list = container.read(chatProvider('u9')).value!;
    expect(list.single.text, '你好呀');
    expect(list.single.isSelf, isTrue);
    expect(list.single.isPending, isFalse);
    expect(fake.log, contains('send:u9:你好呀'));
  });

  test('发送失败:气泡撤掉并抛出', () async {
    final container = makeContainer();
    await container.read(imStatusProvider.notifier).login();
    await container.read(chatProvider('u9').future);
    fake.sendError = const ImException(6013, 'network');

    await expectLater(
      container.read(chatProvider('u9').notifier).send('你好'),
      throwsA(isA<ImException>()),
    );

    expect(container.read(chatProvider('u9')).value, isEmpty);
  });
}
