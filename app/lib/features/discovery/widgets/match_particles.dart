import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../core/theme/ember_colors.dart';

/// 配对粒子(「余烬 Ember」§7.2 情感时刻的收尾):progress 0→1 = 自碰撞点向四周
/// 飘散渐隐。固定随机种子:轨迹每次一致,测试与手测可复现。
///
/// 配色只取语义板:朱砂 `brand.default`、次强调 `accent.default`、预警
/// `status.warning` 与白 —— 心跳期的 `heartOrange` / `amber` 过渡别名不在这里用,
/// 免得「又多一处走别名」。
class MatchParticlesPainter extends CustomPainter {
  /// 构造粒子画笔。
  MatchParticlesPainter({required this.progress, required EmberColors colors})
      : _particles = _build(colors);

  /// 0→1 的飘散进度。
  final double progress;

  final List<_Particle> _particles;

  /// 自绘发生在 paint 阶段(拿不到 BuildContext),色板由外部注入。
  static List<Color> _paletteOf(EmberColors colors) => [
        colors.brandDefault,
        colors.accentDefault,
        colors.statusWarning,
        Colors.white,
      ];

  static List<_Particle> _build(EmberColors colors) {
    final palette = _paletteOf(colors);
    final random = math.Random(7);
    return [
      for (var i = 0; i < 24; i++)
        _Particle(
          angle: i / 24 * 2 * math.pi + (random.nextDouble() - 0.5) * 0.5,
          speed: 60 + random.nextDouble() * 80,
          size: 2 + random.nextDouble() * 3,
          color: palette[random.nextInt(palette.length)],
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
      // 自绘里没有「每帧推进的 Simulation」可挂:粒子只是装饰性轨迹,用三次减速
      // 近似弹簧末段的收敛(先快后慢)。可打断的**位移链路**(卡片、头像)才必须
      // 走 spring(§7.1)。
      final eased = 1 - math.pow(1 - t, 3).toDouble();
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

/// 单颗粒子的参数(角度 / 速度 / 半径 / 颜色 / 延迟)。
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
