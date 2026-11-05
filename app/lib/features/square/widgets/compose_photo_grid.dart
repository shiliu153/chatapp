import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../../../core/theme/app_motion.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/heart_theme_context.dart';

/// 发动态选图(附录 E):3 列 R12 正方格,与广场九宫格同视觉;
/// 加号格 `divider` 描边,已选图右上角半透明深底删除钮。
class ComposePhotoGrid extends StatelessWidget {
  const ComposePhotoGrid({
    super.key,
    required this.images,
    required this.onRemove,
    required this.onAdd,
    this.maxCount = 9,
  });

  final List<Uint8List> images;
  final ValueChanged<int> onRemove;
  final VoidCallback onAdd;
  final int maxCount;

  @override
  Widget build(BuildContext context) => GridView.count(
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        crossAxisCount: 3,
        mainAxisSpacing: AppSpacing.sm,
        crossAxisSpacing: AppSpacing.sm,
        children: [
          for (var i = 0; i < images.length; i++)
            _PickedTile(
              key: Key('compose.picked.$i'),
              bytes: images[i],
              onRemove: () => onRemove(i),
            ),
          if (images.length < maxCount) _AddTile(onTap: onAdd),
        ],
      );
}

class _PickedTile extends StatelessWidget {
  const _PickedTile({super.key, required this.bytes, required this.onRemove});

  final Uint8List bytes;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    return Stack(
        fit: StackFit.expand,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(AppRadius.image),
            child: Image.memory(
              bytes,
              fit: BoxFit.cover,
              errorBuilder: (_, _, _) => ColoredBox(
                color: colors.divider,
                child: Center(
                  child: Icon(Icons.image_rounded, color: colors.text3),
                ),
              ),
            ),
          ),
          Positioned(
            right: 0,
            top: 0,
            child: IconButton(
              iconSize: 18,
              onPressed: onRemove,
              icon: const _RemoveBadge(),
            ),
          ),
        ],
      );
  }
}

/// 半透明深底圆 + 白叉(与资料照片网格同款,各自私有副本,不跨 feature import)。
class _RemoveBadge extends StatelessWidget {
  const _RemoveBadge();

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    return Container(
        width: 22,
        height: 22,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: colors.text1.withValues(alpha: .55),
        ),
        child: const Icon(Icons.close_rounded, size: 14, color: Colors.white),
      );
  }
}

class _AddTile extends StatefulWidget {
  const _AddTile({required this.onTap});

  final VoidCallback onTap;

  @override
  State<_AddTile> createState() => _AddTileState();
}

class _AddTileState extends State<_AddTile> {
  var _pressed = false;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    return GestureDetector(
        key: const Key('compose.add'),
        behavior: HitTestBehavior.opaque,
        onTapDown: (_) => setState(() => _pressed = true),
        onTapUp: (_) => setState(() => _pressed = false),
        onTapCancel: () => setState(() => _pressed = false),
        onTap: widget.onTap,
        child: AnimatedScale(
          scale: _pressed ? 0.96 : 1,
          duration: AppMotion.fast,
          child: DecoratedBox(
            decoration: BoxDecoration(
              color: colors.bgCard,
              borderRadius: BorderRadius.circular(AppRadius.image),
              border: Border.all(color: colors.divider),
            ),
            child: Center(
              child: Icon(Icons.add_photo_alternate_rounded,
                  size: 24, color: colors.text3),
            ),
          ),
        ),
      );
  }
}
