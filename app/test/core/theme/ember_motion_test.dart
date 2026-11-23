import 'dart:math' as math;

import 'package:flutter/physics.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_motion.dart';
import 'package:chatapp_app/core/theme/ember_motion.dart';
import 'package:chatapp_app/core/theme/tokens.g.dart' as tokens;

/// `SpringDescription` 只暴露阻尼系数,这里按 `c = 2ζ√(km)` 反算回阻尼比。
double _ratio(SpringDescription spring) =>
    spring.damping / (2 * math.sqrt(spring.mass * spring.stiffness));

void main() {
  test('四套 spring 的阻尼比 / 刚度就是 §7.1 的 token 值', () {
    // SpringDescription.withDampingRatio 会把 ratio 折成阻尼系数,这里反算回去,
    // 保证「组件层没有把 damping 当刚度用」这类低级错误能被抓住。
    expect(_ratio(EmberMotion.fast), closeTo(tokens.motionSpringFastDamping, 1e-9));
    expect(EmberMotion.fast.stiffness, tokens.motionSpringFastStiffness);
    expect(
      _ratio(EmberMotion.standard),
      closeTo(tokens.motionSpringStandardDamping, 1e-9),
    );
    expect(EmberMotion.standard.stiffness, tokens.motionSpringStandardStiffness);
    expect(
      _ratio(EmberMotion.gentle),
      closeTo(tokens.motionSpringGentleDamping, 1e-9),
    );
    expect(EmberMotion.gentle.stiffness, tokens.motionSpringGentleStiffness);
    expect(
      _ratio(EmberMotion.effects),
      closeTo(tokens.motionSpringEffectsDamping, 1e-9),
    );
    expect(EmberMotion.effects.stiffness, tokens.motionSpringEffectsStiffness);
  });

  test('减弱动态效果统一 120ms(§7.3 / motion.reducedDurationMs)', () {
    expect(EmberMotion.reduced, const Duration(milliseconds: 120));
  });

  test('骨架 / 呼吸的循环周期是 1.2s(§8.3)', () {
    expect(EmberMotion.loop, const Duration(milliseconds: 1200));
  });

  test('心跳期 duration 常量仍在(E-5 逐页删除),与 spring 无一一对应', () {
    // 这条用例是「过渡期双轨」的显式记录:旧 AppMotion 还在被存量页面消费,
    // E-5 迁移后本用例与 app_motion.dart 一起删。
    expect(AppMotion.fast.inMilliseconds, 150);
  });
}
