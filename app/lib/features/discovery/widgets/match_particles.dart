import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';

/// 附录 A.5 配对粒子:progress 0→1 = 自碰撞点向四周飘散渐隐。
/// 固定随机种子:轨迹每次一致,测试与手测可复现。
class MatchParticlesPainter extends CustomPainter {
  MatchParticlesPainter({required this.progress}) : _particles = _build();

  final double progress;
  final List<_Particle> _particles;

  static const _palette = [
    AppColors.brand,
    AppColors.heartOrange,
    AppColors.amber,
    Colors.white,
  ];

  static List<_Particle> _build() {
    final random = math.Random(7);
    return [
      for (var i = 0; i < 24; i++)
        _Particle(
          angle: i / 24 * 2 * math.pi + (random.nextDouble() - 0.5) * 0.5,
          speed: 60 + random.nextDouble() * 80,
          size: 2 + random.nextDouble() * 3,
          color: _palette[random.nextInt(_palette.length)],
          delay: random.nextDouble() * 0.25,
        ),
    ];
  }

  @override
  void paint(Canvas canvas, Size size) {
    if (progress <= 0) return;
    final center = Offset(size.width / 2, size.height / 2);
    for (final particle in _particles) {
      final t = ((progress - particle.delay) / (1 - particle.delay)).clamp(0.0, 1.0);
      if (t <= 0) continue;
      final eased = Curves.easeOutCubic.transform(t);
      final offset = center +
          Offset(math.cos(particle.angle), math.sin(particle.angle)) *
              particle.speed *
              eased;
      final paint = Paint()..color = particle.color.withValues(alpha: (1 - t) * 0.85);
      canvas.drawCircle(offset, particle.size * (1 - 0.3 * t), paint);
    }
  }

  @override
  bool shouldRepaint(MatchParticlesPainter oldDelegate) =>
      oldDelegate.progress != progress;
}

class _Particle {
  const _Particle({
    required this.angle,
    required this.speed,
    required this.size,
    required this.color,
    required this.delay,
  });

  final double angle;
  final double speed;
  final double size;
  final Color color;
  final double delay;
}
