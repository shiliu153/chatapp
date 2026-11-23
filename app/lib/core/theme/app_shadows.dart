import 'package:flutter/material.dart';

import 'tokens.g.dart' as tokens;

/// 层级阴影:值来自生成物里的 `elevation.1` / `elevation.2`(spec §5.3)。
///
/// 为什么要在运行时解析:生成物把阴影存成 CSS 影子串(`0 2px 8px rgba(28,23,20,0.06)`),
/// 这是 Web 侧直接可用的形态;Flutter 侧需要的 [BoxShadow] 只能由它折算出来。
/// **不要在组件里另写一份 rgba** —— 那样又变成两处事实来源,而 §5.3 的暖色
/// (`28,23,20`)正是 Ember 与心跳的差异点之一。
///
/// 深色模式**不用阴影**(§5.3):深底上阴影不可见,靠 `border.divider` + 表面色差分层。
/// 组件层用 `Theme.of(context).brightness` 判断,不要两模式套同一套 boxShadow。
abstract final class AppShadows {
  /// 卡片层级(spec `elevation.1`)。
  static final List<BoxShadow> card = [parse(tokens.elevation1)];

  /// 浮层层级(底栏、sheet、浮卡,spec `elevation.2`)。
  static final List<BoxShadow> floatingBar = [parse(tokens.elevation2)];

  /// 主按钮的 `emberGlow`(spec §2「品牌签名元素」/ §18.6 `--focus-glow`)。
  ///
  /// 规范里它是**径向光晕**而不是投影,所以用零位移 + 较小透明度实现;规范只给了
  /// 「brand @12%」这一条口径(§18.6),没有把 alpha 做成 token,由组件层按该口径算。
  static List<BoxShadow> primaryGlow(Color brand) => [
        BoxShadow(
          color: brand.withValues(alpha: 0.12),
          blurRadius: 24,
          spreadRadius: 2,
        ),
      ];

  /// 把生成物的 CSS 影子串解析成 [BoxShadow]。
  ///
  /// 解析失败**直接抛 [StateError]**:静默回退成「没有阴影」会让层级悄悄消失,
  /// 比启动就炸更难查。`test/core/theme/app_shadows_test.dart` 用生成物里的真实值
  /// 覆盖这条路径。
  static BoxShadow parse(String spec) {
    final match = RegExp(
      // CSS 阴影串里第一段可以省略单位(`0 2px 8px rgba(...)`),所以 px 是可选的。
      r'^\s*(-?[\d.]+)(?:px)?\s+(-?[\d.]+)(?:px)?\s+([\d.]+)(?:px)?\s+'
      r'rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)\s*$',
    ).firstMatch(spec);
    if (match == null) {
      throw StateError('tokens.g.dart 的阴影串格式变了,无法解析:$spec');
    }
    String group(int index) => match.group(index)!;
    int channel(int index) => int.parse(group(index));
    return BoxShadow(
      color: Color.fromRGBO(
        channel(4),
        channel(5),
        channel(6),
        double.parse(group(7)),
      ),
      offset: Offset(double.parse(group(1)), double.parse(group(2))),
      blurRadius: double.parse(group(3)),
    );
  }
}
