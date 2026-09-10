import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../../core/api_exception.dart';
import '../models.dart';
import '../profile_controller.dart';
import '../profile_repository.dart';

typedef PickImage = Future<XFile?> Function();

Future<XFile?> pickImageFromGallery() => ImagePicker().pickImage(
      source: ImageSource.gallery,
      maxWidth: 1080,
      imageQuality: 85,
    );

const _maxBytes = 5 * 1024 * 1024;

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

  void _show(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _add() async {
    final file = await widget.pickImage();
    if (file == null) return;
    final bytes = await file.readAsBytes();
    if (!mounted) return;
    if (bytes.length > _maxBytes) {
      _show('图片不能超过 5MB');
      return;
    }
    setState(() => _busy = true);
    try {
      await ref.read(profileRepositoryProvider).uploadPhoto(bytes, file.name);
      await ref.read(profileProvider.notifier).reload();
    } on ApiException catch (error) {
      if (mounted) _show(error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _confirmDelete(Photo photo) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除这张照片?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('删除')),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    try {
      await ref.read(profileRepositoryProvider).deletePhoto(photo.id);
      await ref.read(profileProvider.notifier).reload();
    } on ApiException catch (error) {
      if (mounted) _show(error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final photos = ref.watch(profileProvider).value?.photos ?? const <Photo>[];
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final photo in photos)
          _PhotoTile(photo: photo, onDelete: () => _confirmDelete(photo)),
        if (photos.length < widget.maxCount) _AddTile(busy: _busy, onTap: _busy ? null : _add),
      ],
    );
  }
}

class _PhotoTile extends StatelessWidget {
  const _PhotoTile({required this.photo, required this.onDelete});

  final Photo photo;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 88,
      height: 88,
      child: Stack(
        fit: StackFit.expand,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: Image.network(
              photo.url,
              fit: BoxFit.cover,
              errorBuilder: (context, error, stack) => Container(
                color: Colors.black12,
                child: const Icon(Icons.broken_image_outlined),
              ),
            ),
          ),
          if (!photo.isApproved)
            Positioned(
              left: 4,
              bottom: 4,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration:
                    BoxDecoration(color: Colors.black54, borderRadius: BorderRadius.circular(4)),
                child: Text(photo.status == 'pending' ? '待审核' : '已驳回',
                    style: const TextStyle(color: Colors.white, fontSize: 11)),
              ),
            ),
          Positioned(
            right: 0,
            top: 0,
            child: IconButton(
              key: Key('photo.delete.${photo.id}'),
              iconSize: 18,
              onPressed: onDelete,
              icon: const CircleAvatar(radius: 11, child: Icon(Icons.close, size: 14)),
            ),
          ),
        ],
      ),
    );
  }
}

class _AddTile extends StatelessWidget {
  const _AddTile({required this.busy, required this.onTap});

  final bool busy;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      key: const Key('photo.add'),
      onTap: onTap,
      child: Container(
        width: 88,
        height: 88,
        decoration: BoxDecoration(
          border: Border.all(color: Colors.black26),
          borderRadius: BorderRadius.circular(8),
        ),
        child: busy
            ? const Center(
                child: SizedBox(
                    width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)))
            : const Icon(Icons.add_a_photo_outlined),
      ),
    );
  }
}
