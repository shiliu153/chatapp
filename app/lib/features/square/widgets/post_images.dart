import 'package:flutter/material.dart';

/// 微博式九宫格:1 张大图;2-4 张两列;5-9 张三列。
class PostImages extends StatelessWidget {
  const PostImages({super.key, required this.urls, this.onTap});

  final List<String> urls;
  final void Function(int index)? onTap;

  @override
  Widget build(BuildContext context) {
    if (urls.isEmpty) return const SizedBox.shrink();
    if (urls.length == 1) {
      return GestureDetector(
        onTap: () => onTap?.call(0),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(6),
          child: SizedBox(width: 200, height: 200, child: _image(0)),
        ),
      );
    }
    final columns = urls.length <= 4 ? 2 : 3;
    return GridView.count(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      crossAxisCount: columns,
      mainAxisSpacing: 4,
      crossAxisSpacing: 4,
      children: [
        for (var i = 0; i < urls.length; i++)
          GestureDetector(
            key: Key('post.image.$i'),
            onTap: () => onTap?.call(i),
            child: _image(i),
          ),
      ],
    );
  }

  Widget _image(int index) => Image.network(
        urls[index],
        fit: BoxFit.cover,
        errorBuilder: (c, e, s) => Container(
          color: const Color(0xFFEFE3E7),
          child: const Icon(Icons.image_outlined, color: Colors.white70),
        ),
      );
}
