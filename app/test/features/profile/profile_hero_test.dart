import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/core/widgets/avatar_hero.dart';
import 'package:chatapp_app/features/auth/session.dart';
import 'package:chatapp_app/features/chat/chat_page.dart';
import 'package:chatapp_app/features/discovery/widgets/profile_card.dart';
import 'package:chatapp_app/features/presence/presence_controller.dart';
import 'package:chatapp_app/features/profile/user_profile_page.dart';
import 'package:chatapp_app/features/profile/widgets/profile_photo_header.dart';
import 'package:chatapp_app/im/im_client.dart';
import 'package:chatapp_app/im/im_manager.dart';

import '../../support/fake_im_client.dart';
import '../../support/harness.dart';
import '../../support/heart_theme.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

/// E-5.4 page spec §3「Hero 转场本单必须落地」:**三条入口都要通**。
///
/// 1. 发现页卡照片 → 资料页(tag `photo-user-{userId}`)
/// 2. 对话页顶栏头像 → 资料页(tag `avatar-chat-{peerId}`)
/// 3. 对话页气泡头像 → 资料页(tag `avatar-msg-{msgId}`)
///
/// 为什么要测「两端 tag 一致」而不只测「有 Hero」:Hero 只在 push 之后**下一帧末**
/// 扫描一次,两端 tag 不同或目标端首帧没有同名 Hero 时**不会报错、只是不飞** ——
/// 肉眼像「转场没做」,测试里只看「有 Hero 组件」也抓不到。这里按目标页内作用域
/// 取 AvatarHero(被盖住的来源页仍在树里,全局 find 会撞到它自己的 Hero)。
const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

class _LoggedInImManager extends ImManager {
  @override
  ImStatus build() => const ImLoggedIn('u3');
}

class _LoggedInSession extends SessionController {
  @override
  SessionState build() => const SessionLoggedIn();
}

ChatMessage _peerText(String id, String text) => ChatMessage(
      msgId: id,
      peerId: 'u9',
      isSelf: false,
      timestamp: 1700000000000,
      kind: ChatMessageKind.text,
      text: text,
    );

/// 目标端的 Hero tag(限定在资料页内查找)。
String? _targetTag(WidgetTester tester) {
  final heroes = tester.widgetList<AvatarHero>(find.descendant(
    of: find.byType(UserProfilePage),
    matching: find.byType(AvatarHero),
  ));
  expect(heroes, isNotEmpty, reason: '资料页里没有 AvatarHero,转场无从落地');
  return heroes.first.tag;
}

void main() {
  testWidgets('发现页卡照片 → 资料页:两端 tag 都是 photo-user-9', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /discovery/candidates': (options) => ok([candidateJson(userId: 9)]),
      'GET /users/9': (options) => ok(publicProfileJson(userId: 9, nickname: '小红')),
      'GET /presence': (options) => ok({'results': []}),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    // 来源侧:顶卡照片层包了同名 AvatarHero
    final sourceTags = tester
        .widgetList<AvatarHero>(find.descendant(
          of: find.byType(ProfileCard),
          matching: find.byType(AvatarHero),
        ))
        .map((hero) => hero.tag)
        .toSet();
    expect(sourceTags, contains('photo-user-9'));

    await tester.tap(find.byKey(const Key('deck.topCard')));
    await tester.pumpAndSettle();

    expect(find.byType(UserProfilePage), findsOneWidget);
    expect(_targetTag(tester), 'photo-user-9');
  });

  group('对话页', () {
    late ScriptedAdapter adapter;
    late FakeImClient fake;

    setUp(() {
      SharedPreferences.setMockInitialValues({});
      adapter = ScriptedAdapter({
        'GET /matches':
            (options) => ok(pageJson([matchJson(userId: 9, nickname: '小红')])),
        'GET /users/me': (options) => ok(profileJson()),
        'GET /presence': (options) => ok({'results': []}),
        'GET /users/9': (options) => ok(publicProfileJson(userId: 9, nickname: '小红')),
      });
      fake = FakeImClient();
      addTearDown(fake.dispose);
    });

    Future<void> pumpChat(WidgetTester tester) async {
      final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))
        ..httpClientAdapter = adapter;
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
          GoRoute(
            path: '/users/:id',
            builder: (context, state) => UserProfilePage(
              userId: int.parse(state.pathParameters['id']!),
              heroTag: state.extra as String?,
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

    testWidgets('顶栏头像 → 资料页:tag avatar-chat-u9', (tester) async {
      await pumpChat(tester);

      await tester.tap(find.byKey(const Key('chat.title')));
      await tester.pumpAndSettle();

      expect(find.byType(UserProfilePage), findsOneWidget);
      expect(_targetTag(tester), 'avatar-chat-u9');
    });

    testWidgets('气泡头像 → 资料页:tag avatar-msg-m1(每条消息一个)', (tester) async {
      fake.history = {
        'u9': [_peerText('m1', '你好')],
      };
      await pumpChat(tester);

      // 来源侧:这条消息的头像被同名 AvatarHero 包住(hero 在外壳的 builder 里,
      // 是气泡头像那个 pressable 的**子节点**)
      final sourceTags = tester
          .widgetList<AvatarHero>(find.descendant(
            of: find.byKey(const Key('chat.avatar:m1')),
            matching: find.byType(AvatarHero),
          ))
          .map((hero) => hero.tag)
          .toSet();
      expect(sourceTags, contains('avatar-msg-m1'));

      await tester.tap(find.byKey(const Key('chat.avatar:m1')));
      await tester.pumpAndSettle();

      expect(find.byType(UserProfilePage), findsOneWidget);
      expect(_targetTag(tester), 'avatar-msg-m1');

      // 收尾先把整棵树卸掉,再让 teardown 释放 ProviderContainer:
      // 否则 ChatController 的 Ref 会在「树还在、容器已 dispose」的瞬间被用到,
      // 抛 UnmountedRefException(污染下一个用例的 finalize)。
      await tester.pumpWidget(const SizedBox.shrink());
    });
  });

  testWidgets('系统「移除动画」→ 头图不包 Hero(退化为淡入)', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: heartTheme,
        home: MediaQuery(
          data: const MediaQueryData(disableAnimations: true),
          child: const Scaffold(
            body: ProfilePhotoHeader(
              photoUrl: null,
              nickname: '小红',
              heroTag: 'photo-user-9',
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    // tag 照传,但减弱动态效果时 AvatarHero 直接渲染 child(§7.3 / §8.4)
    expect(find.byType(Hero), findsNothing);
    expect(find.byType(ProfilePhotoHeader), findsOneWidget);
  });
}
