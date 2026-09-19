import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_motion.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/app_avatar.dart';
import '../../../core/widgets/app_button.dart';
import '../models.dart';
import 'match_particles.dart';

/// 配对成功动效(§6.2 情感时刻,附录 A.5):光晕扩散 → 双头像相向碰撞 →
/// 粒子飘散 → 文案按钮。全程 ~1100ms 有限动画;点击任意处直达完成帧;
/// 「减弱动态效果」直接呈现完成帧。无循环动画(pumpAndSettle 可达完成帧)。
class MatchOverlay extends StatefulWidget {
  const MatchOverlay({
    super.key,
    required this.candidate,
    this.myAvatarUrl,
    required this.onClose,
    this.onGoChat,
  });

  final Candidate candidate;
  final String? myAvatarUrl;
  final VoidCallback onClose;

  /// 有值才显示「去聊天」按钮。
  final VoidCallback? onGoChat;

  @override
  State<MatchOverlay> createState() => _MatchOverlayState();
}

class _MatchOverlayState extends State<MatchOverlay> with SingleTickerProviderStateMixin {
  static const _total = Duration(milliseconds: 1100);

  late final AnimationController _c = AnimationController(vsync: this, duration: _total);
  bool _started = false;

  // 分段(0–1 比例 × 1100ms:0–550 光晕 / 150–550 头像 / 500–800 爆发 /
  // 500–750 心形 / 600–1100 粒子 / 800–1100 文案按钮)
  late final Animation<double> _halo =
      CurvedAnimation(parent: _c, curve: const Interval(0, .5, curve: Curves.easeOutCubic));
  late final Animation<double> _avatars =
      CurvedAnimation(parent: _c, curve: const Interval(.136, .5, curve: Curves.easeOutCubic));
  late final Animation<double> _burst =
      CurvedAnimation(parent: _c, curve: const Interval(.455, .73));
  late final Animation<double> _heart =
      CurvedAnimation(parent: _c, curve: const Interval(.455, .68, curve: Curves.easeOutBack));
  late final Animation<double> _particles =
      CurvedAnimation(parent: _c, curve: const Interval(.545, 1));
  late final Animation<double> _text =
      CurvedAnimation(parent: _c, curve: const Interval(.727, 1, curve: Curves.easeOutCubic));

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_started) return;
    _started = true;
    if (MediaQuery.disableAnimationsOf(context)) {
      _c.value = 1;
    } else {
      _c.forward();
    }
  }

  void _skip() => _c.value = 1; // value setter 内部会 stop

  @override
  Widget build(BuildContext context) {
    final theirAvatarUrl =
        widget.candidate.photos.isEmpty ? null : widget.candidate.photos.first.url;
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: _skip,
        child: AnimatedBuilder(
          animation: _c,
          builder: (context, _) => Stack(
            children: [
              Center(
                child: SizedBox.square(
                  dimension: 280,
                  child: Stack(
                    alignment: Alignment.center,
                    clipBehavior: Clip.none,
                    children: [
                      // 光晕(从双头像位置扩散)
                      Opacity(
                        opacity: _halo.value * 0.9,
                        child: Container(
                          width: 130 + 150 * _halo.value,
                          height: 130 + 150 * _halo.value,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            gradient: RadialGradient(
                              colors: [
                                AppColors.brand.withValues(alpha: 0.55),
                                AppColors.heartOrange.withValues(alpha: 0.28),
                                Colors.transparent,
                              ],
                            ),
                          ),
                        ),
                      ),
                      // 碰撞爆发环
                      Opacity(
                        opacity: 1 - _burst.value,
                        child: Container(
                          width: 120 + 140 * _burst.value,
                          height: 120 + 140 * _burst.value,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            border: Border.all(
                              color: AppColors.brand.withValues(alpha: 0.65),
                              width: 2,
                            ),
                          ),
                        ),
                      ),
                      // 粒子飘散
                      Positioned.fill(
                        child: CustomPaint(
                          painter: MatchParticlesPainter(progress: _particles.value),
                        ),
                      ),
                      // 双头像相向滑入(定格圆心间距 66)
                      Transform.translate(
                        offset: Offset(-33 - 56 * (1 - _avatars.value), 0),
                        child: AppAvatar(imageUrl: widget.myAvatarUrl, size: 96, halo: true),
                      ),
                      Transform.translate(
                        offset: Offset(33 + 56 * (1 - _avatars.value), 0),
                        child: AppAvatar(imageUrl: theirAvatarUrl, size: 96, halo: true),
                      ),
                      // 心形弹出(0.6 → 1,easeOutBack 自带过冲 ~1.1)
                      Transform.scale(
                        scale: 0.6 + 0.4 * _heart.value,
                        child: Icon(
                          Icons.favorite_rounded,
                          size: 30,
                          color: AppColors.brand,
                          shadows: [
                            Shadow(
                              color: AppColors.brand.withValues(alpha: 0.8),
                              blurRadius: 18,
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              Align(
                alignment: Alignment.bottomCenter,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(AppSpacing.xxl, 0, AppSpacing.xxl, 48),
                  child: Opacity(
                    opacity: _text.value,
                    child: Transform.translate(
                      offset: Offset(0, 8 * (1 - _text.value)),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            '你们已互相喜欢',
                            style: AppText.title.copyWith(color: Colors.white),
                          ),
                          const SizedBox(height: AppSpacing.sm),
                          Text(
                            '和 ${widget.candidate.nickname} 打个招呼吧',
                            style: AppText.caption.copyWith(
                                color: Colors.white.withValues(alpha: 0.72)),
                          ),
                          const SizedBox(height: AppSpacing.xxl),
                          Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              if (widget.onGoChat != null) ...[
                                AppButton(
                                  key: const Key('match.goChat'),
                                  label: '去聊天',
                                  onPressed: widget.onGoChat,
                                ),
                                const SizedBox(width: AppSpacing.md),
                              ],
                              AppButton(
                                key: const Key('match.continue'),
                                label: '继续滑卡',
                                variant: AppButtonVariant.secondary,
                                onPressed: widget.onClose,
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 弹配对动效;等它关闭后 future 才完成。
Future<void> showMatchOverlay(
  BuildContext context, {
  required Candidate candidate,
  String? myAvatarUrl,
  VoidCallback? onGoChat,
}) =>
    showGeneralDialog<void>(
      context: context,
      barrierDismissible: false,
      barrierLabel: '配对成功',
      barrierColor: AppColors.text1.withValues(alpha: 0.94),
      transitionDuration: AppMotion.base,
      pageBuilder: (dialogContext, animation, secondary) => MatchOverlay(
        candidate: candidate,
        myAvatarUrl: myAvatarUrl,
        onClose: () => Navigator.of(dialogContext).pop(),
        // 先关弹层再跳,不然路由推在弹层下面
        onGoChat: onGoChat == null
            ? null
            : () {
                Navigator.of(dialogContext).pop();
                onGoChat();
              },
      ),
      transitionBuilder: (context, animation, secondary, child) =>
          FadeTransition(opacity: animation, child: child),
    );
