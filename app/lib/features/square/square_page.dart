import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_typography.dart';
import '../../core/theme/ember_colors.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import '../chat/widgets/photo_viewer.dart';
import '../presence/presence_controller.dart';
import '../profile/profile_controller.dart';
import 'feed_repository.dart';
import 'models.dart';
import 'post_actions.dart';
import 'post_detail_args.dart';
import 'square_controller.dart';
import 'widgets/post_card.dart';
import 'widgets/square_illustration.dart';
import 'widgets/square_skeleton.dart';

/// 回声顶部的两个 tab(批次 I):推荐 = `/posts`,关注 = `/feed/following`。
enum SquareTab { recommend, following }

/// 「回声」tab 根页面:动态流(E-5.5 page spec §1 / §3 / §4 / §5)。
///
/// 本单只换视觉与动效:`square_controller` / `post_detail_controller` /
/// `feed_repository` 一行没动。用户看得见的变化(page spec §1 的表):
/// 1. 顶栏:标题「回声」`display` 32(Fraunces)+ 右侧发帖 `plus`(Phosphor,
///    `brand.default`,热区 48)—— 原来的渐变 FAB 退役(§7 拍板 #5:顶栏 plus);
/// 2. 水平内边距 16 → **20**(§5.2);
/// 3. 动态卡换 [`PostCard`] / [`EmberCard`](见 `widgets/post_card.dart`);
/// 4. 空态 / 错误态换 [`EmberEmpty`] + unDraw 插画(§5,灰色图标占位是 §6 明令禁止的);
/// 5. 骨架换 [`EmberSkeleton`](`surface.sunken` 色块);
/// 6. 点卡进详情:有图走**图片 Hero**,无图沿用整卡 Hero(§1 第 9 条)。
class SquarePage extends ConsumerStatefulWidget {
  /// 构造页面。
  const SquarePage({super.key});

  @override
  ConsumerState<SquarePage> createState() => _SquarePageState();
}

class _SquarePageState extends ConsumerState<SquarePage> {
  final _scroll = ScrollController();

  /// 当前选中的 tab;默认「推荐」(与改造前行为一致)。
  SquareTab _tab = SquareTab.recommend;

  /// 正在飞 Hero 的动态 id;null = 无飞行。
  /// 互斥不变式见 page spec §5 / `PostCard` 的 Hero 纪律:飞行期间该卡的头像 Hero
  /// 让位(整卡态),返回后还原。
  int? _heroPostId;

  /// 当前 tab 对应的控制器(两个 tab 共用 [PostFeedController] 接口)。
  PostFeedController get _feed => switch (_tab) {
        SquareTab.recommend => ref.read(squareProvider.notifier),
        SquareTab.following => ref.read(followingProvider.notifier),
      };

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.extentAfter < 300) {
        _feed.loadMore();
      }
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  /// 进详情;[focusComment] 为真时详情页把焦点落进评论输入框(评论钮的语义,
  /// spec §4「评论钮 …点进详情并聚焦输入」)。
  Future<void> _openDetail(Post post, {bool focusComment = false}) async {
    // 飞行中忽略新点击(防快速连点把飞行中的 Hero 卸载)
    if (_heroPostId != null) return;
    final withImages = post.images.isNotEmpty;
    setState(() => _heroPostId = post.id);
    try {
      await context.push(
        '/posts/${post.id}',
        extra: PostDetailArgs(
          // 有图:图片 Hero(卡图片 → 详情图片);无图:整卡 Hero(批次⑤口径)。
          heroTag: withImages ? null : 'card-post-${post.id}',
          imageHeroTag: withImages ? 'post-image-${post.id}' : null,
          seed: post,
          focusComment: focusComment,
        ),
      );
    } finally {
      if (mounted) setState(() => _heroPostId = null);
    }
  }

  Future<void> _toggleLike(Post post) async {
    try {
      await _feed.toggleLike(post);
    } on ApiException catch (error) {
      if (mounted) EmberToast.show(context, error.message);
    }
  }

  /// 收藏 / 取消收藏:乐观翻转在控制器里,失败回滚后由这里提示。
  Future<void> _toggleFavorite(Post post) async {
    final wasFavorited = post.isFavorited;
    try {
      await _feed.toggleFavorite(post);
      if (!mounted) return;
      EmberToast.show(context, wasFavorited ? '已取消收藏' : '已收藏');
    } on ApiException catch (error) {
      if (mounted) EmberToast.show(context, error.message);
    }
  }

  Future<void> _deletePost(Post post) async {
    final confirmed = await confirmDeletePost(context);
    if (!confirmed || !mounted) return;
    try {
      await ref.read(feedRepositoryProvider).deletePost(post.id);
      await _feed.reload();
      ref.invalidate(myPostsProvider);
      if (mounted) EmberToast.show(context, '已删除');
    } on ApiException catch (error) {
      if (mounted) EmberToast.show(context, error.message);
    }
  }

  /// 切 tab:清掉滚动位置,否则从「推荐」翻到第 5 页再切「关注」会落在列表中间。
  void _switchTab(SquareTab tab) {
    if (tab == _tab) return;
    setState(() => _tab = tab);
    if (_scroll.hasClients) _scroll.jumpTo(0);
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final posts = switch (_tab) {
      SquareTab.recommend => ref.watch(squareProvider),
      SquareTab.following => ref.watch(followingProvider),
    };
    final presenceById = ref.watch(presenceProvider);
    final myId = ref.watch(profileProvider).value?.userId;
    final isFollowingTab = _tab == SquareTab.following;
    return Scaffold(
      backgroundColor: colors.surfacePage,
      body: SafeArea(
        bottom: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _header(colors),
            Padding(
              padding: EdgeInsets.symmetric(horizontal: tokens.space20),
              child: _SquareTabs(value: _tab, onChanged: _switchTab),
            ),
            SizedBox(height: tokens.space8),
            Expanded(
              child: posts.when(
                loading: () => const Padding(
                  padding: EdgeInsets.symmetric(horizontal: tokens.space20),
                  child: SquareSkeleton(),
                ),
                error: (error, _) => _centered(
                  EmberEmpty(
                    illustration: const SquareIllustration(
                      SquareIllustrationKind.loadFailed,
                    ),
                    title: '加载失败',
                    description: apiMessageOf(error),
                    actionLabel: '重试',
                    actionKey: const Key('square.retry'),
                    onAction: () => switch (_tab) {
                      SquareTab.recommend => ref.invalidate(squareProvider),
                      SquareTab.following => ref.invalidate(followingProvider),
                    },
                  ),
                ),
                data: (items) {
                  ref.read(presenceProvider.notifier).track(
                      isFollowingTab ? 'square:following' : 'square',
                      [for (final post in items) post.author.userId]);
                  if (items.isEmpty) return _empty(isFollowingTab);
                  return RefreshIndicator(
                    backgroundColor: colors.surfaceCard,
                    color: colors.brandDefault,
                    onRefresh: _feed.reload,
                    child: ListView.separated(
                      key: Key(
                          isFollowingTab ? 'square.following.list' : 'square.list'),
                      controller: _scroll,
                      padding: EdgeInsets.fromLTRB(
                        tokens.space20,
                        tokens.space4,
                        tokens.space20,
                        // 给悬浮底栏留出气口(高 64 + 底距 10 + 20)
                        tokens.sizeNavHeight +
                            EmberComponentSizes.navBottomInset +
                            tokens.space20,
                      ),
                      itemCount: items.length,
                      separatorBuilder: (_, _) => SizedBox(height: tokens.space12),
                      itemBuilder: (context, index) {
                        final post = items[index];
                        final inFlight = _heroPostId == post.id;
                        final withImages = post.images.isNotEmpty;
                        // Hero 互斥(page spec §5 / PostCard 的 Hero 纪律):
                        // 整卡飞行期间该卡头像让位;图片飞行时头像 Hero 与图片 Hero
                        // 是同一张卡里的兄弟节点,互不嵌套。
                        final cardFlying = inFlight && !withImages;
                        return PostCard(
                          post: post,
                          // tag 按 postId 派生(不是 userId):同作者多卡各得不同 tag
                          heroTag:
                              cardFlying ? null : 'avatar-post-${post.id}',
                          isMine: post.author.userId == myId,
                          online: presenceById[post.author.userId]?.online == true,
                          onTapAuthor: post.author.userId == myId
                              ? null
                              : () => context.push('/users/${post.author.userId}',
                                  extra: 'avatar-post-${post.id}'),
                          onToggleLike: () => _toggleLike(post),
                          // 数字区才是点赞列表入口(图标区仍是点赞/取消)
                          onTapLikes: () => context.push('/posts/${post.id}/likes'),
                          onTap: () => _openDetail(post),
                          cardHeroTag: cardFlying ? 'card-post-${post.id}' : null,
                          imageHeroTag:
                              inFlight && withImages ? 'post-image-${post.id}' : null,
                          onOpenImage: (i) => openPhotoViewer(context,
                              urls: post.images, initialIndex: i),
                          menuAction: (action) => switch (action) {
                            'favorite' || 'unfavorite' => _toggleFavorite(post),
                            'delete' => _deletePost(post),
                            _ => reportPostFromSheet(context, ref, post.id),
                          },
                        );
                      },
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// 顶栏:标题「回声」`display` 32 + 右侧发帖 `plus`(热区 48,§6 / §8.4)。
  Widget _header(EmberColors colors) => Padding(
        padding: EdgeInsets.fromLTRB(
          tokens.space20,
          tokens.space16,
          tokens.space20,
          tokens.space12,
        ),
        child: Row(
          children: [
            Expanded(
              child: Text(
                '回声',
                style: AppText.display.copyWith(color: colors.textPrimary),
              ),
            ),
            EmberPressable(
              key: const Key('square.compose.plus'),
              onTap: () => context.push('/posts/compose'),
              pressedScale: 0.97,
              borderRadius: BorderRadius.circular(tokens.radiusPill),
              semanticLabel: '发动态',
              builder: (context, state) => SizedBox(
                width: tokens.sizeTouchApp,
                height: tokens.sizeTouchApp,
                child: Icon(
                  PhosphorIconsRegular.plus,
                  size: tokens.sizeIcon24,
                  color: colors.brandDefault,
                ),
              ),
            ),
          ],
        ),
      );

  /// 空态:动态流空了给「发第一条」;关注流空了引导回推荐(spec §5 + 既有口径)。
  Widget _empty(bool isFollowingTab) => _centered(
        EmberEmpty(
          illustration: const SquareIllustration(SquareIllustrationKind.emptyFeed),
          title: isFollowingTab ? '还没有关注的人' : '还没有人留下回声',
          description: isFollowingTab ? '去「推荐」看看,关注感兴趣的人' : '发一条,让大家认识你',
          actionLabel: isFollowingTab ? '去推荐看看' : '发第一条',
          actionKey: Key(isFollowingTab ? 'square.empty.toRecommend' : 'square.compose'),
          onAction: isFollowingTab
              ? () => _switchTab(SquareTab.recommend)
              : () => context.push('/posts/compose'),
        ),
      );

  /// 空 / 错两态居中(插画 72–96 本身有最大宽,这里只补页边距)。
  Widget _centered(Widget child) => Center(
        child: Padding(
          padding: EdgeInsets.symmetric(
            horizontal: tokens.space20,
            vertical: tokens.space24,
          ),
          child: child,
        ),
      );
}

/// 「推荐 / 关注」两段 tab:文字 + 主色短下划线(选中)。
///
/// 为什么不用 `EmberChip`:chip 是带底色的胶囊,放在大标题下会与「回声」标题抢视觉;
/// 这里保留「心跳」期的 tab 形态(文字 + 短下划线),只把取值换成 Ember token ——
/// page spec §3 的组件表里没有 tab,属于规范未覆盖的场景,按「挑最接近的复用 +
/// 实现时注明」处理:文字档取 `body` 15,选中 `text.primary` + `brand.default` 下划线。
class _SquareTabs extends StatelessWidget {
  const _SquareTabs({required this.value, required this.onChanged});

  final SquareTab value;
  final ValueChanged<SquareTab> onChanged;

  /// tab 行高(与 `size.touch.app` 48 对齐,保证热区达标 §8.4)。
  static const _tabHeight = tokens.sizeTouchApp;

  /// 选中下划线高:规范只给了 `radius.pill` 与主色,没给 tab 指示条尺寸,
  /// 沿用改造前的 3 与 20(见类注释的「规范未覆盖」口径)。
  static const _underlineHeight = 3.0;

  /// 选中下划线宽。
  static const _underlineWidth = 20.0;

  static const _tabs = <(SquareTab, String, String)>[
    (SquareTab.recommend, '推荐', 'square.tab.recommend'),
    (SquareTab.following, '关注', 'square.tab.following'),
  ];

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Row(
      children: [
        for (final (tab, label, keyName) in _tabs)
          Padding(
            padding: EdgeInsets.only(right: tokens.space24),
            child: GestureDetector(
              key: Key(keyName),
              behavior: HitTestBehavior.opaque,
              onTap: () => onChanged(tab),
              child: Semantics(
                selected: value == tab,
                button: true,
                child: SizedBox(
                  height: _tabHeight,
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text(
                        label,
                        style: AppText.body.copyWith(
                          fontWeight: value == tab
                              ? FontWeight.w600
                              : FontWeight.w400,
                          color: value == tab
                              ? colors.textPrimary
                              : colors.textSecondary,
                        ),
                      ),
                      SizedBox(height: tokens.space4),
                      Container(
                        height: _underlineHeight,
                        width: _underlineWidth,
                        decoration: BoxDecoration(
                          color: value == tab
                              ? colors.brandDefault
                              : colors.surfacePage,
                          borderRadius: BorderRadius.circular(tokens.radiusPill),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }
}
