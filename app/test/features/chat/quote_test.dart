// 引用回复(批次 L-2)的 App 侧测试。
//
// 三条核心行为:
//   1. **上行只带 id**:长按「引用」→ 输入栏上方出现引用条 → 发送时帧里带
//      `ref_msg_id`,发完引用条自动消失(否则下一条消息会莫名其妙继续引用);
//   2. **下行快照照原样渲染**:气泡上方显示服务端给的摘要,`revoked` 时只显示
//      「消息已撤回」(不显示原文);
//   3. **点击跳回原消息**:原消息在当前记录里就滚动并高亮,不在就提示,不假装跳过去。
//
// IM 登录态直接 override 成已登录(同 `chat_page_test.dart`):假时钟里让 dio 真跑
// 一遍登录链路会卡死,而那一截与本节要验的东西无关。
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/image_pick.dart';
import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/auth/session.dart';
import 'package:chatapp_app/features/chat/chat_page.dart';
import 'package:chatapp_app/features/chat/quote.dart';
import 'package:chatapp_app/features/presence/presence_controller.dart';
import 'package:chatapp_app/im/im_client.dart';
import 'package:chatapp_app/im/im_manager.dart';

import '../../support/fake_im_client.dart';
import '../../support/heart_theme.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

/// 让 IM 直接处于已登录态(testWidgets 的假时钟里裸 await 走 dio 的登录会死锁)。
class _LoggedInImManager extends ImManager {
  @override
  ImStatus build() => const ImLoggedIn('u3');
}

/// 会话也直接当已登录(matches 缓存依赖它才会去拉数据)。
class _LoggedInSession extends SessionController {
  @override
  SessionState build() => const SessionLoggedIn();
}

ChatMessage _text(String id, {required bool isSelf, required String text}) => ChatMessage(
      msgId: id,
      peerId: 'u9',
      isSelf: isSelf,
      timestamp: DateTime.now().millisecondsSinceEpoch,
      kind: ChatMessageKind.text,
      text: text,
    );

/// 一条**带引用**的消息(模拟服务端下行帧解析后的结果)。
ChatMessage _quoted(String id, {required String text, required QuoteRef ref}) => ChatMessage(
      msgId: id,
      peerId: 'u9',
      isSelf: false,
      timestamp: DateTime.now().millisecondsSinceEpoch,
      kind: ChatMessageKind.text,
      text: text,
      ref: ref,
    );

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

  /// 进聊天页(peer = u9)。
  ///
  /// Args:
  ///   tester: 测试器。
  ///   pickImage: 相册选图注入(本文件用不到,保持默认)。
  Future<void> pumpChat(WidgetTester tester, {PickImage? pickImage}) async {
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
            pickImage: pickImage ?? () async => null,
          ),
        ),
      ],
    );
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: MaterialApp.router(theme: heartTheme, routerConfig: router),
    ));
    await tester.pumpAndSettle();
  }

  test('canQuote:灰条 / 已撤回 / 发送中 / 本地 id 都不能引用', () {
    final normal = _text('900124', isSelf: false, text: '今晚吃饭?');
    expect(canQuote(normal), isTrue);

    expect(canQuote(normal.copyWith(isRevoked: true)), isFalse);
    expect(canQuote(normal.copyWith(isPending: true)), isFalse);
    expect(canQuote(normal.copyWith(isFailed: true)), isFalse);
    // 本地乐观消息的 id 服务端不认识,引用它等于引用一个不存在的消息
    expect(canQuote(_text('local-1', isSelf: true, text: 'x')), isFalse);
    // 系统灰条没有可引用的内容
    final notice = ChatMessage(
      msgId: '900125',
      peerId: 'u9',
      isSelf: false,
      timestamp: DateTime.now().millisecondsSinceEpoch,
      kind: ChatMessageKind.matchNotice,
      text: '你们已互相喜欢',
    );
    expect(canQuote(notice), isFalse);

    expect(quoteSummaryOf(normal), '今晚吃饭?');
    expect(
      quoteSummaryOf(ChatMessage(
        msgId: '900126',
        peerId: 'u9',
        isSelf: false,
        timestamp: 0,
        kind: ChatMessageKind.image,
      )),
      '[图片]',
    );
  });

  testWidgets('长按「引用」→ 引用条 → 发送带 ref_msg_id,发完引用条消失', (tester) async {
    fake.history['u9'] = [_text('900124', isSelf: false, text: '今晚吃饭?')];
    await pumpChat(tester);

    // 长按气泡 → 菜单里有「引用」
    await tester.longPress(find.text('今晚吃饭?'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('chat.menu.quote')), findsOneWidget);

    await tester.tap(find.byKey(const Key('chat.menu.quote')));
    await tester.pumpAndSettle();

    // 输入栏上方出现引用条:署名 + 摘要
    expect(find.byKey(const Key('chat.quoteBar')), findsOneWidget);
    expect(find.text('引用 小红'), findsOneWidget);
    expect(find.byKey(const Key('chat.quoteBar.text')), findsOneWidget);

    // 发出去:上行**只带 ref_msg_id**(假客户端把它记进流水)
    await tester.enterText(find.byKey(const Key('chat.input')), '好,六点');
    await tester.tap(find.byKey(const Key('chat.send')));
    await tester.pumpAndSettle();
    expect(fake.log, contains('send:u9:好,六点:ref=900124'));

    // 引用条用完即清:下一条消息不该莫名其妙继续引用
    expect(find.byKey(const Key('chat.quoteBar')), findsNothing);

    // 刚发出的气泡上也带着引用块(上行只有 id,本地那份快照留在气泡上)
    expect(find.byKey(const Key('chat.quote:sent-1')), findsOneWidget);
  });

  testWidgets('点引用条的 × 取消引用,发送不再带 ref_msg_id', (tester) async {
    fake.history['u9'] = [_text('900124', isSelf: false, text: '今晚吃饭?')];
    await pumpChat(tester);

    await tester.longPress(find.text('今晚吃饭?'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('chat.menu.quote')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('chat.quoteBar')), findsOneWidget);

    await tester.tap(find.byKey(const Key('chat.quoteBar.close')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('chat.quoteBar')), findsNothing);

    await tester.enterText(find.byKey(const Key('chat.input')), '不引用了');
    await tester.tap(find.byKey(const Key('chat.send')));
    await tester.pumpAndSettle();
    expect(fake.log, contains('send:u9:不引用了'));
    expect(fake.log.any((entry) => entry.contains('ref=')), isFalse);
  });

  testWidgets('下行带引用的消息:气泡上方显示服务端摘要', (tester) async {
    fake.history['u9'] = [
      _quoted('900200', text: '好,六点', ref: const QuoteRef(
        msgId: 900124,
        from: 'u9',
        kind: 'text',
        text: '今晚吃饭?',
        revoked: false,
      )),
    ];
    await pumpChat(tester);

    expect(find.byKey(const Key('chat.quote:900200')), findsOneWidget);
    expect(find.text('今晚吃饭?'), findsOneWidget);
    expect(find.text('好,六点'), findsOneWidget);
  });

  testWidgets('引用一条已撤回的消息:只显示「消息已撤回」,不显示原文', (tester) async {
    fake.history['u9'] = [
      _quoted('900201', text: '你刚才说啥', ref: const QuoteRef(
        msgId: 900125,
        from: 'u9',
        kind: 'text',
        text: '',
        revoked: true,
      )),
    ];
    await pumpChat(tester);

    expect(find.byKey(const Key('chat.quote.revoked')), findsOneWidget);
    expect(find.text('消息已撤回'), findsOneWidget);
  });

  testWidgets('菜单打开后列表把气泡回收,仍然能选中引用(真机键盘压缩视口)', (tester) async {
    // 真机验收现场:点「引用」→ 菜单关闭 → 输入框重新获得焦点 → 键盘弹起 →
    // Scaffold 视口被压小 → ListView 把刚才那条气泡回收掉,它的 BuildContext
    // 当场失效。所以「菜单关掉之后」绝不能再拿 itemContext.mounted 做判断,
    // 否则引用 / 复制 / 撤回 / 删除全都会被静默吞掉(菜单关了、什么都没发生)。
    fake.history['u9'] = [
      for (var i = 0; i < 40; i++)
        _text('${900000 + i}', isSelf: false, text: '第 $i 条'),
    ];
    await pumpChat(tester);

    // 长按最新那条(列表底部,视口内)
    await tester.longPress(find.text('第 39 条'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('chat.menu.quote')), findsOneWidget);

    // 把列表滚到另一端:被长按的气泡被回收,itemContext 失效(等价于键盘压小视口)
    final scrollable = tester.state<ScrollableState>(find.descendant(
      of: find.byKey(const Key('chat.list')),
      matching: find.byType(Scrollable),
    ));
    scrollable.position.jumpTo(scrollable.position.maxScrollExtent);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('chat.menu.quote')));
    await tester.pumpAndSettle();

    // 引用条照样要出来
    expect(find.byKey(const Key('chat.quoteBar')), findsOneWidget);
    expect(find.byKey(const Key('chat.quoteBar.text')), findsOneWidget);
  });

  testWidgets('点引用块:原消息在记录里就滚过去并高亮', (tester) async {
    fake.history['u9'] = [
      _text('900124', isSelf: false, text: '今晚吃饭?'),
      _quoted('900200', text: '好,六点', ref: const QuoteRef(
        msgId: 900124,
        from: 'u9',
        kind: 'text',
        text: '今晚吃饭?',
        revoked: false,
      )),
    ];
    await pumpChat(tester);

    await tester.tap(find.byKey(const Key('chat.quote:900200')));
    // _focusOn 要跨几帧:等 endOfFrame → 定位 → ensureVisible(250ms)→ setState
    for (var i = 0; i < 6; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(find.byKey(const Key('chat.highlight:900124')), findsOneWidget);
    // 高亮 1.5 秒后自动取消:把定时器跑完,别留给下一个用例(会报 pending timer)
    await tester.pump(const Duration(seconds: 2));
  });

  testWidgets('点引用块:原消息不在当前记录里 → 提示,不跳', (tester) async {
    fake.history['u9'] = [
      _quoted('900200', text: '好,六点', ref: const QuoteRef(
        msgId: 900999,
        from: 'u9',
        kind: 'text',
        text: '很久以前的话',
        revoked: false,
      )),
    ];
    await pumpChat(tester);

    await tester.tap(find.byKey(const Key('chat.quote:900200')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('原消息不在当前记录中'), findsOneWidget);
  });
}
