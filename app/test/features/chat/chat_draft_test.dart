import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/auth/session.dart';
import 'package:chatapp_app/features/chat/chat_page.dart';
import 'package:chatapp_app/features/chat/draft_store.dart';
import 'package:chatapp_app/features/presence/presence_controller.dart';
import 'package:chatapp_app/im/im_client.dart';
import 'package:chatapp_app/im/im_manager.dart';

import '../../support/fake_im_client.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';
import '../../support/heart_theme.dart';

/// 批次 T-2:聊天草稿。
///
/// 草稿是**纯客户端**的半成品输入(不写服务端),所以这里全部断言在
/// `shared_preferences` 的 `chat_draft:{peerId}` 与输入框回填上:
/// 防抖落盘 / 进会话回填 / 发送成功删 / 清空删。

ChatMessage _text(String id, {required bool isSelf, required String text}) => ChatMessage(
      msgId: id,
      peerId: 'u9',
      isSelf: isSelf,
      timestamp: DateTime.now().millisecondsSinceEpoch,
      kind: ChatMessageKind.text,
      text: text,
    );

class _LoggedInImManager extends ImManager {
  @override
  ImStatus build() => const ImLoggedIn('u3');
}

class _LoggedInSession extends SessionController {
  @override
  SessionState build() => const SessionLoggedIn();
}

void main() {
  late ScriptedAdapter adapter;
  late FakeImClient fake;
  late ProviderContainer container;

  ScriptedAdapter makeAdapter() => ScriptedAdapter({
        'GET /matches': (options) => ok(pageJson([matchJson(userId: 9, nickname: '小红')])),
        'GET /users/me': (options) => ok(profileJson()),
        'GET /presence': (options) => ok({'results': []}),
      });

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = makeAdapter();
    fake = FakeImClient();
    addTearDown(fake.dispose);
  });

  Future<void> pumpChat(WidgetTester tester, {List<Override> overrides = const []}) async {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
      imClientProvider.overrideWithValue(fake),
      imStatusProvider.overrideWith(_LoggedInImManager.new),
      sessionProvider.overrideWith(_LoggedInSession.new),
      presenceRefreshIntervalProvider.overrideWithValue(null),
      ...overrides,
    ]);
    addTearDown(container.dispose);
    final router = GoRouter(
      initialLocation: '/chat/u9',
      routes: [
        GoRoute(
          path: '/chat/:peerId',
          builder: (context, state) => ChatPage(peerId: state.pathParameters['peerId']!),
        ),
      ],
    );
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: MaterialApp.router(theme: heartTheme, routerConfig: router),
    ));
    await tester.pumpAndSettle();
  }

  testWidgets('输入停 300ms 才落盘(防抖),草稿进内存也进 prefs', (tester) async {
    await pumpChat(tester);

    await tester.enterText(find.byKey(const Key('chat.input')), '还没');
    await tester.pump(const Duration(milliseconds: 100));
    await tester.enterText(find.byKey(const Key('chat.input')), '还没想好');
    // 还没到 300ms:一个字都不该写盘
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('chat_draft:u9'), isNull);

    await tester.pump(const Duration(milliseconds: 350));
    expect(prefs.getString('chat_draft:u9'), '还没想好');
    expect(container.read(draftStoreProvider)['u9'], '还没想好');
  });

  testWidgets('进会话把草稿回填进输入框', (tester) async {
    // 模拟「上次退出时留着草稿」
    SharedPreferences.setMockInitialValues({'chat_draft:u9': '上次没说完的话'});

    await pumpChat(tester);
    await tester.pumpAndSettle();

    final input = tester.widget<TextField>(find.byKey(const Key('chat.input')));
    expect(input.controller!.text, '上次没说完的话');
  });

  testWidgets('发送成功后草稿被删(否则列表永远挂「[草稿] 」)', (tester) async {
    SharedPreferences.setMockInitialValues({'chat_draft:u9': '要发的话'});
    await pumpChat(tester);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('chat_draft:u9'), '要发的话');

    await tester.tap(find.byKey(const Key('chat.send')));
    await tester.pumpAndSettle();

    expect(fake.log, contains('send:u9:要发的话'));
    expect(prefs.getString('chat_draft:u9'), isNull);
    expect(container.read(draftStoreProvider).containsKey('u9'), isFalse);
  });

  testWidgets('输入框清空后草稿被删(清空 = 这条不写了)', (tester) async {
    await pumpChat(tester);
    await tester.enterText(find.byKey(const Key('chat.input')), '算了');
    await tester.pump(const Duration(milliseconds: 350));
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('chat_draft:u9'), '算了');

    await tester.enterText(find.byKey(const Key('chat.input')), '');
    await tester.pumpAndSettle();

    expect(prefs.getString('chat_draft:u9'), isNull);
    expect(container.read(draftStoreProvider).containsKey('u9'), isFalse);
  });

  testWidgets('打完字 300ms 内就退出:dispose 里补存,草稿不丢', (tester) async {
    await pumpChat(tester);

    await tester.enterText(find.byKey(const Key('chat.input')), '走得急');
    await tester.pump(const Duration(milliseconds: 100)); // 还没到 300ms 防抖点
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('chat_draft:u9'), isNull);

    // 卸载页面 = 用户按返回:没落盘的那份必须在 dispose 里补存
    await tester.pumpWidget(const SizedBox());
    await tester.pumpAndSettle();

    expect(prefs.getString('chat_draft:u9'), '走得急');
  });

  testWidgets('只有空白的草稿既不入库,也不覆盖已有草稿', (tester) async {
    fake.history = {
      'u9': [_text('1', isSelf: false, text: '你好')],
    };
    await pumpChat(tester);
    await tester.enterText(find.byKey(const Key('chat.input')), '   ');
    await tester.pump(const Duration(milliseconds: 350));

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('chat_draft:u9'), isNull);
    expect(container.read(draftStoreProvider), isEmpty);
  });
}
