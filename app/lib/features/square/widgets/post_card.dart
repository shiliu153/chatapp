import 'package:flutter/material.dart';

import '../../../core/format.dart';
import '../../presence/online_dot.dart';
import '../models.dart';
import 'post_images.dart';

/// 动态卡片:头像/昵称/相对时间/正文/九宫格/点赞评论行;右上 ··· 菜单。
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
  });

  final Post post;

  /// 是否自己的动态(决定 ··· 菜单是「删除」还是「举报」)。
  final bool isMine;

  /// 作者是否在线 → 头像右下角绿点。
  final bool online;

  /// 点作者头像/昵称;null(自己/不关心)= 空回调吞掉点击。
  final VoidCallback? onTapAuthor;
  final VoidCallback? onTap;
  final VoidCallback? onToggleLike;
  final void Function(int index)? onOpenImage;

  /// 菜单动作:'delete' | 'report';为 null 时不显示 ··· 菜单。
  final void Function(String action)? menuAction;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: Colors.white,
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 6),
      child: InkWell(
        key: Key('post.card.${post.id}'),
        onTap: onTap,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            GestureDetector(
              key: Key('post.avatar.${post.id}'),
              behavior: HitTestBehavior.opaque,
              // null(自己)= 空回调吞掉点击,不落到卡片的「进详情」
              onTap: onTapAuthor ?? () {},
              child: _Avatar(
                  url: post.author.avatarUrl, name: post.author.nickname, online: online),
            ),
            const SizedBox(width: 10),
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
                                style: const TextStyle(
                                    fontWeight: FontWeight.w600, fontSize: 15)),
                          ),
                        ),
                      ),
                      if (menuAction != null)
                        SizedBox(
                          width: 28,
                          height: 20,
                          child: PopupMenuButton<String>(
                            key: Key('post.more.${post.id}'),
                            padding: EdgeInsets.zero,
                            iconSize: 18,
                            icon: const Icon(Icons.more_horiz, color: Color(0xFF999999)),
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
                      style: const TextStyle(fontSize: 12, color: Color(0xFF999999))),
                  if (post.text.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(post.text, style: const TextStyle(fontSize: 15, height: 1.4)),
                  ],
                  if (post.images.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    PostImages(urls: post.images, onTap: onOpenImage),
                  ],
                  const SizedBox(height: 2),
                  Row(
                    children: [
                      _ActionIcon(
                        iconKey: Key('post.like.${post.id}'),
                        icon: post.likedByMe ? Icons.favorite : Icons.favorite_border,
                        color: post.likedByMe
                            ? const Color(0xFFFF2C55)
                            : const Color(0xFF999999),
                        count: post.likeCount,
                        onTap: onToggleLike,
                      ),
                      const SizedBox(width: 24),
                      _ActionIcon(
                        icon: Icons.mode_comment_outlined,
                        color: const Color(0xFF999999),
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
      ),
    );
  }
}

class _ActionIcon extends StatelessWidget {
  const _ActionIcon({
    this.iconKey,
    required this.icon,
    required this.color,
    required this.count,
    this.onTap,
  });

  final Key? iconKey;
  final IconData icon;
  final Color color;
  final int count;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => InkWell(
        key: iconKey,
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 2),
          child: Row(
            children: [
              Icon(icon, size: 18, color: color),
              const SizedBox(width: 4),
              Text('$count', style: TextStyle(fontSize: 13, color: color)),
            ],
          ),
        ),
      );
}

class _Avatar extends StatelessWidget {
  const _Avatar({this.url, required this.name, this.online = false});

  final String? url;
  final String name;
  final bool online;

  @override
  Widget build(BuildContext context) {
    final placeholder = Center(
      child: Text(name.isEmpty ? '?' : name.substring(0, 1),
          style: const TextStyle(color: Colors.white)),
    );
    final avatar = Container(
      width: 40,
      height: 40,
      decoration: BoxDecoration(
        color: const Color(0xFFC9CDD4),
        borderRadius: BorderRadius.circular(6),
      ),
      clipBehavior: Clip.antiAlias,
      child: url == null || url!.isEmpty
          ? placeholder
          : Image.network(url!, fit: BoxFit.cover,
              errorBuilder: (c, e, s) => placeholder),
    );
    if (!online) return avatar;
    return Stack(
      clipBehavior: Clip.none,
      children: [
        avatar,
        const Positioned(right: 0, bottom: 0, child: OnlineDot(size: 11)),
      ],
    );
  }
}
