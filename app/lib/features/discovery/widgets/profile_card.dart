import 'package:flutter/material.dart';

import '../models.dart';

/// 单张候选卡:照片区(多张时点左右两侧切换)+ 底部资料区。
class ProfileCard extends StatefulWidget {
  const ProfileCard({super.key, required this.candidate});

  final Candidate candidate;

  @override
  State<ProfileCard> createState() => _ProfileCardState();
}

class _ProfileCardState extends State<ProfileCard> {
  int _photoIndex = 0;

  @override
  void didUpdateWidget(covariant ProfileCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    // 换成另一个人的卡了,照片从第一张重新看起
    if (oldWidget.candidate.userId != widget.candidate.userId) _photoIndex = 0;
  }

  void _shiftPhoto(int delta) {
    final count = widget.candidate.photos.length;
    if (count < 2) return;
    setState(() => _photoIndex = (_photoIndex + delta + count) % count);
  }

  @override
  Widget build(BuildContext context) {
    final candidate = widget.candidate;
    final photos = candidate.photos;
    final photo = photos.isEmpty ? null : photos[_photoIndex];
    return Material(
      elevation: 2,
      borderRadius: BorderRadius.circular(16),
      clipBehavior: Clip.antiAlias,
      child: Stack(
        fit: StackFit.expand,
        children: [
          if (photo == null)
            const ColoredBox(
              color: Colors.black12,
              child: Center(child: Icon(Icons.person_outline, size: 64)),
            )
          else
            Image.network(
              photo.url,
              key: ValueKey('card.photo.${photo.id}'),
              fit: BoxFit.cover,
              errorBuilder: (context, error, stack) => const ColoredBox(
                color: Colors.black12,
                child: Center(child: Icon(Icons.broken_image_outlined, size: 48)),
              ),
            ),
          if (photos.length > 1) ...[
            Positioned(
              left: 0,
              top: 0,
              bottom: 0,
              width: 56,
              child: GestureDetector(
                key: const Key('card.prevPhoto'),
                behavior: HitTestBehavior.translucent,
                onTap: () => _shiftPhoto(-1),
              ),
            ),
            Positioned(
              right: 0,
              top: 0,
              bottom: 0,
              width: 56,
              child: GestureDetector(
                key: const Key('card.nextPhoto'),
                behavior: HitTestBehavior.translucent,
                onTap: () => _shiftPhoto(1),
              ),
            ),
            Positioned(
              top: 8,
              left: 0,
              right: 0,
              child: Row(
                key: const Key('card.dots'),
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  for (var i = 0; i < photos.length; i++)
                    Container(
                      width: 8,
                      height: 8,
                      margin: const EdgeInsets.symmetric(horizontal: 3),
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: i == _photoIndex ? Colors.white : Colors.white38,
                      ),
                    ),
                ],
              ),
            ),
          ],
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: Container(
              padding: const EdgeInsets.fromLTRB(16, 32, 16, 16),
              decoration: const BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [Colors.transparent, Colors.black87],
                ),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    candidate.age == null
                        ? candidate.nickname
                        : '${candidate.nickname},${candidate.age}',
                    style: const TextStyle(
                        color: Colors.white, fontSize: 22, fontWeight: FontWeight.bold),
                  ),
                  if (candidate.city.isNotEmpty)
                    Text(candidate.city,
                        style: const TextStyle(color: Colors.white70, fontSize: 13)),
                  if (candidate.bio.isNotEmpty) ...[
                    const SizedBox(height: 6),
                    Text(
                      candidate.bio,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: Colors.white, fontSize: 14),
                    ),
                  ],
                  if (candidate.tags.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 6,
                      runSpacing: 6,
                      children: [
                        for (final tag in candidate.tags)
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                            decoration: BoxDecoration(
                              color: Colors.white24,
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: Text(tag.name,
                                style: const TextStyle(color: Colors.white, fontSize: 12)),
                          ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
