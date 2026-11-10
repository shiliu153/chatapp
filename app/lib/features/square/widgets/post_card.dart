import 'package:flutter/material.dart';

import '../../../core/format.dart';
import '../../../core/theme/heart_theme_context.dart';
import '../../../core/theme/app_motion.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/app_avatar.dart';
import '../../../core/widgets/app_card.dart';
import '../../../core/widgets/avatar_hero.dart';
import '../../../core/widgets/card_hero.dart';
import '../models.dart';
import 'post_images.dart';

/// 动态卡(附录 D):AppCard 白卡 R20;圆形头像(在线呼吸点)+ 昵称/时间/正文
/// + 九宫格 + 操作行(点赞带心跳脉冲);右上 ··· 菜单。
///
/// 操作行的三个手势互相独立、命中区不重叠:
/// 头像/昵称 → [onTapAuthor];点赞**图标** → [onToggleLike];点赞**数字** →
/// [onTapLikes](0 赞时不响应);··· 菜单 → [menuAction](`favorite` / `unfavorite`
/// 对「自己」和「他人」的动态都给,`delete` / `report` 才是二选一)。
///
/// Hero 互斥(spec §5):[heroTag](头像)与 [cardHeroTag](整卡)至多传一个,
/// 同传在 debug 下触发 SDK 嵌套断言崩溃。
class PostCard extends StatelessWidget {
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
  });

  final Post post;
  final bool isMine;
  final bool online;
  final VoidCallback? onTapAuthor;
  final VoidCallback? onTap;

  /// 点赞**图标区**:点赞 / 取消点赞(语义不变,别改成「打开列表」)。
  final VoidCallback? onToggleLike;

  /// 点赞**数字区**:打开点赞列表。两区命中范围互不重叠(见 [_LikeTail])。
  final VoidCallback? onTapLikes;
  final void Function(int index)? onOpenImage;
  final void Function(String action)? menuAction;

  /// 头像 Hero tag(附录 C.7);null(我的动态/整卡态)不包。
  final String? heroTag;

  /// 整卡 Hero tag(附录 D);null(普通态)不包。与 [heroTag] 互斥。
  final String? cardHeroTag;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    final card = AppCard(
      key: Key('post.card.${post.id}'),
      onTap: onTap,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          AvatarHero(
            tag: heroTag,
            imageUrl: post.author.avatarUrl,
            fromRadius: AppRadius.full,
            child: GestureDetector(
              key: Key('post.avatar.${post.id}'),
              behavior: HitTestBehavior.opaque,
              // null(自己/整卡态)= 空回调吞掉点击,不落到卡片的「进详情」
              onTap: onTapAuthor ?? () {},
              child: AppAvatar(
                imageUrl: post.author.avatarUrl,
                size: 40,
                showOnlineDot: online,
                fallbackText: post.author.nickname,
              ),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Align(
                        alignment: Alignment.centerLeft,
                        child: GestureDetector(
                          key: Key('post.nickname.${post.id}'),
                          behavior: HitTestBehavior.opaque,
                          onTap: onTapAuthor ?? () {},
                          child: Text(post.author.nickname,
                              style: AppText.subtitle
                                  .copyWith(color: colors.text1)),
                        ),
                      ),
                    ),
                    if (menuAction != null)
                      SizedBox(
                        width: 32,
                        height: 32,
                        child: PopupMenuButton<String>(
                          key: Key('post.more.${post.id}'),
                          padding: EdgeInsets.zero,
                          icon: Icon(Icons.more_horiz_rounded,
                              size: 20, color: colors.text3),
                          onSelected: (value) => menuAction!(value),
                          itemBuilder: (context) => [
                            // 收藏对「自己」和「他人」的动态都给:它是私密书签,
                            // 所以不能塞进下面那个 isMine 二选一里。
                            PopupMenuItem(
                              key: const Key('post.menu.favorite'),
                              value:
                                  post.isFavorited ? 'unfavorite' : 'favorite',
                              child: Row(
                                children: [
                                  Icon(
                                    post.isFavorited
                                        ? Icons.bookmark_rounded
                                        : Icons.bookmark_border_rounded,
                                    size: 20,
                                    color: post.isFavorited
                                        ? colors.brand
                                        : colors.text3,
                                  ),
                                  const SizedBox(width: 8),
                                  Text(post.isFavorited ? '取消收藏' : '收藏'),
                                ],
                              ),
                            ),
                            if (isMine)
                              const PopupMenuItem(
                                  key: Key('post.menu.delete'),
                                  value: 'delete',
                                  child: Text('删除'))
                            else
                              const PopupMenuItem(
                                  key: Key('post.menu.report'),
                                  value: 'report',
                                  child: Text('举报')),
                          ],
                        ),
                      ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(formatPostTime(post.createdAt),
                    style: AppText.micro.copyWith(color: colors.text3)),
                if (post.text.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Text(post.text,
                      style: AppText.body.copyWith(color: colors.text1)),
                ],
                if (post.images.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  PostImages(urls: post.images, onTap: onOpenImage),
                ],
                const SizedBox(height: 2),
                Row(
                  children: [
                    // 点赞位拆成两个**互不重叠**的命中区(见 [_LikeTail]):
                    // 图标 = 点赞/取消(行为不变),数字 = 打开点赞列表。
                    _PulseIcon(
                      iconKey: Key('post.like.${post.id}'),
                      icon: post.likedByMe
                          ? Icons.favorite_rounded
                          : Icons.favorite_border_rounded,
                      color: post.likedByMe ? colors.brand : colors.text3,
                      pulse: post.likedByMe, // didUpdateWidget 里只在「未赞→已赞」触发
                      onTap: onToggleLike,
                    ),
                    _LikeTail(
                      countKey: Key('post.likeCount.${post.id}'),
                      count: post.likeCount,
                      color: post.likedByMe ? colors.brand : colors.text3,
                      // 0 赞时**不响应**:不弹空列表。空回调是为了吞掉这次点击,
                      // 否则它会冒到卡片的 onTap 变成「进详情」(与头像同一个套路)。
                      onTap: post.likeCount > 0 ? onTapLikes : () {},
                    ),
                    const SizedBox(width: 16),
                    _ActionIcon(
                      icon: Icons.mode_comment_rounded,
                      color: colors.text3,
                      count: post.commentCount,
                      onTap: onTap,
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
    return CardHero(tag: cardHeroTag, child: card);
  }
}

/// 操作行图标 + 计数(评论位;无脉冲需求)。
class _ActionIcon extends StatelessWidget {
  const _ActionIcon({
    required this.icon,
    required this.color,
    required this.count,
    this.onTap,
  });

  final IconData icon;
  final Color color;
  final int count;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 2),
          child: Row(
            children: [
              Icon(icon, size: 20, color: color),
              const SizedBox(width: 4),
              Text('$count', style: AppText.caption.copyWith(color: color)),
            ],
          ),
        ),
      );
}

/// 点赞心跳脉冲(§6.2 微交互):状态从未赞翻到已赞时 1→1.25→1(base)。
///
/// **只包图标**,不包数字:数字是另一个命中区([_LikeTail]),两个 `InkWell`
/// 是 Row 里的兄弟节点,矩形天然不重叠;若像改造前那样把「图标 + 数字」包成
/// 一个 `InkWell`,再叠一个数字手势就会变成「点哪都点赞」或「点哪都开列表」。
class _PulseIcon extends StatefulWidget {
  const _PulseIcon({
    this.iconKey,
    required this.icon,
    required this.color,
    required this.pulse,
    this.onTap,
  });

  final Key? iconKey;
  final IconData icon;
  final Color color;

  /// 当前是否已赞;didUpdateWidget 检测 false→true 翻转触发脉冲。
  final bool pulse;
  final VoidCallback? onTap;

  @override
  State<_PulseIcon> createState() => _PulseIconState();
}

class _PulseIconState extends State<_PulseIcon>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: AppMotion.base);
  late final Animation<double> _scale = TweenSequence([
    TweenSequenceItem(tween: Tween(begin: 1.0, end: 1.25), weight: 0.5),
    TweenSequenceItem(tween: Tween(begin: 1.25, end: 1.0), weight: 0.5),
  ]).animate(CurvedAnimation(parent: _c, curve: AppMotion.easeOut));

  @override
  void didUpdateWidget(covariant _PulseIcon oldWidget) {
    super.didUpdateWidget(oldWidget);
    // 只在「未赞 → 已赞」翻带动效;取消赞不弹
    if (widget.pulse && !oldWidget.pulse) {
      if (MediaQuery.disableAnimationsOf(context)) return;
      _c.forward(from: 0);
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => InkWell(
        key: widget.iconKey,
        onTap: widget.onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 2),
          child: ScaleTransition(
            scale: _scale,
            child: Icon(widget.icon, size: 20, color: widget.color),
          ),
        ),
      );
}

/// 点赞计数(点赞列表入口):与图标区**并列**,不套在同一个手势里。
///
/// 两个区是 Row 里的兄弟节点,矩形天然不重叠;`opaque` 让整块(含内边距)
/// 都能接到指针。`onTap` 传空回调 = 吞掉点击(不响应),但不冒到卡片上。
class _LikeTail extends StatelessWidget {
  const _LikeTail({
    this.countKey,
    required this.count,
    required this.color,
    this.onTap,
  });

  final Key? countKey;
  final int count;
  final Color color;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => GestureDetector(
        key: countKey,
        behavior: HitTestBehavior.opaque,
        onTap: onTap,
        child: Padding(
          // 左侧留 4px 与图标区分开:两块命中矩形相邻但不重叠
          padding: const EdgeInsets.fromLTRB(4, 6, 2, 6),
          child: Text('$count', style: AppText.caption.copyWith(color: color)),
        ),
      );
}
