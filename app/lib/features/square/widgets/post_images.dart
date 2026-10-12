import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';

/// 动态配图(附录 D):1 张通栏大图(高 240);2–9 张统一 3 列正方格。
/// 假网络/断网时图挂 → divider 底内容占位(非空态)。
class PostImages extends StatelessWidget {
  const PostImages({super.key, required this.urls, this.onTap});

  final List<String> urls;
  final void Function(int index)? onTap;

  /// 1 张通栏的固定高(附录 D;屏宽自适应宽度)。
  static const _singleHeight = 240.0;

  @override
  Widget build(BuildContext context) {
    if (urls.isEmpty) return const SizedBox.shrink();
    if (urls.length == 1) {
      return GestureDetector(
        key: const Key('post.image.0'), // 单图分支补 key(原缺失,与网格分支对齐)
        onTap: () => onTap?.call(0),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(AppRadius.image),
          child: SizedBox(
            width: double.infinity,
            height: _singleHeight,
            child: _image(0),
          ),
        ),
      );
    }
    return GridView.count(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      crossAxisCount: 3,
      mainAxisSpacing: AppSpacing.sm,
      crossAxisSpacing: AppSpacing.sm,
      children: [
        for (var i = 0; i < urls.length; i++)
          GestureDetector(
            key: Key('post.image.$i'),
            onTap: () => onTap?.call(i),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(AppRadius.image),
              child: _image(i),
            ),
          ),
      ],
    );
  }

  Widget _image(int index) => Image.network(
        urls[index],
        fit: BoxFit.cover,
        errorBuilder: (_, _, _) => const ColoredBox(
          color: AppColors.divider,
          child: Center(
            child: Icon(Icons.image_rounded, color: AppColors.text3),
          ),
        ),
      );
}
