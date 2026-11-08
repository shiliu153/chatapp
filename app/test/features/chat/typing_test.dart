// 输入中状态(批次 L-1)的 App 侧测试。
//
// 两条核心行为:
//   1. **接收端 5 秒过期**:typing 是可丢信号,服务端不落库也不补发,所以「对端打完
//      字停手」这件事只能靠客户端自己超时 —— 不超时的话「正在输入…」会一直挂着;
//   2. **发送端 3 秒节流**:首次输入立即发,之后 3 秒内最多一次(服务端另有
//      1 次 / 2 秒的令牌桶兜底,客户端这层只是省流量)。
//
// 控制器部分用 `fakeAsync` 驱动(定时器就是这两条行为的全部实现,真实等待又慢又抖);
// 顶栏部分用 `testWidgets`(文案只在 peerTyping 为真时出现)。
// IM 登录态直接 override 成已登录(同 `chat_page_test.dart` 的做法):假时钟里让 dio
// 真跑一遍登录链路会卡死,而那一截与本节要验的东西无关。
import 'package:dio/dio.dart';
import 'package:fake_async/fake_async.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/auth/session.dart';
import 'package:chatapp_app/features/chat/chat_controller.dart';
import 'package:chatapp_app/features/chat/chat_page.dart';
import 'package:chatapp_app/features/presence/presence_controller.dart';
import 'package:chatapp_app/im/im_manager.dart';

import '../../support/fake_im_client.dart';
import '../../support/heart_theme.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

/// 让 IM 直接处于已登录态(假时钟里裸 await 走 dio 的登录会卡死)。
class _LoggedInImManager extends ImManager {
  @override
  ImStatus build() => const ImLoggedIn('u3');
}

/// 会话也直接当已登录(matches 缓存依赖它才会去拉数据)。
class _LoggedInSession extends SessionController {
  @override
  SessionState build() => const SessionLoggedIn();
}

void main() {
  late ScriptedAdapter adapter;
  late FakeImClient fake;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({
      'GET /matches': (options) => ok(pageJson([matchJson(userId: 9, nickname: '小红')])),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /presence': (options) => ok({'results': []}),
    });
    fake = FakeImClient();
    addTearDown(fake.dispose);
  });

  /// 控制器测试用的容器(不需要 dio:只碰 IM 客户端)。
  ProviderContainer makeContainer() {
    final container = ProviderContainer(overrides: [
      imClientProvider.overrideWithValue(fake),
      imStatusProvider.overrideWith(_LoggedInImManager.new),
    ]);
    addTearDown(container.dispose);
    return container;
  }

  /// 进入会话:占住订阅(否则 autoDispose 会把控制器连同定时器收走)。
  ///
  /// Args:
  ///   container: 测试容器。
  void openChat(ProviderContainer container) {
    addTearDown(container.listen(chatProvider('u9'), (_, _) {}).close);
    addTearDown(container.listen(chatPeerTypingProvider('u9'), (_, _) {}).close);
  }

  test('收到 typing 帧后 5 秒内 peerTyping 为真,之后自动变假', () {
    fakeAsync((async) {
      final container = makeContainer();
      openChat(container);
      async.flushMicrotasks();
      expect(container.read(chatPeerTypingProvider('u9')), isFalse);

      fake.emitTyping('u9');
      async.flushMicrotasks();
      expect(container.read(chatPeerTypingProvider('u9')), isTrue);

      // 4 秒时还在:过期窗口是 5 秒
      async.elapse(const Duration(seconds: 4));
      expect(container.read(chatPeerTypingProvider('u9')), isTrue);

      // 再过 2 秒(累计 6 秒)自动变假 —— 对端没发新帧就是「没在打字了」
      async.elapse(const Duration(seconds: 2));
      expect(container.read(chatPeerTypingProvider('u9')), isFalse);
    });
  });

  test('连续收到 typing 帧会不断续期:最后一帧后 5 秒才变假', () {
    fakeAsync((async) {
      final container = makeContainer();
      openChat(container);
      async.flushMicrotasks();

      fake.emitTyping('u9');
      async.flushMicrotasks();
      async.elapse(const Duration(seconds: 3));
      fake.emitTyping('u9'); // 续期:再推 5 秒
      async.flushMicrotasks();
      async.elapse(const Duration(seconds: 4));
      expect(container.read(chatPeerTypingProvider('u9')), isTrue);
      async.elapse(const Duration(seconds: 2));
      expect(container.read(chatPeerTypingProvider('u9')), isFalse);
    });
  });

  test('别的会话的 typing 不会点亮当前会话', () {
    fakeAsync((async) {
      final container = makeContainer();
      openChat(container);
      async.flushMicrotasks();

      fake.emitTyping('u8');
      async.flushMicrotasks();
      expect(container.read(chatPeerTypingProvider('u9')), isFalse);
    });
  });

  test('连续输入只按 3 秒节流发 typing,清空输入框不发', () {
    fakeAsync((async) {
      final container = makeContainer();
      openChat(container);
      async.flushMicrotasks();
      final notifier = container.read(chatProvider('u9').notifier);

      notifier.notifyTyping('a'); // 首次:立即发
      notifier.notifyTyping('ab'); // 3 秒内:不发
      async.flushMicrotasks();
      expect(fake.log.where((entry) => entry == 'typing:u9'), hasLength(1));

      async.elapse(const Duration(seconds: 3));
      notifier.notifyTyping('abc'); // 冷却结束:再发
      async.flushMicrotasks();
      expect(fake.log.where((entry) => entry == 'typing:u9'), hasLength(2));

      // 清空输入框意味着「不打了」,不该再发一帧
      async.elapse(const Duration(seconds: 3));
      notifier.notifyTyping('');
      async.flushMicrotasks();
      expect(fake.log.where((entry) => entry == 'typing:u9'), hasLength(2));
    });
  });

  test('离开聊天页后打字状态清零(autoDispose 重建为 false)', () {
    fakeAsync((async) {
      final container = makeContainer();
      final chatSub = container.listen(chatProvider('u9'), (_, _) {});
      final typingSub = container.listen(chatPeerTypingProvider('u9'), (_, _) {});
      async.flushMicrotasks();
      fake.emitTyping('u9');
      async.flushMicrotasks();
      expect(container.read(chatPeerTypingProvider('u9')), isTrue);

      // 关掉订阅 = 离开聊天页:autoDispose 把 provider 连同 5 秒定时器一起销毁
      chatSub.close();
      typingSub.close();
      // Riverpod 的 autoDispose 是「没人听了之后再回收」,给它一拍
      async.elapse(const Duration(milliseconds: 1));

      // 重新读一次是全新实例:必须立刻是 false,不能残留上一次的「正在输入…」
      expect(container.read(chatPeerTypingProvider('u9')), isFalse);
    });
  });

  testWidgets('顶栏只在收到 typing 时显示「对方正在输入…」,5 秒后消失', (tester) async {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
      imClientProvider.overrideWithValue(fake),
      imStatusProvider.overrideWith(_LoggedInImManager.new),
      sessionProvider.overrideWith(_LoggedInSession.new),
      presenceRefreshIntervalProvider.overrideWithValue(null),
    ]);
    addTearDown(container.dispose);
    final router = GoRouter(
      initialLocation: '/chat/u9',
      routes: [
        GoRoute(
          path: '/chat/:peerId',
          builder: (context, state) => ChatPage(
            peerId: state.pathParameters['peerId']!,
            pickImage: () async => null,
          ),
        ),
      ],
    );
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: MaterialApp.router(theme: heartTheme, routerConfig: router),
    ));
    await tester.pumpAndSettle();

    // 没有 typing 帧时,顶栏不该有这行字(不能常驻一个「正在输入…」)
    expect(find.byKey(const Key('chat.typing')), findsNothing);
    expect(find.text('对方正在输入…'), findsNothing);

    fake.emitTyping('u9');
    await tester.pump();
    await tester.pump();
    expect(find.byKey(const Key('chat.typing')), findsOneWidget);
    expect(find.text('对方正在输入…'), findsOneWidget);

    // 5 秒没有新帧 → 自动消失(typing 是可丢信号,不能一直挂着)
    await tester.pump(const Duration(seconds: 6));
    expect(find.byKey(const Key('chat.typing')), findsNothing);
    expect(find.text('对方正在输入…'), findsNothing);
  });
}
