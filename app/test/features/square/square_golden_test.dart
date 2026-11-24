import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/core/theme/ember_colors.dart';
import 'package:chatapp_app/core/ui/ember_ui.dart';
import 'package:chatapp_app/features/square/models.dart';
import 'package:chatapp_app/features/square/widgets/comment_thread.dart';
import 'package:chatapp_app/features/square/widgets/post_card.dart';
import 'package:chatapp_app/features/square/widgets/post_reaction_buttons.dart';
import 'package:chatapp_app/features/square/widgets/square_illustration.dart';

import '../../support/sample_data.dart';

/// 回声(广场)线 golden(E-5.5 page spec §6 第 2 条):**12 张**
///
/// | 组 | 张数 | 覆盖 |
/// |---|---|---|
/// | 动态卡 `PostCard` | 4 | 明 / 暗 × 单图 / 多图 |
/// | 点赞钮 `PostLikeButton` | 4 | 明 / 暗 × 未赞 / 已赞 |
/// | 评论项 `CommentTile` | 2 | 明 / 暗 |
/// | 空态 `EmberEmpty` + unDraw 插画 | 2 | 明 / 暗 |
///
/// 为什么是**组件级 golden**(而不是模拟器整页截图):这里比的是取值 —— 卡片
/// `surface.card` + `radius.lg` + 内边距 20(深色换 `border.divider` 描边)、昵称
/// 17/w600、时间与计数 13 `text.tertiary`、图片格 `radius.sm` 12 + 间距 4、
/// 未赞 Regular `text.tertiary` / 已赞 Fill `brand.default`、评论块
/// `surface.sunken` + `radius.md`。设备字体、真实照片、手势轨迹属于**模拟器手测**
/// (PR 正文「等待模拟器验收」那一段)。
///
/// 图是 `Image.network` 且测试里一律失败(假网络),所以卡片里的图片位显示的是
/// **失败占位**(`surface.sunken` + Phosphor `image`)—— 这正是 §4 的「图片失败」
/// 状态取值,不是缺图。
///
/// 重新生成:`cd app && flutter test --update-goldens test/features/square/square_golden_test.dart`
/// (只在**确认视觉改动就是想要的**之后跑,并人工看一眼 diff 图。)
void main() {
  /// 固定视口 + 关掉动效(骨架 / 在线点呼吸这类循环动画会停在中间值,
  /// 截图不会撞上弹簧中间帧)。
  Future<void> pumpScene(
    WidgetTester tester,
    Widget child, {
    required Brightness brightness,
    Size size = const Size(390, 844),
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(brightness: brightness),
        themeAnimationDuration: Duration.zero,
        home: MediaQuery(
          data: MediaQueryData(size: size, disableAnimations: true),
          child: Scaffold(body: Align(alignment: Alignment.topLeft, child: child)),
        ),
      ),
    );
    await tester.pump();
    // `Image.asset` 的解码是异步的:不先把它解好就截图,空态会截到一块空白
    // (E-5.3 的 `chat_golden_test` 同一个坑,同一套修法)。
    await _precacheAssets(tester);
    await tester.pump();
  }

  Post post({required bool singleImage}) => Post.fromJson(postJson(
        id: 1,
        authorId: 9,
        nickname: '小红',
        text: '今天的风很轻,江边走了很久。',
        images: singleImage
            ? ['http://test/media/posts/1.png']
            : [
                'http://test/media/posts/1.png',
                'http://test/media/posts/2.png',
                'http://test/media/posts/3.png',
              ],
        likeCount: 12,
        commentCount: 3,
      ));

  Widget card(Post item) => SizedBox(
        width: 390,
        child: PostCard(
          post: item,
          isMine: false,
          online: true,
          onTap: () {},
          onTapAuthor: () {},
          onToggleLike: () {},
          onTapLikes: () {},
          onOpenImage: (_) {},
          menuAction: (_) {},
        ),
      );

  /// 点赞钮放在 `surface.page` 上截图:纽本身是透明底,没有底就看不出对比度。
  Widget likeButton({required bool liked, required Brightness brightness}) =>
      Container(
        width: 120,
        height: 96,
        color: buildAppTheme(brightness: brightness).extension<EmberColors>()!.surfacePage,
        alignment: Alignment.center,
        child: PostLikeButton(liked: liked, onTap: () {}),
      );

  for (final brightness in Brightness.values) {
    final mode = brightness == Brightness.light ? 'light' : 'dark';

    testWidgets('动态卡 golden · $mode · 单图', (tester) async {
      await pumpScene(
        tester,
        card(post(singleImage: true)),
        brightness: brightness,
        size: const Size(390, 460),
      );
      await expectLater(
        find.byType(PostCard),
        matchesGoldenFile('goldens/post_card_${mode}_single.png'),
      );
    });

    testWidgets('动态卡 golden · $mode · 多图', (tester) async {
      await pumpScene(
        tester,
        card(post(singleImage: false)),
        brightness: brightness,
        size: const Size(390, 480),
      );
      await expectLater(
        find.byType(PostCard),
        matchesGoldenFile('goldens/post_card_${mode}_multi.png'),
      );
    });

    testWidgets('点赞钮 golden · $mode · 未赞', (tester) async {
      await pumpScene(
        tester,
        likeButton(liked: false, brightness: brightness),
        brightness: brightness,
        size: const Size(120, 96),
      );
      await expectLater(
        find.byType(PostLikeButton),
        matchesGoldenFile('goldens/post_like_${mode}_unliked.png'),
      );
    });

    testWidgets('点赞钮 golden · $mode · 已赞', (tester) async {
      await pumpScene(
        tester,
        likeButton(liked: true, brightness: brightness),
        brightness: brightness,
        size: const Size(120, 96),
      );
      await expectLater(
        find.byType(PostLikeButton),
        matchesGoldenFile('goldens/post_like_${mode}_liked.png'),
      );
    });

    testWidgets('评论项 golden · $mode', (tester) async {
      await pumpScene(
        tester,
        SizedBox(
          width: 390,
          child: CommentTile(
            comment: PostCommentItem.fromJson(commentJson(
              id: 5,
              nickname: '阿秋',
              text: '江边这个点风最大,记得穿外套',
            )),
            depth: 0,
            isMine: false,
            onReply: () {},
            onDelete: () {},
          ),
        ),
        brightness: brightness,
        size: const Size(390, 120),
      );
      await expectLater(
        find.byType(CommentTile),
        matchesGoldenFile('goldens/comment_tile_$mode.png'),
      );
    });

    testWidgets('空态 golden · $mode', (tester) async {
      await pumpScene(
        tester,
        const SizedBox(
          width: 390,
          child: EmberEmpty(
            illustration: SquareIllustration(SquareIllustrationKind.emptyFeed),
            title: '还没有人留下回声',
            description: '发一条,让大家认识你',
            actionLabel: '发第一条',
            onAction: _noop,
          ),
        ),
        brightness: brightness,
        size: const Size(390, 420),
      );
      await expectLater(
        find.byType(EmberEmpty),
        matchesGoldenFile('goldens/empty_state_$mode.png'),
      );
    });
  }
}

/// 空态按钮的回调(金图不点它,但 `EmberEmpty` 要求给)。
void _noop() {}

/// 把**资源图**先解码好再截图(`Image.asset` 的解码是异步的,直接截会截到空)。
///
/// 两遍:先扫树里的 `Image`(动态卡的 `Image.network` 在测试里一律 400,跳过),
/// 再把 [SquareIllustrationKind] 的四张资产(明 / 暗 × 空态 / 失败态)逐个预热 ——
/// 空态场景只用到其中一张,但四张一起预热才能保证任何一张进金图时都已经解好。
Future<void> _precacheAssets(WidgetTester tester) async {
  final context = tester.element(find.byType(Scaffold));
  final elements = find.byType(Image).evaluate().toList();
  await tester.runAsync(() async {
    for (final element in elements) {
      final provider = (element.widget as Image).image;
      if (provider is! AssetImage) continue;
      await precacheImage(provider, element);
    }
    for (final kind in SquareIllustrationKind.values) {
      for (final dark in const [false, true]) {
        await precacheImage(AssetImage(kind.assetPath(dark: dark)), context);
      }
    }
  });
}
