// 动态卡的三个手势约定(U-2 / issue #222):点赞图标、点赞数字、··· 菜单各自独立。
//
// 为什么必须上真机(integration_test),而不是只靠 widget 测试:
// 「点数字打开点赞列表」如果实现成在点赞整块(图标 + 数字)上再叠一层手势,
// `tester.tap` 照样能点中,单测看不出「点哪都开列表 / 点哪都点赞」;真机上手
// 落在图标边缘、数字中间才暴露手感问题。所以这里用**真实 hit test** 钉住:
//
// 1. 图标区与数字区的命中矩形**互不重叠**(矩形级断言,不只靠回调计数);
// 2. 点数字只触发 `onTapLikes`,点图标只触发 `onToggleLike`,互不串;
// 3. `likeCount == 0` 时数字区**不响应**(不弹空列表);
// 4. ··· 菜单能展开并点中「收藏」(菜单项在 overlay 里,必须走真实指针)。
//
// 与 `discovery_filter_test.dart` 同样的写法:直接 pump `PostCard` + 假 `Post`,
// **不碰网络**(所以后端不可达也不影响这条用例)。

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/features/square/models.dart';
import 'package:chatapp_app/features/square/widgets/post_card.dart';

Post _post({required int likeCount}) => Post(
      id: 1,
      author: const FeedAuthor(userId: 9, nickname: 'Alice'),
      text: '正文',
      images: const [],
      likeCount: likeCount,
      commentCount: 0,
      likedByMe: false,
      createdAt: DateTime(2026, 11, 10, 12),
    );

/// 把三个手势的结果原样显示出来,好让用例断言「到底触发了哪一个」。
class _CardHost extends StatefulWidget {
  const _CardHost({required this.likeCount});

  final int likeCount;

  @override
  State<_CardHost> createState() => _CardHostState();
}

class _CardHostState extends State<_CardHost> {
  int _likeTaps = 0;
  int _likesPageTaps = 0;
  String? _menuAction;

  @override
  Widget build(BuildContext context) => Scaffold(
        body: Column(
          children: [
            PostCard(
              post: _post(likeCount: widget.likeCount),
              isMine: false,
              onToggleLike: () => setState(() => _likeTaps += 1),
              onTapLikes: () => setState(() => _likesPageTaps += 1),
              menuAction: (action) => setState(() => _menuAction = action),
            ),
            Text('like=$_likeTaps', key: const Key('host.like')),
            Text('likesPage=$_likesPageTaps', key: const Key('host.likesPage')),
            Text('menu=${_menuAction ?? '-'}', key: const Key('host.menu')),
          ],
        ),
      );
}

String _text(WidgetTester tester, String key) =>
    tester.widget<Text>(find.byKey(Key(key))).data!;

Future<void> _pumpHost(WidgetTester tester, {required int likeCount}) async {
  await tester.pumpWidget(MaterialApp(
    theme: buildAppTheme(brightness: Brightness.light),
    home: _CardHost(likeCount: likeCount),
  ));
  await tester.pumpAndSettle();
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('··· 菜单能展开并点中「收藏」(真实 hit test)', (tester) async {
    await _pumpHost(tester, likeCount: 2);

    await tester.tap(find.byKey(const Key('post.more.1')));
    await tester.pumpAndSettle();

    // 收藏项在菜单里(别人的动态也要有:私密书签,不是 isMine 的二选一)
    expect(find.byKey(const Key('post.menu.favorite')), findsOneWidget);
    expect(find.text('收藏'), findsOneWidget);

    await tester.tap(find.text('收藏'));
    await tester.pumpAndSettle();

    expect(_text(tester, 'host.menu'), 'menu=favorite',
        reason: '菜单项没收到真实指针事件(点中了但回调没派发)');
    expect(_text(tester, 'host.like'), 'like=0', reason: '点菜单不该顺手点赞');
  });

  testWidgets('点赞数字与图标是两个互不重叠的命中区', (tester) async {
    await _pumpHost(tester, likeCount: 2);

    final iconRect = tester.getRect(find.byKey(const Key('post.like.1')));
    final countRect = tester.getRect(find.byKey(const Key('post.likeCount.1')));
    expect(iconRect.overlaps(countRect), isFalse,
        reason: '图标区 $iconRect 与数字区 $countRect 重叠 → 必然「点哪都触发同一个回调」');

    // 点数字 → 只有 onTapLikes
    await tester.tap(find.byKey(const Key('post.likeCount.1')));
    await tester.pumpAndSettle();
    expect(_text(tester, 'host.likesPage'), 'likesPage=1',
        reason: '点数字没有打开点赞列表');
    expect(_text(tester, 'host.like'), 'like=0',
        reason: '点数字串到了点赞回调(这就是整块一个 onTap 的症状)');

    // 点图标 → 只有 onToggleLike
    await tester.tap(find.byKey(const Key('post.like.1')));
    await tester.pumpAndSettle();
    expect(_text(tester, 'host.like'), 'like=1', reason: '点图标没有点赞/取消');
    expect(_text(tester, 'host.likesPage'), 'likesPage=1',
        reason: '点图标串到了「打开点赞列表」(图标语义必须仍是点赞)');
  });

  testWidgets('likeCount == 0 时点数字不触发 onTapLikes', (tester) async {
    await _pumpHost(tester, likeCount: 0);

    await tester.tap(find.byKey(const Key('post.likeCount.1')));
    await tester.pumpAndSettle();

    expect(_text(tester, 'host.likesPage'), 'likesPage=0',
        reason: '0 赞时点数字弹出了一个空列表');
    expect(_text(tester, 'host.like'), 'like=0', reason: '0 赞时点数字串到了点赞回调');
  });
}
