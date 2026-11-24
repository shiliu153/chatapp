import 'package:flutter/material.dart';
import 'package:flutter/physics.dart';

import 'tokens.g.dart' as tokens;

/// 「余烬 Ember」动效基座:spec §7.1 的 spring 复合 token(damping / stiffness 成对)。
///
/// 为什么不用 duration + curve:滑卡、拖拽面板这类手势会被打断,curve 动画每次
/// 重启动都会「跳一下」;弹簧能按当前位置续接(§7 的立项理由)。
///
/// 换算关系:`SpringDescription.withDampingRatio(stiffness: k, ratio: ζ)` 等价于
/// 「单位质量 + 阻尼系数 `c = 2ζ√k`」,这正是 M3 Expressive 那套 token 的物理含义,
/// 所以 token 里的 damping 直接当 **阻尼比** 用,不需要再拍一个质量参数。
abstract final class EmberMotion {
  /// 按压、开关、chip 选中(spec `spring.fast`)。
  static final SpringDescription fast = _spring(
    tokens.motionSpringFastDamping,
    tokens.motionSpringFastStiffness,
  );

  /// 页面切换、展开收起、列表入场(spec `spring.standard`)。
  static final SpringDescription standard = _spring(
    tokens.motionSpringStandardDamping,
    tokens.motionSpringStandardStiffness,
  );

  /// 大卡片、sheet 上浮、头像环(spec `spring.gentle`)。
  static final SpringDescription gentle = _spring(
    tokens.motionSpringGentleDamping,
    tokens.motionSpringGentleStiffness,
  );

  /// 纯透明度 / 颜色过渡(无位移,spec `spring.effects`)。
  static final SpringDescription effects = _spring(
    tokens.motionSpringEffectsDamping,
    tokens.motionSpringEffectsStiffness,
  );

  /// 减弱动态效果时的统一淡入时长(spec §7.3 / `motion.reducedDurationMs` = 120ms)。
  static Duration get reduced => _ms(tokens.motionReducedDurationMs);

  /// 骨架屏 / 呼吸点的循环周期:spec §8.2 给的是 **1.2s**,而固定值本身没有对应的
  /// 尺度 token(它是「循环」而不是「过渡」),所以在动效基座里单点声明一次,
  /// 组件不要各自写 1200。
  static const Duration loop = Duration(milliseconds: 1200);

  /// 当前环境是否要求减弱动态效果(spec §7.3 / §8.4)。
  ///
  /// 真机上由系统「移除动画」开关驱动;测试里可用 `MediaQuery` 的
  /// `disableAnimations` 直接构造这一场景。
  static bool reducedOf(BuildContext context) =>
      // 用 maybe 版本:手势回调里 context 可能已经 deactivate(组件被替换/销毁),
      // 强断言版本会在那种瞬间抛「deactivated widget」而不是安静地取不到值。
      MediaQuery.maybeDisableAnimationsOf(context) ?? false;

  /// 按「有没有减弱动态效果」二选一:[spring] 场景返回 null 表示「直接用终态」,
  /// 由调用方改成 [reduced] 的线性淡入。
  static Duration transitionOf(BuildContext context, Duration normal) =>
      reducedOf(context) ? reduced : normal;

  /// 把 spring 表达成 [Curve](`t` 0→1 摊到 [settle] 那条时间轴上)。
  ///
  /// **只给分段编排用**:配对成功这类「几段压在同一条总时间轴」的动效,段落是
  /// `Interval` 切的,而 `Interval` 只能吃 [Curve] —— 直接写 `Curves.*` 等于把曲线
  /// 常量偷偷带回来(spec §7.1「位移类动画一律用 spring,不用 Curves」)。用弹簧曲线
  /// 当段落缓动,手感与逐段 `SpringSimulation` 同源,又不破坏「一条时间轴可跳过」。
  ///
  /// 返回值**可能过冲**(>1 / <0),透明度类用途要自己 clamp:
  /// ```dart
  /// opacity: EmberMotion.gentleCurve.transform(t).clamp(0, 1)
  /// ```
  static Curve springCurve(
    SpringDescription spring, {
    Duration settle = const Duration(milliseconds: 900),
  }) =>
      EmberSpringCurve(spring, settle);

  /// 分段编排默认用的 `spring.gentle` 曲线(大卡片、情感时刻)。
  static Curve get gentleCurve => springCurve(gentle);

  /// token 里的毫秒是 `double`(生成器统一按数值档输出),这里折成 [Duration],
  /// 顺带保证不会因为截断丢掉小数毫秒。
  static Duration _ms(double milliseconds) =>
      Duration(microseconds: (milliseconds * 1000).round());

  /// 阻尼比 + 刚度 → [SpringDescription](单位质量)。
  static SpringDescription _spring(double dampingRatio, double stiffness) =>
      SpringDescription.withDampingRatio(
        mass: 1,
        stiffness: stiffness,
        ratio: dampingRatio,
      );
}

/// 用 [SpringSimulation] 采样出来的 [Curve](见 [EmberMotion.springCurve])。
///
/// 为什么不用 `Curve` 的固定公式:token 里的弹簧是「阻尼比 + 刚度」两个数,采样
/// 弹簧本身才能保证与按压 / 位移那些 `SpringSimulation` 走同一套物理参数。
class EmberSpringCurve extends Curve {
  /// 构造一条弹簧曲线。
  const EmberSpringCurve(this.spring, this.settle);

  /// 弹簧参数(`spring.fast` / `standard` / `gentle` / `effects`)。
  final SpringDescription spring;

  /// `t = 1` 对应的物理时间:取到弹簧基本收敛的长度(默认 900ms)。
  final Duration settle;

  @override
  double transformInternal(double t) {
    if (t <= 0) return 0;
    final seconds = settle.inMicroseconds * t / Duration.microsecondsPerSecond;
    // 初始速度 0、位移 0→1:这是「松开手之后自己走完」的那条轨迹。
    return SpringSimulation(spring, 0, 1, 0).x(seconds);
  }
}
