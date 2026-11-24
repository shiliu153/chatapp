import 'package:flutter/material.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/theme/tokens.g.dart' as tokens;

/// 全屏看图:黑底、左右滑、双指缩放、点右上角关闭。聊天图片与资料页相册共用。
///
/// 「沉浸内容 = 全屏」(§9.3),所以底色保持纯黑 / 图标纯白 —— 它们是**两模式语义相同**
/// 的两个例外(见 `no_raw_colors_test` 的白黑白名单)。
///
/// Hero(E-5.4 page spec §2「照片查看:全屏 + Hero」):调用方给 [heroTags] 时,
/// 第 i 张图包一层 `Hero(tag: heroTags[i])`,与来源缩略图同 tag 即可飞行;不给时
/// 与旧行为完全一致(聊天图片不参与 Hero)。
class PhotoViewerPage extends StatefulWidget {
  /// 构造全屏看图。
  const PhotoViewerPage({
    super.key,
    required this.urls,
    this.initialIndex = 0,
    this.heroTags,
  });

  /// 图片地址(按相册顺序)。
  final List<String> urls;

  /// 起始下标。
  final int initialIndex;

  /// 与 [urls] 一一对应的 Hero tag;`null` 表示不参与 Hero。
  final List<String>? heroTags;

  @override
  State<PhotoViewerPage> createState() => _PhotoViewerPageState();
}

class _PhotoViewerPageState extends State<PhotoViewerPage> {
  late final PageController _controller =
      PageController(initialPage: widget.initialIndex);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: Colors.black,
        body: Stack(
          children: [
            PageView.builder(
              key: const Key('viewer.page'),
              controller: _controller,
              itemCount: widget.urls.length,
              itemBuilder: (context, index) {
                final Widget page = InteractiveViewer(
                  maxScale: 4,
                  child: Center(
                    child: Image.network(
                      widget.urls[index],
                      fit: BoxFit.contain,
                      errorBuilder: (c, e, s) => const Icon(
                        PhosphorIconsRegular.imageBroken,
                        color: Colors.white38,
                        size: 64,
                      ),
                    ),
                  ),
                );
                final tags = widget.heroTags;
                if (tags == null || index >= tags.length) return page;
                return Hero(tag: tags[index], child: page);
              },
            ),
            SafeArea(
              child: Align(
                alignment: Alignment.topRight,
                child: IconButton(
                  key: const Key('viewer.close'),
                  onPressed: () => Navigator.of(context).pop(),
                  // 热区 48(§8.4),图标本体 24(§6 工具栏档)。
                  iconSize: tokens.sizeIcon24,
                  icon: const Icon(PhosphorIconsRegular.x, color: Colors.white),
                ),
              ),
            ),
          ],
        ),
      );
}

/// 打开全屏看图;[heroTags] 给定时按 E-5.4 的相册口径参与 Hero 转场。
void openPhotoViewer(
  BuildContext context, {
  required List<String> urls,
  int initialIndex = 0,
  List<String>? heroTags,
}) {
  if (urls.isEmpty) return;
  Navigator.of(context).push(MaterialPageRoute(
    builder: (_) => PhotoViewerPage(
      urls: urls,
      initialIndex: initialIndex,
      heroTags: heroTags,
    ),
  ));
}
