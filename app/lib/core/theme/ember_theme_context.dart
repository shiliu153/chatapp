import 'package:flutter/material.dart';

import 'ember_colors.dart';

/// 取语义色板的短写法:比 `Theme.of(context).extension<EmberColors>()!` 短,
/// 且漏注册主题时会在 debug 下直接断言报错,而不是运行时崩在 null 上。
///
/// ```dart
/// @override
/// Widget build(BuildContext context) {
///   final colors = context.ember; // 必须在 build 内取:它不是 const
///   return ColoredBox(color: colors.surfaceCard);
/// }
/// ```
extension EmberThemeX on BuildContext {
  /// 当前主题的语义色板。**不能出现在 const 表达式里**。
  EmberColors get ember {
    final ext = Theme.of(this).extension<EmberColors>();
    assert(
      ext != null,
      'EmberColors 未注册到 ThemeData.extensions —— 检查 buildAppTheme 是否传了 extensions',
    );
    // assert 在 release 下不生效,兜底回浅色板,避免漏配时直接白屏。
    return ext ?? EmberColors.light;
  }

  /// 过渡别名:E-2 只换底座,**存量页面**仍写 `context.heart`(E-5 逐页迁移时换掉)。
  ///
  /// 与 [ember] 是同一块色板,不是第二份实现;文件名 `heart_theme_context.dart`
  /// 也只为让存量页面不必改 import 路径。
  EmberColors get heart => ember;
}
