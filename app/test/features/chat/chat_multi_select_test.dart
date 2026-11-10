import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/auth/session.dart';
import 'package:chatapp_app/features/chat/chat_page.dart';
import 'package:chatapp_app/features/presence/presence_controller.dart';
import 'package:chatapp_app/im/im_client.dart';
import 'package:chatapp_app/im/im_manager.dart';

import '../../support/fake_im_client.dart';
import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';
import '../../support/heart_theme.dart';

/// 批次 T-2:多选删除(单方删除)的页面级行为。
///
/// 这里只关心「选中 → 确认 → 删除」这条链与它的两个边界:
/// **删失败不能丢选中**,**已撤回 / 发送中的消息不能选**。真正的网络与幂等在
/// imserver 的集成测试里钉(App 侧只有一条 `deleteMessages` 调用)。

ChatMessage _text(String id, {required bool isSelf, required String text}) => ChatMessage(
      msgId: id,
      peerId: 'u9',
      isSelf: isSelf,
      timestamp: DateTime.now().millisecondsSinceEpoch,
      kind: ChatMessageKind.text,
      text: text,
    );

/// 让 IM 直接处于已登录态(裸 await 真实登录会在假时钟里死锁,同 chat_page_test)。
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

  Future<void> pumpChat(WidgetTester tester, {List<Override> overrides = const []}) async {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final container = ProviderContainer(overrides: [
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

  /// 长按第一条消息 → 点「多选」进多选模式。
  Future<void> enterSelectMode(WidgetTester tester, String firstText) async {
    await tester.longPress(find.text(firstText));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('chat.menu.multi')));
    await tester.pumpAndSettle();
  }

  testWidgets('长按菜单里的「多选」进多选:顶栏变「已选 0 条」,输入栏换成操作条', (tester) async {
    fake.history = {
      'u9': [_text('1', isSelf: false, text: '你好')],
    };
    await pumpChat(tester);

    await enterSelectMode(tester, '你好');

    expect(find.byKey(const Key('chat.select.count')), findsOneWidget);
    expect(find.text('已选 0 条'), findsOneWidget);
    // 输入栏让位给操作条;退出多选才回来
    expect(find.byKey(const Key('chat.input')), findsNothing);
    expect(find.byKey(const Key('chat.select.delete')), findsOneWidget);
    expect(find.byKey(const Key('chat.select.copy')), findsOneWidget);
  });

  testWidgets('点两条消息 → 已选 2 条;再点一条取消 → 已选 1 条', (tester) async {
    fake.history = {
      'u9': [
        _text('1', isSelf: false, text: '第一条'),
        _text('2', isSelf: true, text: '第二条'),
      ],
    };
    await pumpChat(tester);
    await enterSelectMode(tester, '第一条');

    await tester.tap(find.byKey(const Key('chat.bubble:1')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('chat.bubble:2')));
    await tester.pumpAndSettle();
    expect(find.text('已选 2 条'), findsOneWidget);

    await tester.tap(find.byKey(const Key('chat.bubble:1')));
    await tester.pumpAndSettle();
    expect(find.text('已选 1 条'), findsOneWidget);
  });

  testWidgets('删除:确认后一次批量调用、列表少两条、退出多选', (tester) async {
    fake.history = {
      'u9': [
        _text('1', isSelf: false, text: '第一条'),
        _text('2', isSelf: false, text: '第二条'),
        _text('3', isSelf: false, text: '第三条'),
      ],
    };
    await pumpChat(tester);
    await enterSelectMode(tester, '第一条');

    await tester.tap(find.byKey(const Key('chat.bubble:1')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('chat.bubble:3')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('chat.select.delete')));
    await tester.pumpAndSettle();

    // 确认框必须写清「只在你这边删除」:这是删除和撤回的分界线
    expect(find.text('只在你这边删除,对方仍可见。'), findsOneWidget);
    await tester.tap(find.byKey(const Key('chat.select.confirm')));
    await tester.pumpAndSettle();

    expect(fake.log.where((line) => line.startsWith('delete:')).length, 1);
    expect(fake.log, contains('delete:1,3'));
    expect(find.text('第一条'), findsNothing);
    expect(find.text('第三条'), findsNothing);
    expect(find.text('第二条'), findsOneWidget);
    // 删完退出多选,输入栏回来
    expect(find.byKey(const Key('chat.select.count')), findsNothing);
    expect(find.byKey(const Key('chat.input')), findsOneWidget);
    await drainToast(tester);
  });

  testWidgets('删除失败:toast 提示且**保留选中**(下次重试不用重勾)', (tester) async {
    fake.history = {
      'u9': [
        _text('1', isSelf: false, text: '第一条'),
        _text('2', isSelf: false, text: '第二条'),
      ],
    };
    await pumpChat(tester);
    await enterSelectMode(tester, '第一条');
    await tester.tap(find.byKey(const Key('chat.bubble:1')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('chat.bubble:2')));
    await tester.pumpAndSettle();

    fake.deleteError = const ImException(42901, '操作过于频繁,请稍后再试');
    await tester.tap(find.byKey(const Key('chat.select.delete')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('chat.select.confirm')));
    await tester.pumpAndSettle();

    expect(find.text('操作过于频繁,请稍后再试'), findsOneWidget);
    // 两条都还在、还是选中的,仍在多选模式里
    expect(find.text('第一条'), findsOneWidget);
    expect(find.text('第二条'), findsOneWidget);
    expect(find.text('已选 2 条'), findsOneWidget);
    await drainToast(tester);
  });

  testWidgets('已撤回 / 发送中的消息不可选:没有勾选圈,点了也不计数', (tester) async {
    fake.history = {
      'u9': [
        _text('1', isSelf: false, text: '正常的'),
        ChatMessage(
          msgId: '2',
          peerId: 'u9',
          isSelf: false,
          timestamp: DateTime.now().millisecondsSinceEpoch,
          kind: ChatMessageKind.text,
          text: '撤回的',
          isRevoked: true,
        ),
        ChatMessage(
          msgId: 'local-1',
          peerId: 'u9',
          isSelf: true,
          timestamp: DateTime.now().millisecondsSinceEpoch,
          kind: ChatMessageKind.text,
          text: '发送中的',
          isPending: true,
        ),
      ],
    };
    await pumpChat(tester);
    await enterSelectMode(tester, '正常的');

    expect(find.byKey(const Key('chat.select:1')), findsOneWidget);
    expect(find.byKey(const Key('chat.select:2')), findsNothing);
    expect(find.byKey(const Key('chat.select:local-1')), findsNothing);

    // 撤回的那条已是居中灰字,发送中的那条点了也不该被选中。
    // warnIfMissed: false 是**预期**:不可选的气泡不挂点击回调,点上去就该落空。
    await tester.tap(find.byKey(const Key('chat.bubble:local-1')), warnIfMissed: false);
    await tester.pumpAndSettle();
    expect(find.text('已选 0 条'), findsOneWidget);
  });

  testWidgets('复制文本:选中多条按时间顺序用换行连接', (tester) async {
    String? copied;
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') {
        copied = (call.arguments as Map)['text'] as String?;
      }
      return null;
    });
    addTearDown(() => tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null));

    fake.history = {
      'u9': [
        _text('1', isSelf: false, text: '第一句'),
        _text('2', isSelf: true, text: '第二句'),
      ],
    };
    await pumpChat(tester);
    await enterSelectMode(tester, '第一句');
    await tester.tap(find.byKey(const Key('chat.bubble:1')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('chat.bubble:2')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('chat.select.copy')));
    await tester.pumpAndSettle();

    expect(copied, '第一句\n第二句');
    await drainToast(tester);
  });

  testWidgets('取消多选:选择清空,输入栏回来', (tester) async {
    fake.history = {
      'u9': [_text('1', isSelf: false, text: '你好')],
    };
    await pumpChat(tester);
    await enterSelectMode(tester, '你好');
    await tester.tap(find.byKey(const Key('chat.bubble:1')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('chat.select.cancel')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('chat.select.count')), findsNothing);
    expect(find.byKey(const Key('chat.input')), findsOneWidget);
  });

  testWidgets('勾选上限 50 条(imserver 的 ids 上限),第 51 条被拒并提示', (tester) async {
    // 51 条短消息一次全部铺进视口:窗口临时拉高,避免「滚到屏幕外就点不到」
    tester.view.physicalSize = const Size(800, 4000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);

    fake.history = {
      'u9': [
        for (var i = 1; i <= 51; i++) _text('$i', isSelf: false, text: '第 $i 条'),
      ],
    };
    await pumpChat(tester);
    await enterSelectMode(tester, '第 1 条');

    for (var i = 1; i <= 50; i++) {
      await tester.tap(find.byKey(Key('chat.bubble:$i')));
      await tester.pump();
    }
    expect(find.text('已选 50 条'), findsOneWidget);

    await tester.tap(find.byKey(const Key('chat.bubble:51')));
    await tester.pump();
    // 第 51 条不进去:超限的批量请求 imserver 会整批 400,不如当场拦住
    expect(find.text('已选 50 条'), findsOneWidget);
    expect(find.text('一次最多选 50 条'), findsOneWidget);
    await drainToast(tester);
  });

  testWidgets('多选模式下长按不再弹菜单(动作只有勾选)', (tester) async {
    fake.history = {
      'u9': [_text('1', isSelf: false, text: '你好')],
    };
    await pumpChat(tester);
    await enterSelectMode(tester, '你好');

    await tester.longPress(find.byKey(const Key('chat.bubble:1')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('chat.menu.quote')), findsNothing);
    expect(find.byKey(const Key('chat.menu.delete')), findsNothing);
  });
}
