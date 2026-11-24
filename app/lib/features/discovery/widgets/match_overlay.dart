import 'package:flutter/material.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/theme/app_typography.dart';
import '../../../core/theme/ember_motion.dart';
import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';
import '../../profile/models.dart';
import '../icebreaker.dart';
import '../models.dart';
import 'match_particles.dart';

/// 配对成功动效(「余烬 Ember」§7.2 情感时刻 / §9.2「配对 = 独立状态」,
/// E-5.2 page spec §3 / §4 配对编排行):
/// `emberGlow` 径向扩散 → 双头像相向碰撞 → 粒子飘散 → 文案按钮。
///
/// 三条硬口径:
/// - **分段缓动全部换成 `spring.gentle`**(§7.1:位移类一律弹簧)。几段压在同一条
///   1100ms 总时间轴上,所以用 [EmberMotion.springCurve] 把弹簧表达成段落缓动,
///   既保留「一条时间轴可跳过」,又不把固定曲线常量带回来;
/// - 光晕是 **`emberGlow` 径向扩散**(朱砂 @12%,§18.6),不是心跳期那种高饱和
///   双色渐变;一屏只有这一处(§2);
/// - 「减弱动态效果」时**直接呈现完成帧**,不做位移/缩放(§8.4);点任意处直达
///   完成帧(§7.3「超过 400ms 必须可跳过」),全程无循环动画。
class MatchOverlay extends StatefulWidget {
  /// 构造配对编排。
  const MatchOverlay({
    super.key,
    required this.candidate,
    this.myAvatarUrl,
    this.sharedTags = const [],
    this.myCity = '',
    required this.onClose,
    this.onGoChat,
  });

  /// 刚配上的人。
  final Candidate candidate;

  /// 我的头像(拿不到就不画图,回落到首字)。
  final String? myAvatarUrl;

  /// 共同标签(来自滑卡响应),只用于「配对那一刻」的破冰文案。
  final List<Tag> sharedTags;

  /// 我的城市:与对方城市相同才展示「你们都在 X」。
  final String myCity;

  /// 关闭编排(「继续滑卡」也走这里)。
  final VoidCallback onClose;

  /// 有值才显示「去聊天」按钮。
  final VoidCallback? onGoChat;

  /// 编排总时长(spec「900–1400ms」取 1100)。
  static const total = Duration(milliseconds: 1100);

  @override
  State<MatchOverlay> createState() => _MatchOverlayState();
}

class _MatchOverlayState extends State<MatchOverlay> with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: MatchOverlay.total);
  bool _started = false;

  /// 分段弹簧曲线(`spring.gentle`,采样 900ms 摊到 `t` 0→1)。
  Curve get _spring => EmberMotion.gentleCurve;

  // 分段(0–1 比例 × 1100ms):光晕 0–.5 / 头像 .136–.5 / 爆发 .455–.73 /
  // 心形 .455–.68 / 粒子 .545–1 / 文案按钮 .727–1
  late final Animation<double> _halo =
      CurvedAnimation(parent: _c, curve: Interval(0, .5, curve: _spring));
  late final Animation<double> _avatars =
      CurvedAnimation(parent: _c, curve: Interval(.136, .5, curve: _spring));
  late final Animation<double> _burst =
      CurvedAnimation(parent: _c, curve: const Interval(.455, .73));
  late final Animation<double> _heart =
      CurvedAnimation(parent: _c, curve: Interval(.455, .68, curve: _spring));
  late final Animation<double> _particles =
      CurvedAnimation(parent: _c, curve: const Interval(.545, 1));
  late final Animation<double> _text =
      CurvedAnimation(parent: _c, curve: Interval(.727, 1, curve: _spring));

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
    // 减弱动态效果:不做位移/缩放,直接给完成帧(§8.4)。
    if (EmberMotion.reducedOf(context)) {
      _c.value = 1;
    } else {
      _c.forward();
    }
  }

  /// 点任意处直达完成帧(`value` 的 setter 内部会 `stop`)。
  void _skip() => _c.value = 1;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final theirAvatarUrl =
        widget.candidate.photos.isEmpty ? null : widget.candidate.photos.first.url;
    // 共同点只在「配对那一刻」说一句:有共同标签说标签,否则只在同城时说城市。
    final icebreaker = matchIcebreaker(
      sharedTagNames: [for (final tag in widget.sharedTags) tag.name],
      myCity: widget.myCity,
      peerCity: widget.candidate.city,
    );
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
                      // `emberGlow` 径向扩散:朱砂 @12% 从双头像位置向外淡出。
                      Opacity(
                        opacity: _halo.value.clamp(0, 1),
                        child: Container(
                          width: 130 + 150 * _halo.value,
                          height: 130 + 150 * _halo.value,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            gradient: RadialGradient(
                              colors: [
                                colors.brandDefault.withValues(alpha: 0.12),
                                colors.brandDefault.withValues(alpha: 0),
                              ],
                              stops: const [0.55, 1],
                            ),
                          ),
                        ),
                      ),
                      // 碰撞爆发环:一圈朱砂描边向外散开(有限动画,不是循环)。
                      Opacity(
                        opacity: (1 - _burst.value).clamp(0, 1),
                        child: Container(
                          width: 120 + 140 * _burst.value,
                          height: 120 + 140 * _burst.value,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            border: Border.all(
                              color: colors.brandDefault.withValues(alpha: 0.65),
                              width: 2,
                            ),
                          ),
                        ),
                      ),
                      // 粒子飘散(自绘,固定随机种子)
                      Positioned.fill(
                        child: CustomPaint(
                          painter: MatchParticlesPainter(
                            progress: _particles.value,
                            colors: colors,
                          ),
                        ),
                      ),
                      // 双头像相向滑入(定格圆心间距 66)
                      Transform.translate(
                        offset: Offset(-33 - 56 * (1 - _avatars.value), 0),
                        child: EmberAvatar(
                          key: const Key('match.myAvatar'),
                          image: _networkImage(widget.myAvatarUrl),
                          size: EmberComponentSizes.avatarHero,
                          isNewMatch: true,
                          semanticLabel: '我的头像',
                        ),
                      ),
                      Transform.translate(
                        offset: Offset(33 + 56 * (1 - _avatars.value), 0),
                        child: EmberAvatar(
                          key: const Key('match.theirAvatar'),
                          image: _networkImage(theirAvatarUrl),
                          name: widget.candidate.nickname,
                          size: EmberComponentSizes.avatarHero,
                          isNewMatch: true,
                          semanticLabel: '${widget.candidate.nickname}的头像',
                        ),
                      ),
                      // 心形弹出(0.6 → 1,弹簧自带过冲)
                      Transform.scale(
                        scale: (0.6 + 0.4 * _heart.value).clamp(0, 2),
                        child: Icon(
                          PhosphorIconsFill.heart,
                          size: 30,
                          color: colors.brandDefault,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              Align(
                alignment: Alignment.bottomCenter,
                child: Padding(
                  padding: EdgeInsets.fromLTRB(
                    tokens.space24,
                    0,
                    tokens.space24,
                    tokens.space40,
                  ),
                  child: Opacity(
                    opacity: _text.value.clamp(0, 1),
                    child: Transform.translate(
                      offset: Offset(0, 8 * (1 - _text.value)),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            '你们已互相喜欢',
                            // `title` 24 / Fraunces(§4.2 弹层标题档)。
                            style: AppText.title.copyWith(color: Colors.white),
                          ),
                          SizedBox(height: tokens.space8),
                          Text(
                            '和 ${widget.candidate.nickname} 打个招呼吧',
                            style: AppText.caption.copyWith(
                              color: Colors.white.withValues(alpha: 0.72),
                            ),
                          ),
                          if (icebreaker != null) ...[
                            SizedBox(height: tokens.space8),
                            Text(
                              icebreaker,
                              key: const Key('match.icebreaker'),
                              textAlign: TextAlign.center,
                              style: AppText.caption.copyWith(
                                color: Colors.white.withValues(alpha: 0.92),
                              ),
                            ),
                          ],
                          SizedBox(height: tokens.space24),
                          Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              if (widget.onGoChat != null) ...[
                                EmberButton(
                                  key: const Key('match.goChat'),
                                  label: '去聊天',
                                  onPressed: widget.onGoChat,
                                ),
                                SizedBox(width: tokens.space12),
                              ],
                              EmberButton(
                                key: const Key('match.continue'),
                                label: '继续滑卡',
                                variant: EmberButtonVariant.secondary,
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

  /// 空串 / null 不建 `NetworkImage`(否则会去请求一个空 URL)。
  ImageProvider? _networkImage(String? url) =>
      (url == null || url.isEmpty) ? null : NetworkImage(url);
}

/// 弹配对动效;等它关闭后 future 才完成。
///
/// 参数说明:
/// - [context] 用于取主题与 Navigator。
/// - [candidate] 刚配上的人。
/// - [myAvatarUrl] 我的头像;`null` 时两边头像都走首字占位。
/// - [sharedTags] / [myCity] 只用于「配对那一刻」的破冰文案,拿不到就都不传。
/// - [onGoChat] 有值才出现「去聊天」。
Future<void> showMatchOverlay(
  BuildContext context, {
  required Candidate candidate,
  String? myAvatarUrl,
  List<Tag> sharedTags = const [],
  String myCity = '',
  VoidCallback? onGoChat,
}) {
  final colors = context.ember;
  return showGeneralDialog<void>(
    context: context,
    barrierDismissible: false,
    barrierLabel: '配对成功',
    // 遮罩用 `overlay.scrim`(§8.3):暖黑,不压成纯黑。
    barrierColor: colors.overlayScrim,
    // 弹层淡入不参与编排时间轴,给一个短时长;减弱动态效果时压到 120ms。
    transitionDuration: EmberMotion.transitionOf(
      context,
      const Duration(milliseconds: 220),
    ),
    pageBuilder: (dialogContext, animation, secondary) => MatchOverlay(
      candidate: candidate,
      myAvatarUrl: myAvatarUrl,
      sharedTags: sharedTags,
      myCity: myCity,
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
}
