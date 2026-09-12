import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/image_pick.dart';
import 'feed_repository.dart';
import 'square_controller.dart';

const _maxBytes = 5 * 1024 * 1024;
const _maxCount = 9;

typedef _Picked = ({Uint8List bytes, String name});

/// 发布动态:文字(≤500)+ 九宫格选图(≤9);两者至少其一。
class PostComposePage extends ConsumerStatefulWidget {
  const PostComposePage({super.key, this.pickImages = pickImagesFromGallery});

  /// 测试注入用;默认打开系统相册多选。
  final PickImages pickImages;

  @override
  ConsumerState<PostComposePage> createState() => _PostComposePageState();
}

class _PostComposePageState extends ConsumerState<PostComposePage> {
  final _text = TextEditingController();
  final _images = <_Picked>[];
  bool _submitting = false;

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  void _show(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _pick() async {
    final files = await widget.pickImages();
    if (!mounted || files.isEmpty) return;
    for (final file in files) {
      if (_images.length >= _maxCount) {
        _show('最多 9 张图片');
        break;
      }
      final bytes = await file.readAsBytes();
      if (bytes.length > _maxBytes) {
        _show('单张图片不能超过 5MB');
        continue;
      }
      _images.add((bytes: bytes, name: file.name));
    }
    setState(() {});
  }

  Future<void> _submit() async {
    setState(() => _submitting = true);
    try {
      await ref.read(feedRepositoryProvider).createPost(
          text: _text.text.trim(), images: List.of(_images));
      ref.invalidate(squareProvider);
      if (mounted) Navigator.of(context).pop(true);
    } on ApiException catch (error) {
      if (mounted) _show(error.message);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final canSubmit = !_submitting && (_text.text.trim().isNotEmpty || _images.isNotEmpty);
    return Scaffold(
      appBar: AppBar(
        title: const Text('发布动态'),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: FilledButton(
              key: const Key('compose.submit'),
              onPressed: canSubmit ? _submit : null,
              child: const Text('发布'),
            ),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            key: const Key('compose.text'),
            controller: _text,
            maxLength: 500,
            maxLines: 6,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(
              hintText: '分享新鲜事…',
              border: InputBorder.none,
            ),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (var i = 0; i < _images.length; i++)
                _PickedTile(
                  key: Key('compose.picked.$i'),
                  bytes: _images[i].bytes,
                  onRemove: () => setState(() => _images.removeAt(i)),
                ),
              if (_images.length < _maxCount)
                InkWell(
                  key: const Key('compose.add'),
                  onTap: _pick,
                  child: Container(
                    width: 88,
                    height: 88,
                    decoration: BoxDecoration(
                      border: Border.all(color: Colors.black26),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: const Icon(Icons.add_a_photo_outlined),
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _PickedTile extends StatelessWidget {
  const _PickedTile({super.key, required this.bytes, required this.onRemove});

  final Uint8List bytes;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) => SizedBox(
        width: 88,
        height: 88,
        child: Stack(
          fit: StackFit.expand,
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: Image.memory(bytes, fit: BoxFit.cover,
                  errorBuilder: (c, e, s) => Container(color: Colors.black12)),
            ),
            Positioned(
              right: 0,
              top: 0,
              child: IconButton(
                onPressed: onRemove,
                iconSize: 18,
                icon: const CircleAvatar(radius: 11, child: Icon(Icons.close, size: 14)),
              ),
            ),
          ],
        ),
      );
}
