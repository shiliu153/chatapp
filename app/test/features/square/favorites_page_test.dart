import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

ScriptedAdapter _adapter(Map<String, dynamic> favoritesPage) => ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(nickname: '小明')),
      'GET /posts': (options) => ok(pageJson([postJson(id: 1, text: '广场的')])),
      'GET /presence': (options) => ok({'results': []}),
      'GET /feed/favorites': (options) => ok(favoritesPage),
    });

/// 走到「我的 → 我的收藏」。
///
/// 「我的收藏」紧挨「我的动态」,在 800×600 的测试窗口里会压在悬浮底栏下面:
/// `ensureVisible` 只保证「在视口内」,底栏是浮在 body 之上的,所以要再往上滚一点
/// 才能拿到真实指针(真机上点被底栏盖住的行同样是点不动的)。
Future<void> _openFavorites(WidgetTester tester) async {
  await tester.tap(navTab('我的'));
  await tester.pumpAndSettle();
  await tester.ensureVisible(find.byKey(const Key('my.row.favorites')));
  await tester.pumpAndSettle();
  await tester.drag(find.byKey(const Key('my.row.posts')), const Offset(0, -120));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('my.row.favorites')));
  await tester.pumpAndSettle();
}

/// 我的收藏:入口在「我的」页里「我的动态」旁边;取消收藏后该行必须消失
/// (服务端已把它移出收藏,本地留着就是假状态)。
void main() {
  testWidgets('我的收藏:取消收藏后行消失并提示', (tester) async {
    final adapter = _adapter(cursorPageJson([
      postJson(id: 9, authorId: 12, nickname: '小雨12', text: '收藏的', isFavorited: true),
    ]));
    adapter.routes['DELETE /posts/9/favorite'] = (options) => ok({}, status: 204);

    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await _openFavorites(tester);

    expect(find.text('我的收藏'), findsWidgets); // 顶栏标题
    expect(find.byKey(const Key('favorites.list')), findsOneWidget);
    expect(find.text('收藏的'), findsOneWidget);

    await tester.tap(find.byKey(const Key('post.more.9')));
    await tester.pumpAndSettle();
    // 已收藏 → 菜单项是「取消收藏」
    expect(find.text('取消收藏'), findsOneWidget);
    await tester.tap(find.text('取消收藏'));
    await tester.pumpAndSettle();

    expect(
        adapter.log.where((r) => r.method == 'DELETE' && r.path == '/posts/9/favorite'),
        hasLength(1));
    expect(find.text('收藏的'), findsNothing);
    expect(find.text('还没有收藏'), findsOneWidget); // 只剩这一条,取消后就空了
    expect(find.text('已取消收藏'), findsOneWidget);

    await drainToast(tester);
  });

  testWidgets('收藏列表为空:空态文案,不崩', (tester) async {
    final adapter = _adapter(cursorPageJson([]));

    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();
    await _openFavorites(tester);

    expect(find.byKey(const Key('favorites.empty')), findsOneWidget);
    expect(find.text('还没有收藏'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
