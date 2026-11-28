import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../core/api_exception.dart';
import '../../core/image_pick.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import 'feed_repository.dart';
import 'square_controller.dart';
import 'widgets/compose_photo_grid.dart';

/// 单张图片上限 5MB(与后端 `config/images.py` 一致,本地先拦一次)。
const _maxBytes = 5 * 1024 * 1024;

/// 单条动态最多几张图。
///
/// 直接引用 `pickImagesDefaultLimit`(相册多选的默认上限):两处若各写一个 9 就会漂移 ——
/// 「相册让你选 12 张、页面只收 9 张」这种不一致不会有任何测试或门禁发现。
const _maxCount = pickImagesDefaultLimit;

/// 正文上限(与后端 `posts` 序列化器的 500 字上限一致)。
const _maxTextLength = 500;

typedef _Picked = ({Uint8List bytes, String name});

/// 发布动态(附录 E / E-5.6c):§9.4 二级页 shell + 正文输入 + 三列选图 +
/// 底部主操作「发布」。
///
/// **只换皮**:正文与图片的上限、超限提示、发布成功后 `pop(true)` 与失效
/// `squareProvider` 的行为与改版前逐字一致。两处按 page spec 落地:
/// - 正文走 `EmberField`(高 52 起、`radius.md`、focus 2px `brand.default`);
/// - 提交失败给表单底部的 `status.danger` 提示条 + 保留已填内容(§5),不弹 Toast。
class PostComposePage extends ConsumerStatefulWidget {
  /// 构造发帖页。
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

  /// 提交失败的提示条文案;`null` 时不出提示条。
  String? _submitError;

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  /// 选图:把相册选回来的文件逐个过两道护栏,再追加到 [_images]。
  ///
  /// 两道护栏的**可达性不同**(2026-11-28 实测 + 用例钉住,见 #532):
  /// - **「最多 9 张」可达**:加号格只在 `< 9` 时渲染,但「已选 2 张再一次性多选 9 张」
  ///   会让循环补到 9 张后命中本分支 —— 这是真实用户路径;
  /// - **「单张 > 5MB」生产路径够不到**:`pickImagesFromGallery` 传了
  ///   `maxWidth: 1080 / imageQuality: 85`,image_picker 在交给本页之前就降采样了。
  ///   它**保留为防御性护栏**(将来放开 `maxWidth` 时不至于裸奔),并由
  ///   `app/test/features/square/post_compose_page_test.dart` 用注入的假 picker 覆盖。
  Future<void> _pick() async {
    final files = await widget.pickImages();
    if (!mounted) return;
    if (files.isEmpty) return;
    for (final file in files) {
      if (_images.length >= _maxCount) {
        EmberToast.show(context, '最多 $_maxCount 张图片');
        break;
      }
      final bytes = await file.readAsBytes();
      if (!mounted) return;
      if (bytes.length > _maxBytes) {
        EmberToast.show(context, '单张图片不能超过 5MB');
        continue;
      }
      _images.add((bytes: bytes, name: file.name));
    }
    setState(() {});
  }

  Future<void> _submit() async {
    setState(() {
      _submitError = null;
      _submitting = true;
    });
    try {
      await ref.read(feedRepositoryProvider).createPost(
          text: _text.text.trim(), images: List.of(_images));
      ref.invalidate(squareProvider);
      if (mounted) Navigator.of(context).pop(true);
    } on ApiException catch (error) {
      // 提交失败:提示条 + 保留正文与已选图(不弹 Toast,§5)。
      if (mounted) setState(() => _submitError = error.message);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final canSubmit =
        !_submitting && (_text.text.trim().isNotEmpty || _images.isNotEmpty);
    return EmberPageScaffold(
      title: '发布动态',
      backKey: const Key('compose.back'),
      bottomBar: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (_submitError != null) ...[
            _ComposeErrorBanner(message: _submitError!),
            SizedBox(height: tokens.space12),
          ],
          EmberButton(
            key: const Key('compose.submit'),
            label: '发布',
            expand: true,
            loading: _submitting,
            onPressed: canSubmit ? _submit : null,
          ),
        ],
      ),
      body: ListView(
        // 横向 20 由 shell 给(§9.4),这里只补纵向气口。
        padding: EdgeInsets.only(top: tokens.space16, bottom: tokens.space40),
        children: [
          EmberField(
            fieldKey: const Key('compose.text'),
            controller: _text,
            placeholder: '分享新鲜事…',
            label: '正文',
            maxLines: 6,
            maxLength: _maxTextLength,
            onChanged: (_) => setState(() {}),
          ),
          SizedBox(height: tokens.space4),
          // 字数计数自己画(EmberField 不渲染 Material 的计数器,§8.3 输入框只有四态)。
          Align(
            alignment: Alignment.centerRight,
            child: ExcludeSemantics(
              child: Text(
                '${_text.text.length}/$_maxTextLength',
                key: const Key('compose.counter'),
                style: TextStyle(
                  fontSize: tokens.fontSizeCaption,
                  height: tokens.fontLineHeightCaption,
                  color: colors.textTertiary,
                ),
              ),
            ),
          ),
          SizedBox(height: tokens.space16),
          ComposePhotoGrid(
            images: [for (final item in _images) item.bytes],
            onAdd: _pick,
            onRemove: (index) => setState(() => _images.removeAt(index)),
          ),
        ],
      ),
    );
  }
}

/// 提交失败提示条:`status.danger` 描边 + 图标 + 文案(page spec §5)。
///
/// 与编辑资料页的 `FormErrorBanner` 是同一形态的两份实现 —— 不跨 feature import
/// (与照片格删除徽标同一条口径:几十行不值得让 `square` 依赖 `profile`)。
class _ComposeErrorBanner extends StatelessWidget {
  const _ComposeErrorBanner({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Semantics(
      liveRegion: true,
      label: '发布失败，$message',
      child: Container(
        padding: EdgeInsets.symmetric(
          horizontal: tokens.space12,
          vertical: tokens.space8,
        ),
        decoration: BoxDecoration(
          color: colors.surfaceCard,
          borderRadius: BorderRadius.circular(tokens.radiusMd),
          border: Border.all(color: colors.statusDanger),
        ),
        child: Row(
          children: [
            Icon(
              PhosphorIconsRegular.warningCircle,
              size: tokens.sizeIcon16,
              color: colors.statusDanger,
            ),
            SizedBox(width: tokens.space8),
            Expanded(
              child: Text(
                message,
                style: TextStyle(
                  fontSize: tokens.fontSizeCaption,
                  height: tokens.fontLineHeightCaption,
                  color: colors.statusDanger,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
