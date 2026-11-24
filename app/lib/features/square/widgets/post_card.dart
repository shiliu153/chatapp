import 'package:flutter/material.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/format.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/theme/ember_colors.dart';
import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';
import '../../../core/widgets/avatar_hero.dart';
import '../../../core/widgets/card_hero.dart';
import '../models.dart';
import 'post_images.dart';
import 'post_reaction_buttons.dart';

/// 动态卡(E-5.5 page spec §1 第 1–6 条 / §3 / §4):
///
/// | 元素 | 取值 |
/// |---|---|
/// | 卡 | [`EmberCard`]:`surface.card` + `radius.lg` + `elev.1` + 内边距 20;深色 `border.divider` 无阴影 |
/// | 作者行 | [`EmberAvatar`] 40 + 昵称 `subtitle` 17/w600 + 时间 `caption` 13 `text.tertiary` |
/// | 正文 | `body` 15 / 行高 1.55 |
/// | 图片 | [`PostImages`]:`radius.sm` 12、间距 4、最多 9 宫格 |
/// | 点赞 / 评论 | Phosphor `heart` / `chat-circle` 20 + `caption` 13 计数 |
///
/// 操作行的三个手势互相独立、命中区不重叠:头像/昵称 → [onTapAuthor];点赞**图标**
/// → [onToggleLike];点赞**数字** → [onTapLikes](0 赞时不响应);··· 菜单 →
/// [menuAction](`favorite` / `unfavorite` 对「自己」和「他人」都给,`delete` /
/// `report` 才是二选一)。
///
/// **Hero 纪律**(SDK `heroes.dart` 硬断言:Hero 的 child 及其后代不得再包含 Hero):
/// 一张卡任意时刻至多一个 Hero。三者按来源互斥,由调用方保证:
/// - [cardHeroTag]:整卡飞进详情(无图动态沿用批次⑤的整卡转场);
/// - [imageHeroTag]:图片飞进详情(§1 第 9 条,E-5.5 新增);
/// - [heroTag]:头像飞进资料页(两个 Hero 都让位时才给)。
class PostCard extends StatelessWidget {
  /// 构造动态卡。
  const PostCard({
    super.key,
    required this.post,
    required this.isMine,
    this.online = false,
    this.onTapAuthor,
    this.onTap,
    this.onToggleLike,
    this.onTapLikes,
    this.onOpenImage,
    this.menuAction,
    this.heroTag,
    this.cardHeroTag,
    this.imageHeroTag,
  });

  /// 动态本身。
  final Post post;

  /// 是否是我发的(决定菜单给「删除」还是「举报」)。
  final bool isMine;

  /// 作者是否在线(头像右下角绿点)。
  final bool online;

  /// 点头像 / 昵称(进资料页);null 表示不可点(自己 / 整卡态)。
  final VoidCallback? onTapAuthor;

  /// 点卡片(进详情);详情页内传 null(不再进详情)。
  final VoidCallback? onTap;

  /// 点赞**图标区**:点赞 / 取消点赞(语义不变,别改成「打开列表」)。
  final VoidCallback? onToggleLike;

  /// 点赞**数字区**:打开点赞列表。
  final VoidCallback? onTapLikes;

  /// 点某张图(打开大图查看器)。
  final void Function(int index)? onOpenImage;

  /// `···` 菜单动作(`favorite` / `unfavorite` / `delete` / `report`)。
  final void Function(String action)? menuAction;

  /// 头像 Hero tag;null 不包。
  final String? heroTag;

  /// 整卡 Hero tag;null 不包。与 [imageHeroTag] / [heroTag] 互斥。
  final String? cardHeroTag;

  /// 图片 Hero tag;null 不包。与 [cardHeroTag] 互斥。
  final String? imageHeroTag;

  /// 卡片读屏标签:作者 + 正文摘要 + 赞数 + 评论数(spec §6 第 3 条)。
  String get _semanticsLabel {
    final summary = post.text.trim();
    final brief = summary.length <= 30 ? summary : '${summary.substring(0, 30)}…';
    return [
      post.author.nickname,
      if (brief.isNotEmpty) brief,
      '${post.likeCount} 赞',
      '${post.commentCount} 评论',
    ].join('，');
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final semantics = _semanticsLabel;

    Widget card = EmberCard(
      key: Key('post.card.${post.id}'),
      onTap: onTap,
      // 可点卡由 EmberCard 自己包（语义容器 + 按压 .98）；静态卡（详情页顶卡）
      // 走下面的手包 Semantics，两处都保证读屏能念出这张卡。
      semanticsLabel: onTap == null ? null : semantics,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _author(context),
          SizedBox(width: tokens.space12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _titleRow(colors),
                SizedBox(height: tokens.space4),
                Text(
                  formatPostTime(post.createdAt),
                  style: AppText.caption.copyWith(color: colors.textTertiary),
                ),
                if (post.text.isNotEmpty) ...[
                  SizedBox(height: tokens.space8),
                  Text(
                    post.text,
                    style: AppText.body.copyWith(color: colors.textPrimary),
                  ),
                ],
                if (post.images.isNotEmpty) ...[
                  SizedBox(height: tokens.space12),
                  PostImages(
                    urls: post.images,
                    onTap: onOpenImage,
                    heroTag: imageHeroTag,
                  ),
                ],
                SizedBox(height: tokens.space4),
                _actionRow(),
              ],
            ),
          ),
        ],
      ),
    );

    if (onTap == null) {
      // 静态卡：EmberCard 不包 EmberPressable，语义容器在这里补
      // （读屏仍要念「作者，正文摘要，N 赞，M 评论」）。
      card = Semantics(container: true, label: semantics, child: card);
    }

    // 整卡 Hero（无图动态）：与图片 Hero 互斥，调用方只给其中一个。
    return CardHero(tag: cardHeroTag, child: card);
  }

  /// 头像(+ 在线点 + 资料页 Hero)。
  Widget _author(BuildContext context) => AvatarHero(
        tag: heroTag,
        imageUrl: post.author.avatarUrl,
        fromRadius: tokens.radiusPill,
        child: GestureDetector(
          key: Key('post.avatar.${post.id}'),
          behavior: HitTestBehavior.opaque,
          // null(自己/整卡态)= 空回调吞掉点击,不落到卡片的「进详情」
          onTap: onTapAuthor ?? () {},
          child: EmberAvatar(
            image: (post.author.avatarUrl == null || post.author.avatarUrl!.isEmpty)
                ? null
                : NetworkImage(post.author.avatarUrl!),
            name: post.author.nickname,
            size: EmberComponentSizes.avatarMd,
            online: online,
          ),
        ),
      );

  /// 昵称 + `···` 菜单。
  Widget _titleRow(EmberColors colors) => Row(
        children: [
          Expanded(
            child: Align(
              alignment: Alignment.centerLeft,
              child: GestureDetector(
                key: Key('post.nickname.${post.id}'),
                behavior: HitTestBehavior.opaque,
                onTap: onTapAuthor ?? () {},
                child: Text(
                  post.author.nickname,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppText.subtitle.copyWith(color: colors.textPrimary),
                ),
              ),
            ),
          ),
          if (menuAction != null) _MoreMenu(post: post, isMine: isMine, onAction: menuAction!),
        ],
      );

  /// 操作行:点赞图标 / 赞数(点赞列表入口)/ 评论。
  Widget _actionRow() => Row(
        children: [
          PostLikeButton(
            iconKey: Key('post.like.${post.id}'),
            liked: post.likedByMe,
            onTap: onToggleLike,
          ),
          PostLikeCount(
            countKey: Key('post.likeCount.${post.id}'),
            count: post.likeCount,
            liked: post.likedByMe,
            onTap: onTapLikes,
          ),
          SizedBox(width: tokens.space16),
          PostCommentButton(
            iconKey: Key('post.comment.${post.id}'),
            count: post.commentCount,
            onTap: onTap,
          ),
        ],
      );
}

/// `···` 菜单:收藏(对所有人都给,它是私密书签)+ 删除 / 举报(按归属二选一)。
class _MoreMenu extends StatelessWidget {
  const _MoreMenu({required this.post, required this.isMine, required this.onAction});

  final Post post;
  final bool isMine;
  final void Function(String action) onAction;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return SizedBox(
      width: tokens.sizeTouchApp,
      height: tokens.sizeTouchApp,
      child: PopupMenuButton<String>(
        key: Key('post.more.${post.id}'),
        padding: EdgeInsets.zero,
        tooltip: '更多',
        icon: Icon(
          PhosphorIconsRegular.dotsThree,
          size: tokens.sizeIcon20,
          color: colors.textTertiary,
        ),
        onSelected: onAction,
        itemBuilder: (context) => [
          PopupMenuItem(
            key: const Key('post.menu.favorite'),
            value: post.isFavorited ? 'unfavorite' : 'favorite',
            child: Row(
              children: [
                Icon(
                  post.isFavorited
                      ? PhosphorIconsFill.bookmarkSimple
                      : PhosphorIconsRegular.bookmarkSimple,
                  size: tokens.sizeIcon20,
                  color: post.isFavorited ? colors.brandDefault : colors.textTertiary,
                ),
                SizedBox(width: tokens.space8),
                Text(post.isFavorited ? '取消收藏' : '收藏'),
              ],
            ),
          ),
          if (isMine)
            const PopupMenuItem(
              key: Key('post.menu.delete'),
              value: 'delete',
              child: Text('删除'),
            )
          else
            const PopupMenuItem(
              key: Key('post.menu.report'),
              value: 'report',
              child: Text('举报'),
            ),
        ],
      ),
    );
  }
}
