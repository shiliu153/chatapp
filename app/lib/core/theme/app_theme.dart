import 'package:flutter/material.dart';

import 'app_typography.dart';
import 'tokens.g.dart' as tokens;
import 'ember_colors.dart';

/// 组装全局主题(spec §3 色彩 + §5 形状 + §8 组件基线)。
///
/// [brightness] 必填:暗色之后主题不是单例,调用方必须明确要哪一套,免得漏传时
/// 静默拿到浅色、深色页面上冒出白块。
///
/// **禁止 `ColorScheme.fromSeed`**(spec §8 / 工单 E-2):种子算法会派生出一整套
/// 规范里没有的颜色,`primary` 也不是 `brand.default` 原值。这里逐槽位用 §3.3 的
/// token 填,填不满的槽位(如 `primaryFixed`)保持 Material 默认,组件层不应依赖它们。
ThemeData buildAppTheme({required Brightness brightness}) {
  final colors = EmberColors.of(brightness);
  final scheme = ColorScheme(
    brightness: brightness,
    primary: colors.brandDefault,
    onPrimary: colors.brandOn,
    primaryContainer: colors.surfaceSunken,
    onPrimaryContainer: colors.textPrimary,
    secondary: colors.accentDefault,
    onSecondary: colors.accentOn,
    secondaryContainer: colors.surfaceSunken,
    onSecondaryContainer: colors.textPrimary,
    tertiary: colors.statusInfo,
    // status.info 没有配套的 on 色(§3.3 只给了 fg 一个值);取 brandOn 是因为
    // 它在两个模式下都满足「浅底深字 / 深底白字」的对比度方向。
    onTertiary: colors.brandOn,
    error: colors.statusDanger,
    onError: colors.statusOnDanger,
    errorContainer: colors.surfaceSunken,
    onErrorContainer: colors.statusDanger,
    surface: colors.surfaceCard,
    onSurface: colors.textPrimary,
    surfaceDim: colors.surfacePage,
    surfaceBright: colors.surfaceCard,
    surfaceContainerLowest: colors.surfacePage,
    surfaceContainerLow: colors.surfaceSunken,
    surfaceContainer: colors.surfaceCard,
    surfaceContainerHigh: colors.surfaceCard,
    surfaceContainerHighest: colors.surfaceSunken,
    onSurfaceVariant: colors.textSecondary,
    outline: colors.borderStrong,
    outlineVariant: colors.borderDivider,
    shadow: colors.overlayScrim,
    scrim: colors.overlayScrim,
    inverseSurface: colors.textPrimary,
    onInverseSurface: colors.surfaceCard,
    inversePrimary: colors.brandDefault,
    surfaceTint: colors.brandDefault,
  );

  final base = ThemeData(
    colorScheme: scheme,
    useMaterial3: true,
    // 全局字族 = token `font.family.body`(系统无衬线链):Flutter 的 `fontFamily` 只认单个
    // 名字,所以主字族留空(平台默认 SF / Roboto),中文按 token 顺序落到系统字族。
    // 标题档的 Fraunces 是**组件级**取值(见 `AppText.display` / `AppText.title`)——
    // 规范 §4.1 只让它服务 display / title 两档,不设成全局字族。
    fontFamilyFallback: kBodyFontFallback,
    extensions: [colors],
  );

  return base.copyWith(
    scaffoldBackgroundColor: colors.surfacePage,
    canvasColor: colors.surfacePage,
    dividerColor: colors.borderDivider,
    splashFactory: InkSparkle.splashFactory,
    textSelectionTheme: TextSelectionThemeData(
      cursorColor: colors.brandDefault,
      selectionColor: colors.brandDefault.withValues(alpha: 0.24),
      selectionHandleColor: colors.brandDefault,
    ),
    progressIndicatorTheme: ProgressIndicatorThemeData(
      color: colors.brandDefault,
    ),
    // §8.2 Toast / 浮层口径:`overlay.scrim` 底 + 白字 13。
    // 底色单点维护在这里,组件(AppToast / EmberToast)都从 snackBarTheme 取,
    // 避免各自再写一份半透明黑。
    snackBarTheme: SnackBarThemeData(
      backgroundColor: colors.overlayScrim,
      contentTextStyle: AppText.caption.copyWith(color: Colors.white),
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(tokens.radiusMd)),
    ),
  );
}
