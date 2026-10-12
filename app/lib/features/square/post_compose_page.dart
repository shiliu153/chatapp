import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/image_pick.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_text_action.dart';
import '../../core/widgets/app_text_field.dart';
import '../../core/widgets/app_toast.dart';
import 'feed_repository.dart';
import 'square_controller.dart';
import 'widgets/compose_photo_grid.dart';

const _maxBytes = 5 * 1024 * 1024;
const _maxCount = 9;

typedef _Picked = ({Uint8List bytes, String name});

/// 发布动态(附录 E):顶栏「发布」文字按钮 + 无边框正文 + 三列选图。
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

  Future<void> _pick() async {
    final files = await widget.pickImages();
    if (!mounted) return;
    if (files.isEmpty) return;
    for (final file in files) {
      if (_images.length >= _maxCount) {
        AppToast.show(context, '最多 9 张图片');
        break;
      }
      final bytes = await file.readAsBytes();
      if (!mounted) return;
      if (bytes.length > _maxBytes) {
        AppToast.show(context, '单张图片不能超过 5MB');
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
      if (mounted) AppToast.show(context, error.message);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final canSubmit =
        !_submitting && (_text.text.trim().isNotEmpty || _images.isNotEmpty);
    return Scaffold(
      backgroundColor: AppColors.bgPage,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            AppSubPageBar(
              title: '发布动态',
              trailing: AppTextAction(
                key: const Key('compose.submit'),
                label: '发布',
                onPressed: canSubmit ? _submit : null,
              ),
            ),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(AppSpacing.pageH,
                    AppSpacing.md, AppSpacing.pageH, AppSpacing.xxl),
                children: [
                  AppTextField(
                    key: const Key('compose.text'),
                    controller: _text,
                    hint: '分享新鲜事…',
                    borderless: true,
                    maxLines: 6,
                    minLines: 6,
                    maxLength: 500,
                    counterKey: const Key('compose.counter'),
                    onChanged: (_) => setState(() {}),
                  ),
                  const SizedBox(height: AppSpacing.lg),
                  ComposePhotoGrid(
                    images: [for (final item in _images) item.bytes],
                    onAdd: _pick,
                    onRemove: (index) =>
                        setState(() => _images.removeAt(index)),
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
