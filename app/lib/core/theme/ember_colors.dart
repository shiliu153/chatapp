import 'package:flutter/material.dart';

import 'tokens.g.dart' as tokens;

/// 「余烬 Ember」语义色板:spec §3.3 的二十项语义角色,值**全部来自生成物**
/// `tokens.g.dart`(唯一事实来源是 `design/tokens/*.json`)。
///
/// 三条纪律,都有机械判据兜住(见 `test/core/theme/`):
/// 1. 本文件**不写任何色值字面量** —— 要改色就改 `design/tokens/*.json`,
///    再跑 `python scripts/design_tokens.py --write`;手改生成物会被门禁判红。
/// 2. 浅/深两套**键集必须一致**(生成器已 fail-closed):少一个深色值,该元素在
///    深色模式下会静默回落到浅色值。
/// 3. 取色一律走 `context.ember`(`ember_theme_context.dart`),**不能用在 const
///    表达式里** —— 本类是 ThemeExtension,值随当前主题变化。
///
/// 为什么不用 `ColorScheme.fromSeed`:种子算法会派生出一整套规范里没有的颜色
/// (spec §8 明令禁止),这里的每个槽位都必须是 §3.3 表里点得出的 token。
@immutable
class EmberColors extends ThemeExtension<EmberColors> {
  const EmberColors({
    required this.surfacePage,
    required this.surfaceCard,
    required this.surfaceSunken,
    required this.textPrimary,
    required this.textSecondary,
    required this.textTertiary,
    required this.borderDivider,
    required this.borderStrong,
    required this.brandDefault,
    required this.brandOn,
    required this.accentDefault,
    required this.accentOn,
    required this.statusDanger,
    required this.statusOnDanger,
    required this.statusSuccess,
    required this.statusOnSuccess,
    required this.statusWarning,
    required this.statusOnWarning,
    required this.statusInfo,
    required this.overlayScrim,
  });

  /// 页面底(spec §3.3 `surface.page`)。
  final Color surfacePage;

  /// 卡片 / 列表行 / sheet 底(`surface.card`)。
  final Color surfaceCard;

  /// 凹陷区、输入底、骨架底色(`surface.sunken`)。
  final Color surfaceSunken;

  /// 正文、标题(`text.primary`)。
  final Color textPrimary;

  /// 次级信息、说明(`text.secondary`)。
  final Color textSecondary;

  /// 时间戳、占位、禁用文字(`text.tertiary`)。
  final Color textTertiary;

  /// 分割线、描边(`border.divider`)。
  final Color borderDivider;

  /// 需要明确边界的容器(`border.strong`)。
  final Color borderStrong;

  /// 主按钮底、强调文字、未读(`brand.default`)。
  final Color brandDefault;

  /// 主色底上的文字(`brand.on`;深色模式是近黑,不是白)。
  final Color brandOn;

  /// 次强调、精选标识(`accent.default`)。
  final Color accentDefault;

  /// 次强调底上的文字(`accent.on`)。
  final Color accentOn;

  /// 错误、删除(`status.danger`)。
  final Color statusDanger;

  /// 危险底上的文字(`status.onDanger`)。
  final Color statusOnDanger;

  /// 成功、在线点(`status.success`)。
  final Color statusSuccess;

  /// 成功底上的文字(`status.onSuccess`)。
  final Color statusOnSuccess;

  /// 预警、会员(`status.warning`)。
  final Color statusWarning;

  /// 警告底上的文字(`status.onWarning`)。
  final Color statusOnWarning;

  /// 系统通知、官方标识(`status.info`)。
  final Color statusInfo;

  /// Toast / 遮罩(`overlay.scrim`,已带 92% 透明度)。
  final Color overlayScrim;

  /// 浅色板(spec §3.3 的 Light 列)。
  static const light = EmberColors(
    surfacePage: tokens.colorSurfacePageLight,
    surfaceCard: tokens.colorSurfaceCardLight,
    surfaceSunken: tokens.colorSurfaceSunkenLight,
    textPrimary: tokens.colorTextPrimaryLight,
    textSecondary: tokens.colorTextSecondaryLight,
    textTertiary: tokens.colorTextTertiaryLight,
    borderDivider: tokens.colorBorderDividerLight,
    borderStrong: tokens.colorBorderStrongLight,
    brandDefault: tokens.colorBrandDefaultLight,
    brandOn: tokens.colorBrandOnLight,
    accentDefault: tokens.colorAccentDefaultLight,
    accentOn: tokens.colorAccentOnLight,
    statusDanger: tokens.colorStatusDangerLight,
    statusOnDanger: tokens.colorStatusOnDangerLight,
    statusSuccess: tokens.colorStatusSuccessLight,
    statusOnSuccess: tokens.colorStatusOnSuccessLight,
    statusWarning: tokens.colorStatusWarningLight,
    statusOnWarning: tokens.colorStatusOnWarningLight,
    statusInfo: tokens.colorStatusInfoLight,
    overlayScrim: tokens.colorOverlayScrimLight,
  );

  /// 深色板(spec §3.3 的 Dark 列)。
  ///
  /// 注意两处直觉会错的地方(§3.4):主按钮在深色下是**亮底 + 近黑文字**,
  /// 次级灰比想象中亮得多 —— 这两条都体现在 token 值里,不要在组件里自己调。
  static const dark = EmberColors(
    surfacePage: tokens.colorSurfacePageDark,
    surfaceCard: tokens.colorSurfaceCardDark,
    surfaceSunken: tokens.colorSurfaceSunkenDark,
    textPrimary: tokens.colorTextPrimaryDark,
    textSecondary: tokens.colorTextSecondaryDark,
    textTertiary: tokens.colorTextTertiaryDark,
    borderDivider: tokens.colorBorderDividerDark,
    borderStrong: tokens.colorBorderStrongDark,
    brandDefault: tokens.colorBrandDefaultDark,
    brandOn: tokens.colorBrandOnDark,
    accentDefault: tokens.colorAccentDefaultDark,
    accentOn: tokens.colorAccentOnDark,
    statusDanger: tokens.colorStatusDangerDark,
    statusOnDanger: tokens.colorStatusOnDangerDark,
    statusSuccess: tokens.colorStatusSuccessDark,
    statusOnSuccess: tokens.colorStatusOnSuccessDark,
    statusWarning: tokens.colorStatusWarningDark,
    statusOnWarning: tokens.colorStatusOnWarningDark,
    statusInfo: tokens.colorStatusInfoDark,
    overlayScrim: tokens.colorOverlayScrimDark,
  );

  /// 按亮度取板。测试与 `buildAppTheme` 共用,避免两处各写一遍三元表达式。
  static EmberColors of(Brightness brightness) =>
      brightness == Brightness.dark ? dark : light;

  // ---------------------------------------------------------------------------
  // 过渡别名:心跳期字段名 → Ember 语义角色(对照表见 spec §18.2)。
  //
  // E-2 只换底座、不迁移页面,存量页面(80+ 文件、500+ 处)仍按旧名取色,所以这里
  // 把旧名指到新值上。**它不是第二份色值**:每个别名都只读上面的语义字段,改 token
  // 仍然只改一处。E-5 逐页迁移完成后整段删除(届时
  // `test/core/theme/ember_colors_test.dart` 的「过渡别名表」用例一并删)。
  // ---------------------------------------------------------------------------

  /// 过渡别名 → [surfacePage]。
  Color get bgPage => surfacePage;

  /// 过渡别名 → [surfaceCard]。
  Color get bgCard => surfaceCard;

  /// 过渡别名 → [borderDivider]。
  Color get divider => borderDivider;

  /// 过渡别名 → [textPrimary]。
  Color get text1 => textPrimary;

  /// 过渡别名 → [textSecondary]。
  Color get text2 => textSecondary;

  /// 过渡别名 → [textTertiary]。
  Color get text3 => textTertiary;

  /// 过渡别名 → [brandDefault]。
  Color get brand => brandDefault;

  /// 过渡别名 → [accentDefault]。
  ///
  /// 心跳期的 `heartOrange` 只服务渐变终点;spec §18.2 的口径是「删除,需要第二个
  /// 暖色强调时用 `accent.default`」,所以这里指向 accent 而不是造一个新色。
  Color get heartOrange => accentDefault;

  /// 过渡别名 → [statusInfo]。
  ///
  /// 心跳期的 `violet` 只服务「系统」渐变起点;§18.2 把系统 / 官方标识统一到
  /// `status.info` 单色。
  Color get violet => statusInfo;

  /// 过渡别名 → [statusInfo](与 [violet] 同源:系统色合并为单色)。
  Color get systemBlue => statusInfo;

  /// 过渡别名 → [statusSuccess]。
  Color get green => statusSuccess;

  /// 过渡别名 → [statusWarning]。
  Color get amber => statusWarning;

  /// 过渡别名 → [statusDanger]。
  Color get danger => statusDanger;

  /// 过渡别名 → [overlayScrim]。
  Color get photoScrim => overlayScrim;

  /// 过渡别名 → [statusSuccess](心跳期 `success` 是 `green` 的别名)。
  Color get success => statusSuccess;

  /// 过渡别名 → [statusWarning](心跳期 `warning` 是 `amber` 的别名)。
  Color get warning => statusWarning;

  /// 语义字段名 → 色值。给「两套字段齐全 / 来自生成物」的断言用
  /// (不能用 dart:mirrors,所以手写一份;漏字段会被测试的字面量数量断言抓住)。
  Map<String, Color> toMap() => {
        'surfacePage': surfacePage,
        'surfaceCard': surfaceCard,
        'surfaceSunken': surfaceSunken,
        'textPrimary': textPrimary,
        'textSecondary': textSecondary,
        'textTertiary': textTertiary,
        'borderDivider': borderDivider,
        'borderStrong': borderStrong,
        'brandDefault': brandDefault,
        'brandOn': brandOn,
        'accentDefault': accentDefault,
        'accentOn': accentOn,
        'statusDanger': statusDanger,
        'statusOnDanger': statusOnDanger,
        'statusSuccess': statusSuccess,
        'statusOnSuccess': statusOnSuccess,
        'statusWarning': statusWarning,
        'statusOnWarning': statusOnWarning,
        'statusInfo': statusInfo,
        'overlayScrim': overlayScrim,
      };

  @override
  EmberColors copyWith({
    Color? surfacePage,
    Color? surfaceCard,
    Color? surfaceSunken,
    Color? textPrimary,
    Color? textSecondary,
    Color? textTertiary,
    Color? borderDivider,
    Color? borderStrong,
    Color? brandDefault,
    Color? brandOn,
    Color? accentDefault,
    Color? accentOn,
    Color? statusDanger,
    Color? statusOnDanger,
    Color? statusSuccess,
    Color? statusOnSuccess,
    Color? statusWarning,
    Color? statusOnWarning,
    Color? statusInfo,
    Color? overlayScrim,
  }) {
    return EmberColors(
      surfacePage: surfacePage ?? this.surfacePage,
      surfaceCard: surfaceCard ?? this.surfaceCard,
      surfaceSunken: surfaceSunken ?? this.surfaceSunken,
      textPrimary: textPrimary ?? this.textPrimary,
      textSecondary: textSecondary ?? this.textSecondary,
      textTertiary: textTertiary ?? this.textTertiary,
      borderDivider: borderDivider ?? this.borderDivider,
      borderStrong: borderStrong ?? this.borderStrong,
      brandDefault: brandDefault ?? this.brandDefault,
      brandOn: brandOn ?? this.brandOn,
      accentDefault: accentDefault ?? this.accentDefault,
      accentOn: accentOn ?? this.accentOn,
      statusDanger: statusDanger ?? this.statusDanger,
      statusOnDanger: statusOnDanger ?? this.statusOnDanger,
      statusSuccess: statusSuccess ?? this.statusSuccess,
      statusOnSuccess: statusOnSuccess ?? this.statusOnSuccess,
      statusWarning: statusWarning ?? this.statusWarning,
      statusOnWarning: statusOnWarning ?? this.statusOnWarning,
      statusInfo: statusInfo ?? this.statusInfo,
      overlayScrim: overlayScrim ?? this.overlayScrim,
    );
  }

  /// 主题切换动画用:逐通道插值。`other == null` 时按官方约定返回自身。
  @override
  EmberColors lerp(ThemeExtension<EmberColors>? other, double t) {
    if (other is! EmberColors) return this;
    Color mix(Color a, Color b) => Color.lerp(a, b, t)!;
    return EmberColors(
      surfacePage: mix(surfacePage, other.surfacePage),
      surfaceCard: mix(surfaceCard, other.surfaceCard),
      surfaceSunken: mix(surfaceSunken, other.surfaceSunken),
      textPrimary: mix(textPrimary, other.textPrimary),
      textSecondary: mix(textSecondary, other.textSecondary),
      textTertiary: mix(textTertiary, other.textTertiary),
      borderDivider: mix(borderDivider, other.borderDivider),
      borderStrong: mix(borderStrong, other.borderStrong),
      brandDefault: mix(brandDefault, other.brandDefault),
      brandOn: mix(brandOn, other.brandOn),
      accentDefault: mix(accentDefault, other.accentDefault),
      accentOn: mix(accentOn, other.accentOn),
      statusDanger: mix(statusDanger, other.statusDanger),
      statusOnDanger: mix(statusOnDanger, other.statusOnDanger),
      statusSuccess: mix(statusSuccess, other.statusSuccess),
      statusOnSuccess: mix(statusOnSuccess, other.statusOnSuccess),
      statusWarning: mix(statusWarning, other.statusWarning),
      statusOnWarning: mix(statusOnWarning, other.statusOnWarning),
      statusInfo: mix(statusInfo, other.statusInfo),
      overlayScrim: mix(overlayScrim, other.overlayScrim),
    );
  }
}
