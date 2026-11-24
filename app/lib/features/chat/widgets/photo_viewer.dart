import 'package:flutter/material.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/theme/tokens.g.dart' as tokens;

/// 全屏看图:黑底、左右滑、双指缩放、点右上角关闭。聊天图片与资料页相册共用。
///
/// 「沉浸内容 = 全屏」(§9.3),所以底色保持纯黑 / 图标纯白 —— 它们是**两模式语义相同**
/// 的两个例外(见 `no_raw_colors_test` 的白黑白名单)。
class PhotoViewerPage extends StatefulWidget {
  const PhotoViewerPage({super.key, required this.urls, this.initialIndex = 0});

  final List<String> urls;
  final int initialIndex;

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
              itemBuilder: (context, index) => InteractiveViewer(
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
              ),
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

void openPhotoViewer(BuildContext context,
    {required List<String> urls, int initialIndex = 0}) {
  if (urls.isEmpty) return;
  Navigator.of(context).push(MaterialPageRoute(
    builder: (_) => PhotoViewerPage(urls: urls, initialIndex: initialIndex),
  ));
}
