import 'package:flutter/material.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;
import 'post_image_hero.dart';

/// 动态配图(E-5.5 page spec §1 第 4 条 / §3「图片网格」):
/// `radius.sm`(12)、间距 4、最多 9 宫格(沿用既有网格规则:1 张通栏、其余 3 列);
/// 图挂了 → `surface.sunken` 底 + Phosphor `image` 图标(**不是**灰色 Material 图标)。
///
/// 单图高度取附录 D 的 240:规范只写「单图按比例」,而客户端在解码前拿不到原图比例
/// (契约里 `images` 只有 URL),按 240 通栏是当前唯一稳定的口径 —— 差异记在 PR 遗留,
/// 等后端补 `width`/`height` 再改真按比例。
class PostImages extends StatelessWidget {
  /// 构造图片块。
  const PostImages({super.key, required this.urls, this.onTap, this.heroTag});

  /// 图片地址(最多取前 9 张)。
  final List<String> urls;

  /// 点某一张的回调(打开大图查看器)。
  final void Function(int index)? onTap;

  /// 图片块的 Hero tag;null 不包 Hero(见 [PostImageHero])。
  final String? heroTag;

  /// 单图通栏的固定高(附录 D;屏宽自适应宽度)。
  static const singleHeight = 240.0;

  /// 9 宫格上限(§3「最多 9 宫格」)。
  static const maxCount = 9;

  @override
  Widget build(BuildContext context) {
    final visible = urls.take(maxCount).toList();
    if (visible.isEmpty) return const SizedBox.shrink();
    return PostImageHero(
      tag: heroTag,
      child: visible.length == 1
          ? _single(context, visible)
          : _grid(context, visible),
    );
  }

  /// 单图:通栏 + 固定高。
  Widget _single(BuildContext context, List<String> visible) => GestureDetector(
        key: const Key('post.image.0'),
        onTap: () => onTap?.call(0),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(tokens.radiusSm),
          child: SizedBox(
            width: double.infinity,
            height: singleHeight,
            child: _image(context, 0, visible),
          ),
        ),
      );

  /// 多图:3 列正方格(间距 4,§3)。
  Widget _grid(BuildContext context, List<String> visible) => GridView.count(
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        crossAxisCount: 3,
        mainAxisSpacing: tokens.space4,
        crossAxisSpacing: tokens.space4,
        children: [
          for (var i = 0; i < visible.length; i++)
            GestureDetector(
              key: Key('post.image.$i'),
              onTap: () => onTap?.call(i),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(tokens.radiusSm),
                child: _image(context, i, visible),
              ),
            ),
        ],
      );

  /// 一张图:加载失败落在 `surface.sunken` + Phosphor `image`(§4 图片「失败」态)。
  Widget _image(BuildContext context, int index, List<String> visible) {
    final colors = context.ember;
    return Image.network(
      visible[index],
      fit: BoxFit.cover,
      errorBuilder: (_, _, _) => ColoredBox(
        color: colors.surfaceSunken,
        child: Center(
          child: Icon(
            PhosphorIconsRegular.image,
            size: tokens.sizeIcon20,
            color: colors.textTertiary,
          ),
        ),
      ),
    );
  }
}
