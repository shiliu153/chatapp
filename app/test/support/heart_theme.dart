import 'package:flutter/material.dart';

import 'package:chatapp_app/core/theme/app_theme.dart';

/// 单组件测试的默认主题。
///
/// F 批之后组件取色走 `context.heart`(ThemeExtension),裸 `MaterialApp()` 里
/// 没有注册扩展,`HeartThemeX.heart` 的 debug 断言会直接炸。所以凡是 pump 组件
/// 的用例都要把 `theme:` 传成它。
ThemeData get heartTheme => buildAppTheme(brightness: Brightness.light);

/// 暗色主题(暗色专项用例用)。
ThemeData get heartThemeDark => buildAppTheme(brightness: Brightness.dark);
