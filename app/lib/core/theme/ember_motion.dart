import 'package:flutter/material.dart';

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
