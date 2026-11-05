import 'package:flutter/material.dart';

import 'heart_colors.dart';

/// 取「心跳」语义色的短写法:比 `Theme.of(context).extension<HeartColors>()!` 短,
/// 且漏注册主题时会在 debug 下直接断言报错,而不是运行时崩在 null 上。
///
/// ```dart
/// @override
/// Widget build(BuildContext context) {
///   final colors = context.heart; // 必须在 build 内取:它不是 const
///   return Container(color: colors.bgCard);
/// }
/// ```
extension HeartThemeX on BuildContext {
  /// 当前主题下的语义色板。**不能出现在 const 表达式里**。
  HeartColors get heart {
    final ext = Theme.of(this).extension<HeartColors>();
    assert(
      ext != null,
      'HeartColors 未注册到 ThemeData.extensions —— 检查 buildAppTheme 是否传了 extensions',
    );
    // assert 在 release 下不生效,兜底回浅色板,避免暗色漏配直接白屏。
    return ext ?? HeartColors.light;
  }
}
