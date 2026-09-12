import 'package:flutter/material.dart';

/// ＋面板:目前只有「相册」,后续入口加在这里。
class MorePanel extends StatelessWidget {
  const MorePanel({super.key, required this.onPickImage});

  final VoidCallback onPickImage;

  @override
  Widget build(BuildContext context) => Container(
        key: const Key('chat.more.panel'),
        height: 160,
        color: const Color(0xFFF7F3F5),
        padding: const EdgeInsets.all(16),
        child: Align(
          alignment: Alignment.topLeft,
          child: InkWell(
            key: const Key('chat.more.image'),
            onTap: onPickImage,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 56,
                  height: 56,
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: const Icon(Icons.photo_library_outlined, size: 28),
                ),
                const SizedBox(height: 6),
                const Text('相册', style: TextStyle(fontSize: 12)),
              ],
            ),
          ),
        ),
      );
}
