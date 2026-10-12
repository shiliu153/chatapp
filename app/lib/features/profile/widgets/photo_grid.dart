import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_exception.dart';
import '../../../core/image_pick.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_motion.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/app_dialog.dart';
import '../../../core/widgets/app_toast.dart';
import '../models.dart';
import '../profile_controller.dart';
import '../profile_repository.dart';

const _maxBytes = 5 * 1024 * 1024;

/// 资料照片网格(§5.3 相册/照片网格:3 列、R12);最多 [maxCount] 张。
class PhotoGrid extends ConsumerStatefulWidget {
  const PhotoGrid({super.key, this.pickImage = pickImageFromGallery, this.maxCount = 6});

  /// 测试注入用;默认打开系统相册。
  final PickImage pickImage;
  final int maxCount;

  @override
  ConsumerState<PhotoGrid> createState() => _PhotoGridState();
}

class _PhotoGridState extends ConsumerState<PhotoGrid> {
  bool _busy = false;

  Future<void> _add() async {
    final file = await widget.pickImage();
    if (file == null) return;
    final bytes = await file.readAsBytes();
    if (!mounted) return;
    if (bytes.length > _maxBytes) {
      AppToast.show(context, '图片不能超过 5MB');
      return;
    }
    setState(() => _busy = true);
    try {
      await ref.read(profileRepositoryProvider).uploadPhoto(bytes, file.name);
      await ref.read(profileProvider.notifier).reload();
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _confirmDelete(Photo photo) async {
    final confirmed = await showConfirmDialog(
      context,
      title: '删除这张照片?',
      confirmLabel: '删除',
      danger: true,
    );
    if (!confirmed || !mounted) return;
    try {
      await ref.read(profileRepositoryProvider).deletePhoto(photo.id);
      await ref.read(profileProvider.notifier).reload();
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final photos = ref.watch(profileProvider).value?.photos ?? const <Photo>[];
    return GridView.count(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      crossAxisCount: 3,
      mainAxisSpacing: AppSpacing.sm,
      crossAxisSpacing: AppSpacing.sm,
      children: [
        for (final photo in photos)
          _PhotoTile(photo: photo, onDelete: () => _confirmDelete(photo)),
        if (photos.length < widget.maxCount)
          _AddTile(busy: _busy, onTap: _busy ? null : _add),
      ],
    );
  }
}

class _PhotoTile extends StatelessWidget {
  const _PhotoTile({required this.photo, required this.onDelete});

  final Photo photo;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) => Stack(
        fit: StackFit.expand,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(AppRadius.image),
            child: Image.network(
              photo.url,
              fit: BoxFit.cover,
              errorBuilder: (context, error, stack) => const ColoredBox(
                color: AppColors.divider,
                child: Center(
                  child: Icon(Icons.image_rounded, color: AppColors.text3),
                ),
              ),
            ),
          ),
          if (!photo.isApproved)
            Positioned(
              left: AppSpacing.xs,
              bottom: AppSpacing.xs,
              child: Container(
                padding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.sm, vertical: 2),
                decoration: BoxDecoration(
                  color: AppColors.amber,
                  borderRadius: BorderRadius.circular(AppRadius.chip),
                ),
                child: Text(
                  photo.status == 'pending' ? '待审核' : '已驳回',
                  style: AppText.badge.copyWith(color: Colors.white),
                ),
              ),
            ),
          Positioned(
            right: 0,
            top: 0,
            child: IconButton(
              key: Key('photo.delete.${photo.id}'),
              iconSize: 18,
              onPressed: onDelete,
              icon: const _RemoveBadge(),
            ),
          ),
        ],
      );
}

/// 半透明深底圆 + 白叉(照片右上角删除钮)。
/// 发动态选图另有一份同款私有副本 —— 不跨 feature import(12 行不值得建依赖)。
class _RemoveBadge extends StatelessWidget {
  const _RemoveBadge();

  @override
  Widget build(BuildContext context) => Container(
        width: 22,
        height: 22,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: AppColors.text1.withValues(alpha: .55),
        ),
        child: const Icon(Icons.close_rounded, size: 14, color: Colors.white),
      );
}

class _AddTile extends StatefulWidget {
  const _AddTile({required this.busy, required this.onTap});

  final bool busy;
  final VoidCallback? onTap;

  @override
  State<_AddTile> createState() => _AddTileState();
}

class _AddTileState extends State<_AddTile> {
  var _pressed = false;

  @override
  Widget build(BuildContext context) => GestureDetector(
        key: const Key('photo.add'),
        behavior: HitTestBehavior.opaque,
        onTapDown:
            widget.onTap == null ? null : (_) => setState(() => _pressed = true),
        onTapUp:
            widget.onTap == null ? null : (_) => setState(() => _pressed = false),
        onTapCancel: widget.onTap == null
            ? null
            : () => setState(() => _pressed = false),
        onTap: widget.onTap,
        child: AnimatedScale(
          scale: _pressed ? 0.96 : 1,
          duration: AppMotion.fast,
          child: DecoratedBox(
            decoration: BoxDecoration(
              color: AppColors.bgCard,
              borderRadius: BorderRadius.circular(AppRadius.image),
              border: Border.all(color: AppColors.divider),
            ),
            child: Center(
              child: widget.busy
                  // §7 加载:按钮内用小转圈(白底上用 brand)
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: AppColors.brand),
                    )
                  : const Icon(Icons.add_photo_alternate_rounded,
                      size: 24, color: AppColors.text3),
            ),
          ),
        ),
      );
}
