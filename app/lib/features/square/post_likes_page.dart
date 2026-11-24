import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import 'models.dart';
import 'post_likes_controller.dart';
import 'widgets/square_illustration.dart';

/// 点赞列表(`/posts/:id/likes`):谁点了赞 —— 头像 + 昵称 + 相对时间,点行进资料页。
///
/// 入口是动态卡上**点赞数字**那一块(图标区仍是点赞/取消),见 `widgets/post_card.dart`。
///
/// E-5.6d 只换皮(page spec §1 D 组):顶栏换 [`EmberPageScaffold`](§9.4)、
/// 行换 [`EmberPressable`] + [`EmberAvatar`](行高 68 / 17-w600 / 13)、
/// 空 / 错态换 [`EmberEmpty`] + unDraw、骨架换 [`EmberSkeleton`];
/// `postLikesProvider` 与分页逻辑一行没动。
class PostLikesPage extends ConsumerStatefulWidget {
  /// 构造点赞列表页。
  const PostLikesPage({super.key, required this.postId});

  /// 被点赞的动态 id。
  final int postId;

  @override
  ConsumerState<PostLikesPage> createState() => _PostLikesPageState();
}

class _PostLikesPageState extends ConsumerState<PostLikesPage> {
  final _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.extentAfter < 300) {
        ref.read(postLikesProvider(widget.postId).notifier).loadMore();
      }
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final likes = ref.watch(postLikesProvider(widget.postId));
    return EmberPageScaffold(
      title: '点赞',
      backKey: const Key('postLikes.back'),
      // 列表行整行铺满(分隔线横贯),横向 20 由行自己给(§5.2 / §9.4)。
      contentPadding: EdgeInsets.zero,
      body: likes.when(
        loading: () => const _PostLikesSkeleton(),
        error: (error, _) => _Centered(
          child: EmberEmpty(
            illustration:
                const SquareIllustration(SquareIllustrationKind.loadFailed),
            title: '加载失败',
            description:
                error is ApiException ? error.message : '加载失败,请重试',
            actionLabel: '重试',
            actionKey: const Key('postLikes.retry'),
            onAction: () => ref.invalidate(postLikesProvider(widget.postId)),
          ),
        ),
        data: (items) => items.isEmpty
            ? _Centered(
                child: EmberEmpty(
                  key: const Key('postLikes.empty'),
                  // 插画取回声线共用的 unDraw `Online posts`(最近的一张):
                  // 点赞列表是「人」的列表,`assets/illustrations/` 里没有专门的
                  // 人像空态图,按「挑最接近的复用 + 实现时注明」处理(CLAUDE.md
                  // 的规范未覆盖场景口径)。
                  illustration: const SquareIllustration(
                    SquareIllustrationKind.emptyFeed,
                  ),
                  title: '还没有人点赞',
                  description: '第一个喜欢的人,往往就差一个赞',
                ),
              )
            : ListView.builder(
                key: const Key('postLikes.list'),
                controller: _scroll,
                padding: EdgeInsets.only(bottom: tokens.space24),
                itemCount: items.length,
                itemBuilder: (context, index) {
                  final user = items[index];
                  return _LikerRow(
                    user: user,
                    onTap: () => context.push('/users/${user.userId}'),
                  );
                },
              ),
      ),
    );
  }
}

/// 一行点赞者:头像 40 + 昵称 17/w600 + 点赞时间 13 `text.secondary`。
///
/// 为什么不用 [`EmberSettingsTile`]:那一行的左侧槽只收 `IconData`,这里要头像
/// (page spec §3「列表项(通知 / 收藏 / 点赞)」的两条路里,带缩略图的走自绘行);
/// 行高 / 字号 / 分隔线取值与它对齐(68 / 17-w600 / 13,§5.2)。
///
/// 读屏(page spec §6 第 3 条):整行播报「昵称,时间」,内部文字 `ExcludeSemantics`。
class _LikerRow extends StatelessWidget {
  const _LikerRow({required this.user, required this.onTap});

  final PostLikeUser user;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final time = formatPostTime(user.likedAt);
    return Semantics(
      container: true,
      button: true,
      label: '${user.nickname}，$time',
      onTap: onTap,
      child: ExcludeSemantics(
        child: EmberPressable(
          key: Key('postLikes.row.${user.userId}'),
          onTap: onTap,
          pressedScale: 0.97,
          builder: (context, state) => ColoredBox(
            color: state.pressed ? colors.surfaceSunken : Colors.transparent,
            child: ConstrainedBox(
              // 行高下沿 68(spec §5.2「列表行高 68–76」)。
              constraints: const BoxConstraints(minHeight: _minRowHeight),
              child: DecoratedBox(
                decoration: BoxDecoration(
                  border: Border(
                    bottom: BorderSide(color: colors.borderDivider, width: 1),
                  ),
                ),
                child: Padding(
                  padding: EdgeInsets.symmetric(
                    horizontal: tokens.space20,
                    vertical: tokens.space12,
                  ),
                  child: Row(
                    children: [
                      EmberAvatar(
                        image: (user.avatarUrl == null || user.avatarUrl!.isEmpty)
                            ? null
                            : NetworkImage(user.avatarUrl!),
                        size: EmberComponentSizes.avatarMd,
                        name: user.nickname,
                      ),
                      SizedBox(width: tokens.space12),
                      Expanded(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              user.nickname,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                fontSize: tokens.fontSizeSubtitle,
                                fontWeight: FontWeight.w600,
                                height: tokens.fontLineHeightSubtitle,
                                color: colors.textPrimary,
                              ),
                            ),
                            SizedBox(height: tokens.space4),
                            Text(
                              time,
                              style: TextStyle(
                                fontSize: tokens.fontSizeCaption,
                                height: tokens.fontLineHeightCaption,
                                color: colors.textSecondary,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  /// 行高下沿 68(与 `EmberSettingsTile` 同一口径)。
  static const double _minRowHeight = 68;
}

/// 骨架:6 行「圆头像 + 两行文字」(`surface.sunken` 呼吸,§8.3)。
class _PostLikesSkeleton extends StatelessWidget {
  const _PostLikesSkeleton();

  @override
  Widget build(BuildContext context) {
    return ListView(
      key: const Key('postLikes.skeleton'),
      padding: EdgeInsets.symmetric(vertical: tokens.space12),
      children: [
        for (var i = 0; i < 6; i++)
          Padding(
            padding: EdgeInsets.symmetric(
              horizontal: tokens.space20,
              vertical: tokens.space12,
            ),
            child: Row(
              children: [
                const EmberSkeleton(
                  width: EmberComponentSizes.avatarMd,
                  height: EmberComponentSizes.avatarMd,
                  shape: BoxShape.circle,
                ),
                SizedBox(width: tokens.space12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      EmberSkeleton(
                        width: 120,
                        height: tokens.fontSizeSubtitle,
                      ),
                      SizedBox(height: tokens.space8),
                      EmberSkeleton(
                        width: 72,
                        height: tokens.fontSizeCaption,
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

/// 空 / 错两态居中且可滚动(小屏 + 大字号下不溢出)。
class _Centered extends StatelessWidget {
  const _Centered({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: constraints.maxHeight),
          child: Center(
            child: Padding(
              padding: EdgeInsets.all(tokens.space24),
              child: child,
            ),
          ),
        ),
      ),
    );
  }
}
