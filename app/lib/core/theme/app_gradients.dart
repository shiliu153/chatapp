import 'package:flutter/material.dart';

import 'ember_colors.dart';

/// 心跳期渐变的**过渡实现**:颜色改为从 [EmberColors] 取,不再是手写常量。
///
/// spec §18.1 #2 规定「渐变全部取消,主色改实色」,所以这里保留三个构造函数的唯一
/// 目的是让存量页面继续编译与显示,E-5 逐页迁移时逐个删除:
/// - [heartOf]:粉橙渐变 → 现在是 `brand.default → accent.default` 的暖色渐变;
/// - [systemOf]:紫蓝渐变 → 「系统 / 官方」在 §18.2 里合并成 `status.info` **单色**,
///   所以两端取同一个色值(渲染成实色,不再有色相过渡);
/// - [heartSweepOf]:完成度环的进度弧,与 [heartOf] 同色。
abstract final class AppGradients {
  /// 主题感知的「心跳」渐变(旧:粉→橙;现:朱砂→琥珀)。
  static LinearGradient heartOf(EmberColors colors) => LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [colors.brandDefault, colors.accentDefault],
      );

  /// 主题感知的「系统」渐变。§18.2:系统 / 官方统一 `status.info` 单色,
  /// 两端同值即为实色(保留函数是为了让存量页面不改调用)。
  static LinearGradient systemOf(EmberColors colors) => LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [colors.statusInfo, colors.statusInfo],
      );

  /// 主题感知的完成度环进度弧(沿圆周扫过)。
  static SweepGradient heartSweepOf(EmberColors colors) => SweepGradient(
        colors: [colors.brandDefault, colors.accentDefault],
      );
}
