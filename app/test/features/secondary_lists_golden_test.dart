import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/chat/search_page.dart';
import 'package:chatapp_app/features/notifications/notifications_page.dart';
import 'package:chatapp_app/features/square/favorites_page.dart';
import 'package:chatapp_app/im/im_client.dart';

import '../support/fake_im_client.dart';
import '../support/harness.dart';
import '../support/sample_data.dart';
import '../support/scripted_adapter.dart';

/// 二级页·列表组 golden(E-5.6d page spec §1 D 组 / issue #509 验收第 2 条):**8 张**
///
/// | 页 | 张数 | 覆盖 |
/// |---|---|---|
/// | 通知 `NotificationsPage` | 4 | 明 / 暗 × 有内容 / 空 |
/// | 我的收藏 `FavoritesPage` | 2 | 明 / 暗 × 有内容 |
/// | 聊天记录搜索 `SearchPage` | 2 | 明 / 暗 × 有命中 |
///
/// 为什么是**整页 golden**(而不是组件级):D 组的验收对象正是「§9.4 顶栏 + 列表行 +
/// 空态」三者的组合 —— 顶栏 52 / 返回 22 Phosphor `caret-left` / 标题 17-w600 居中、
/// 行高 68、正文 17-w600 + 时间 13 `text.secondary`、分隔线 1px `border.divider`、
/// 空态插画 + 标题 + 说明。设备字体、真实照片、手势轨迹属于**模拟器手测**
/// (PR 正文「等待模拟器验收」那一段)。
///
/// 头像一律是 `NetworkImage`:假网络下必然失败,于是 `EmberAvatar` 显示首字柔色底
/// —— 这是 §8.3 的「无照片」取值,不是缺图。空态里的 unDraw 插画是 `Image.asset`,
/// 必须先预热解码再截图(否则截到一块空白,E-5.3 / E-5.5 同一个坑)。
///
/// 重新生成:`cd app && flutter test --update-goldens test/features/secondary_lists_golden_test.dart`
/// (只在**确认视觉改动就是想要的**之后跑,并人工看一眼 diff 图。)
void main() {
  /// 固定 390×844 视口 + 关掉动效(骨架呼吸 / 按压弹簧会停在中间帧)。
  Future<void> pumpListPage(
    WidgetTester tester,
    ScriptedAdapter adapter,
    Widget page, {
    required Brightness brightness,
    FakeImClient? imClient,
  }) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await pumpPage(
      tester,
      adapter,
      MediaQuery(
        // `disableAnimations` 让弹簧与骨架呼吸停在终态(§7.3 reduced-motion 口径)。
        data: const MediaQueryData(
          size: Size(390, 844),
          disableAnimations: true,
        ),
        child: page,
      ),
      brightness: brightness,
      imClient: imClient,
    );
    // 网络链 + 首帧布局:8 帧足够放行(骨架 / 涟漪这类循环动画不能用 pumpAndSettle)。
    await pumpFrames(tester);
    await _precacheIllustrations(tester);
    await tester.pump();
  }

  ScriptedAdapter notificationAdapter({required bool empty}) => ScriptedAdapter({
        'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
        'GET /users/me': (options) => ok(profileJson(nickname: '小明')),
        'GET /presence': (options) => ok({'results': []}),
        'GET /notifications/unread_count': (options) => ok({'unread': 2}),
        'GET /notifications': (options) => ok(cursorPageJson(empty
            ? []
            : [
                notificationJson(
                  id: 3,
                  text: '小红 赞了你的动态',
                  targetKind: 'post',
                  targetId: 9,
                ),
                notificationJson(
                  id: 2,
                  kind: 'post_comment',
                  text: '阿秋 评论了你的动态:江边这个点风最大,记得穿外套',
                  actorId: 11,
                  actorNickname: '阿秋',
                  targetKind: 'post',
                  targetId: 9,
                ),
                notificationJson(
                  id: 1,
                  kind: 'match',
                  text: '你和 小雨 互相喜欢了',
                  isRead: true,
                  actorId: 12,
                  actorNickname: '小雨',
                  targetKind: 'user',
                  targetId: 12,
                ),
              ])),
      });

  ScriptedAdapter favoritesAdapter() => ScriptedAdapter({
        'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
        'GET /users/me': (options) => ok(profileJson(nickname: '小明')),
        'GET /presence': (options) => ok({'results': []}),
        'GET /feed/favorites': (options) => ok(cursorPageJson([
              postJson(
                id: 9,
                authorId: 12,
                nickname: '小雨12',
                text: '收藏的一句话:江边走了很久,风很轻。',
                isFavorited: true,
                likeCount: 4,
                commentCount: 1,
              ),
            ])),
      });

  ScriptedAdapter searchAdapter() => ScriptedAdapter({
        'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
        'GET /users/me': (options) => ok(profileJson(nickname: '小明')),
        'GET /presence': (options) => ok({'results': []}),
      });

  for (final brightness in Brightness.values) {
    final mode = brightness == Brightness.light ? 'light' : 'dark';

    testWidgets('通知列表 golden · $mode · 有内容', (tester) async {
      await pumpListPage(
        tester,
        notificationAdapter(empty: false),
        const NotificationsPage(),
        brightness: brightness,
      );
      await expectLater(
        find.byType(NotificationsPage),
        matchesGoldenFile('goldens/notifications_${mode}_list.png'),
      );
    });

    testWidgets('通知列表 golden · $mode · 空', (tester) async {
      await pumpListPage(
        tester,
        notificationAdapter(empty: true),
        const NotificationsPage(),
        brightness: brightness,
      );
      await expectLater(
        find.byType(NotificationsPage),
        matchesGoldenFile('goldens/notifications_${mode}_empty.png'),
      );
    });

    testWidgets('我的收藏 golden · $mode', (tester) async {
      await pumpListPage(
        tester,
        favoritesAdapter(),
        const FavoritesPage(),
        brightness: brightness,
      );
      await expectLater(
        find.byType(FavoritesPage),
        matchesGoldenFile('goldens/favorites_${mode}_list.png'),
      );
    });

    testWidgets('聊天记录搜索 golden · $mode', (tester) async {
      final fake = FakeImClient()
        ..searchHits = [
          ImSearchHit(
            msgId: '42',
            seq: 7,
            peerId: 'u9',
            text: '晚上吃火锅吗',
            timestamp: DateTime(2026, 11, 10, 21, 12).millisecondsSinceEpoch,
            peerName: '阿九',
          ),
          ImSearchHit(
            msgId: '43',
            seq: 8,
            peerId: 'u9',
            text: '火锅店订在江边那家,七点半',
            timestamp: DateTime(2026, 11, 10, 21, 15).millisecondsSinceEpoch,
            peerName: '阿九',
          ),
        ];
      await pumpListPage(
        tester,
        searchAdapter(),
        const SearchPage(),
        brightness: brightness,
        imClient: fake,
      );
      await tester.enterText(find.byKey(const Key('search.input')), '火锅');
      await tester.pump(const Duration(milliseconds: 350)); // 过防抖
      await pumpFrames(tester);
      // 刻意保留**聚焦态**:搜索页是 `autofocus: true` 的,用户打开时看到的就是
      // §8.3 的 focus 取值(2px `brand.default` + 2px 外扩)。光标闪烁在假时钟下
      // 相位固定,金图不会飘。
      await expectLater(
        find.byType(SearchPage),
        matchesGoldenFile('goldens/search_${mode}_hits.png'),
      );
    });
  }
}

/// 把空态用到的四张 unDraw 插画(明 / 暗 × 对话线 / 回声线)先解码好再截图。
///
/// `Image.asset` 的解码是异步的:不预热就会截到一块空白(E-5.3 / E-5.5 同一个坑)。
Future<void> _precacheIllustrations(WidgetTester tester) async {
  final context = tester.element(find.byType(MaterialApp));
  await tester.runAsync(() async {
    for (final asset in const [
      'assets/illustrations/chat_empty_light.png',
      'assets/illustrations/chat_empty_dark.png',
      'assets/illustrations/chat_error_light.png',
      'assets/illustrations/chat_error_dark.png',
      'assets/illustrations/square_empty_light.png',
      'assets/illustrations/square_empty_dark.png',
      'assets/illustrations/square_error_light.png',
      'assets/illustrations/square_error_dark.png',
    ]) {
      await precacheImage(AssetImage(asset), context);
    }
  });
}
