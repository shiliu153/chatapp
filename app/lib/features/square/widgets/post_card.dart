import 'package:flutter/material.dart';

import '../../../core/format.dart';
import '../../../core/theme/app_colors.dart';
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
  final VoidCallback? onToggleLike;
  final void Function(int index)? onOpenImage;
  final void Function(String action)? menuAction;

  /// 头像 Hero tag(附录 C.7);null(我的动态/整卡态)不包。
  final String? heroTag;

  /// 整卡 Hero tag(附录 D);null(普通态)不包。与 [heroTag] 互斥。
  final String? cardHeroTag;

  @override
  Widget build(BuildContext context) {
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
                                  .copyWith(color: AppColors.text1)),
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
                          icon: const Icon(Icons.more_horiz_rounded,
                              size: 20, color: AppColors.text3),
                          onSelected: (value) => menuAction!(value),
                          itemBuilder: (context) => [
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
                    style: AppText.micro.copyWith(color: AppColors.text3)),
                if (post.text.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Text(post.text,
                      style: AppText.body.copyWith(color: AppColors.text1)),
                ],
                if (post.images.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  PostImages(urls: post.images, onTap: onOpenImage),
                ],
                const SizedBox(height: 2),
                Row(
                  children: [
                    _PulseIcon(
                      iconKey: Key('post.like.${post.id}'),
                      icon: post.likedByMe
                          ? Icons.favorite_rounded
                          : Icons.favorite_border_rounded,
                      color: post.likedByMe ? AppColors.brand : AppColors.text3,
                      count: post.likeCount,
                      pulse: post.likedByMe, // didUpdateWidget 里只在「未赞→已赞」触发
                      onTap: onToggleLike,
                    ),
                    const SizedBox(width: 16),
                    _ActionIcon(
                      icon: Icons.mode_comment_rounded,
                      color: AppColors.text3,
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
class _PulseIcon extends StatefulWidget {
  const _PulseIcon({
    this.iconKey,
    required this.icon,
    required this.color,
    required this.count,
    required this.pulse,
    this.onTap,
  });

  final Key? iconKey;
  final IconData icon;
  final Color color;
  final int count;

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
          child: Row(
            children: [
              ScaleTransition(
                scale: _scale,
                child: Icon(widget.icon, size: 20, color: widget.color),
              ),
              const SizedBox(width: 4),
              Text('${widget.count}',
                  style: AppText.caption.copyWith(color: widget.color)),
            ],
          ),
        ),
      );
}
