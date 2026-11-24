import 'package:flutter/material.dart';
import 'package:flutter/physics.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/theme/app_typography.dart';
import '../../../core/theme/ember_motion.dart';
import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';

/// 点赞 / 评论钮(E-5.5 page spec §3「点赞 / 评论钮」+ §4 状态清单)。
///
/// 三条硬口径:
/// 1. **已赞 = Phosphor `heart` 的 Fill 字重 + `brand.default`;未赞 = Regular +
///    `text.tertiary`**(§6「未选中 Regular + `text.tertiary`,选中 Fill + `brand.default`」)。
///    颜色不是唯一线索 —— 字重同时变,读屏标签同时变(§8.4)。
/// 2. **心形弹跳保留**(§7 拍板 #2):`spring.fast` 弹簧驱动的 1 → 1.25 → 1,
///    只在「未赞 → 已赞」翻带时触发;减弱动态效果下**只换色不缩放**(§8.4)。
/// 3. 热区 ≥48×48(§8.4「图标本体可以小,热区不能缩」)。

/// 点赞钮(图标区):点赞 / 取消点赞。
///
/// 与 [_LikeCount] 是 Row 里的**兄弟节点**:图标区管点赞(语义「赞,已赞 / 未赞」),
/// 数字区管打开点赞列表(语义「N 赞,查看点赞列表」)。两块矩形天然不重叠,
/// 不会出现「点哪都点赞」或「点哪都开列表」。
class PostLikeButton extends StatefulWidget {
  /// 构造点赞钮。
  const PostLikeButton({
    super.key,
    required this.liked,
    this.onTap,
    this.iconKey,
  });

  /// 当前是否已赞(决定字重 + 颜色 + 读屏标签)。
  final bool liked;

  /// 点击回调(点赞 / 取消)。
  final VoidCallback? onTap;

  /// 图标本的 Key(页面测试定点点击用)。
  final Key? iconKey;

  @override
  State<PostLikeButton> createState() => _PostLikeButtonState();
}

class _PostLikeButtonState extends State<PostLikeButton>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 420));

  /// 心形弹跳:1 → 1.25 → 1(§7 拍板 #2 的「保留心形弹跳」)。
  late final Animation<double> _scale = TweenSequence<double>([
    TweenSequenceItem(tween: Tween(begin: 1.0, end: 1.25), weight: 0.5),
    TweenSequenceItem(tween: Tween(begin: 1.25, end: 1.0), weight: 0.5),
  ]).animate(_controller);

  @override
  void didUpdateWidget(covariant PostLikeButton oldWidget) {
    super.didUpdateWidget(oldWidget);
    // 只在「未赞 → 已赞」翻带时弹;取消赞不弹(§4「pressed: scale .97 + 心形弹跳」)。
    if (!widget.liked || oldWidget.liked) return;
    // 减弱动态效果:只换色不缩放(§4 reduced motion 行 / §8.4)。
    if (EmberMotion.reducedOf(context)) return;
    _controller.animateWith(
      SpringSimulation(EmberMotion.fast, 0, 1, 0),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return EmberPressable(
      key: widget.iconKey,
      onTap: widget.onTap,
      pressedScale: 0.97,
      borderRadius: BorderRadius.circular(tokens.radiusPill),
      semanticLabel: widget.liked ? '赞，已赞' : '赞，未赞',
      builder: (context, state) => SizedBox(
        width: tokens.sizeTouchApp,
        height: tokens.sizeTouchApp,
        child: Center(
          child: ScaleTransition(
            scale: _scale,
            child: Icon(
              widget.liked
                  ? PhosphorIconsFill.heart
                  : PhosphorIconsRegular.heart,
              size: tokens.sizeIcon20,
              color: widget.liked ? colors.brandDefault : colors.textTertiary,
            ),
          ),
        ),
      ),
    );
  }
}

/// 点赞计数(点赞列表入口):与 [PostLikeButton] 并列,不套在同一个手势里。
///
/// 0 赞时**不响应**(不弹空列表):`onTap` 传 null 即不可点,也维持「不冒到卡片」
/// 的既有行为 —— [EmberPressable] 的 `onTap` 为 null 时不会吞事件,所以这里用空
/// 回调吞掉点击,避免落到外层可点卡片上进详情。
class PostLikeCount extends StatelessWidget {
  /// 构造计数。
  const PostLikeCount({
    super.key,
    required this.count,
    required this.liked,
    this.onTap,
    this.countKey,
  });

  /// 赞数。
  final int count;

  /// 是否已赞(数字跟着变成 `brand.default`,与图标同色)。
  final bool liked;

  /// 打开点赞列表;null 或 0 赞时不响应。
  final VoidCallback? onTap;

  /// 数字本的 Key。
  final Key? countKey;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final active = count > 0 && onTap != null;
    return EmberPressable(
      key: countKey,
      onTap: active ? onTap : () {},
      pressedScale: 1,
      borderRadius: BorderRadius.circular(tokens.radiusPill),
      // 数字区读「N 赞,查看点赞列表」—— 0 赞时不说「查看列表」(那里是空的)。
      semanticLabel: active ? '$count 赞，查看点赞列表' : '$count 赞',
      builder: (context, state) => ConstrainedBox(
        constraints: const BoxConstraints(
          minWidth: tokens.sizeTouchApp,
          minHeight: tokens.sizeTouchApp,
        ),
        child: Center(
          child: Text(
            '$count',
            style: AppText.caption.copyWith(
              color: liked ? colors.brandDefault : colors.textTertiary,
            ),
          ),
        ),
      ),
    );
  }
}

/// 评论钮:Phosphor `chat-circle` Regular + `text.tertiary` + 计数;点进详情并聚焦输入
/// (spec §4「评论钮 default:…点进详情并聚焦输入」)。
class PostCommentButton extends StatelessWidget {
  /// 构造评论钮。
  const PostCommentButton({super.key, required this.count, this.onTap, this.iconKey});

  /// 评论数。
  final int count;

  /// 点击回调(进详情)。
  final VoidCallback? onTap;

  /// 图标本的 Key。
  final Key? iconKey;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return EmberPressable(
      key: iconKey,
      onTap: onTap,
      pressedScale: 0.97,
      borderRadius: BorderRadius.circular(tokens.radiusPill),
      semanticLabel: '评论，$count 条',
      builder: (context, state) => SizedBox(
        height: tokens.sizeTouchApp,
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              PhosphorIconsRegular.chatCircle,
              size: tokens.sizeIcon20,
              color: colors.textTertiary,
            ),
            SizedBox(width: tokens.space4),
            Text(
              '$count',
              style: AppText.caption.copyWith(color: colors.textTertiary),
            ),
          ],
        ),
      ),
    );
  }
}
