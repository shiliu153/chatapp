import 'package:flutter/material.dart';

/// 动态配图的 Hero 转场包装(E-5.5 page spec §1 第 9 条 / §9.3「沉浸内容 → 全屏 +
/// Hero 转场」)。
///
/// 为什么不用 `core/widgets/card_hero.dart` 那份:那个把**整张卡**送进详情页,
/// 本条要求的是「动态卡图片 → 详情页图片」。两者不能叠(SDK 硬断言禁止 Hero 嵌套),
/// 所以广场点卡时按「有没有图」二选一:有图走图片 Hero,没图仍走整卡 Hero。
///
/// [tag] 为 null(无来源 / 深链 / 我的动态)或系统开启「减弱动态效果」时**不包**
/// Hero,静默降级为普通渲染 —— 此时转场由路由自己退化成淡入(见 `router.dart` 的
/// [subPageRoute]),即 §8.4 的「Hero 退化为淡入」。
class PostImageHero extends StatelessWidget {
  /// 构造 Hero 包装。
  const PostImageHero({super.key, required this.tag, required this.child});

  /// Hero tag(`post-image-{postId}`);null 时直接渲染 [child]。
  final String? tag;

  /// 被包住的图片块。
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final heroTag = tag;
    if (heroTag == null || MediaQuery.disableAnimationsOf(context)) return child;
    return Hero(tag: heroTag, child: child);
  }
}
