import 'package:flutter/material.dart';

import 'app_colors.dart';

/// 深色语义色板(计划 F-1 / spec §2.1.1 的「深色(新增)」列)。
///
/// 单独成类而不是内联进 [HeartColors.dark] 的原因:`web/tests/unit/tokens.spec.ts`
/// 用正则解析 `static const name = Color(0xAARRGGBB);` 与 `[data-theme="dark"]`
/// 双向比对,写在内联构造参数里就解析不到,暗色漏改也抓不住。
abstract final class HeartDarkColors {
  static const bgPage = Color(0xFF0E1015);
  static const bgCard = Color(0xFF171A21);
  static const divider = Color(0xFF262A33);
  static const text1 = Color(0xFFF2F4F8);
  static const text2 = Color(0xFF9BA1AE);
  static const text3 = Color(0xFF6E7482);
  static const brand = Color(0xFFFF2C55); // 品牌色不变:心跳渐变是视觉锚点
  static const heartOrange = Color(0xFFFF8A5B); // 暗底提亮
  static const violet = Color(0xFF8E72FF);
  static const systemBlue = Color(0xFF6AA0FF);
  static const green = Color(0xFF22D89B);
  static const amber = Color(0xFFFFC04D);
  static const danger = Color(0xFFFF6B6B);
  static const photoScrim = Color(0xDE101114); // 照片叠字场景本身就是深色,不变
}

/// 「心跳」语义色的主题载体(spec §2.1)。
///
/// [AppColors] 是 `static const`,无法随主题切换,所以保留它作为**浅色值的事实来源**,
/// 由 [HeartColors.light] 逐字段派生;深色值写在 [HeartColors.dark]。
/// 取色一律走 `context.heart`(见 `heart_theme_context.dart`),**必须在 build 内取,不能用 const**。
@immutable
class HeartColors extends ThemeExtension<HeartColors> {
  const HeartColors({
    required this.bgPage,
    required this.bgCard,
    required this.divider,
    required this.text1,
    required this.text2,
    required this.text3,
    required this.brand,
    required this.heartOrange,
    required this.violet,
    required this.systemBlue,
    required this.green,
    required this.amber,
    required this.danger,
    required this.photoScrim,
  });

  /// 页面底色。
  final Color bgPage;

  /// 卡片 / 面板底色。
  final Color bgCard;

  /// 分隔线 / 描边。
  final Color divider;

  /// 主文字。
  final Color text1;

  /// 次文字。
  final Color text2;

  /// 弱文字 / 占位。
  final Color text3;

  /// 品牌主色(心跳渐变起点)。
  final Color brand;

  /// 心跳渐变终点(粉→橙)。
  final Color heartOrange;

  /// 系统紫(系统渐变起点)。
  final Color violet;

  /// 系统蓝(系统渐变终点)。
  final Color systemBlue;

  /// 成功 / 在线。
  final Color green;

  /// 提醒 / 星级。
  final Color amber;

  /// 危险 / 错误。
  final Color danger;

  /// 照片叠字 scrim(发现卡底部渐变终点)。
  final Color photoScrim;

  /// §2.1 里 `success` / `warning` 是 green / amber 的别名,保留同名读取口,迁移时不必改名。
  Color get success => green;
  Color get warning => amber;

  /// 浅色板:从 [AppColors] 派生,单点维护。
  static const light = HeartColors(
    bgPage: AppColors.bgPage,
    bgCard: AppColors.bgCard,
    divider: AppColors.divider,
    text1: AppColors.text1,
    text2: AppColors.text2,
    text3: AppColors.text3,
    brand: AppColors.brand,
    heartOrange: AppColors.heartOrange,
    violet: AppColors.violet,
    systemBlue: AppColors.systemBlue,
    green: AppColors.green,
    amber: AppColors.amber,
    danger: AppColors.danger,
    photoScrim: AppColors.photoScrim,
  );

  /// 深色板:见 [HeartDarkColors]。
  static const dark = HeartColors(
    bgPage: HeartDarkColors.bgPage,
    bgCard: HeartDarkColors.bgCard,
    divider: HeartDarkColors.divider,
    text1: HeartDarkColors.text1,
    text2: HeartDarkColors.text2,
    text3: HeartDarkColors.text3,
    brand: HeartDarkColors.brand,
    heartOrange: HeartDarkColors.heartOrange,
    violet: HeartDarkColors.violet,
    systemBlue: HeartDarkColors.systemBlue,
    green: HeartDarkColors.green,
    amber: HeartDarkColors.amber,
    danger: HeartDarkColors.danger,
    photoScrim: HeartDarkColors.photoScrim,
  );

  /// 按亮度取板。测试与 `buildAppTheme` 共用,避免两处各写一遍三元表达式。
  static HeartColors of(Brightness brightness) =>
      brightness == Brightness.dark ? dark : light;

  /// 字段名 → 色值。给「两套字段齐全」的断言用(不能用 dart:mirrors)。
  Map<String, Color> toMap() => {
        'bgPage': bgPage,
        'bgCard': bgCard,
        'divider': divider,
        'text1': text1,
        'text2': text2,
        'text3': text3,
        'brand': brand,
        'heartOrange': heartOrange,
        'violet': violet,
        'systemBlue': systemBlue,
        'green': green,
        'amber': amber,
        'danger': danger,
        'photoScrim': photoScrim,
      };

  @override
  HeartColors copyWith({
    Color? bgPage,
    Color? bgCard,
    Color? divider,
    Color? text1,
    Color? text2,
    Color? text3,
    Color? brand,
    Color? heartOrange,
    Color? violet,
    Color? systemBlue,
    Color? green,
    Color? amber,
    Color? danger,
    Color? photoScrim,
  }) {
    return HeartColors(
      bgPage: bgPage ?? this.bgPage,
      bgCard: bgCard ?? this.bgCard,
      divider: divider ?? this.divider,
      text1: text1 ?? this.text1,
      text2: text2 ?? this.text2,
      text3: text3 ?? this.text3,
      brand: brand ?? this.brand,
      heartOrange: heartOrange ?? this.heartOrange,
      violet: violet ?? this.violet,
      systemBlue: systemBlue ?? this.systemBlue,
      green: green ?? this.green,
      amber: amber ?? this.amber,
      danger: danger ?? this.danger,
      photoScrim: photoScrim ?? this.photoScrim,
    );
  }

  /// 主题切换动画用:逐通道插值。`other == null` 时按官方约定返回自身。
  @override
  HeartColors lerp(ThemeExtension<HeartColors>? other, double t) {
    if (other is! HeartColors) return this;
    Color mix(Color a, Color b) => Color.lerp(a, b, t)!;
    return HeartColors(
      bgPage: mix(bgPage, other.bgPage),
      bgCard: mix(bgCard, other.bgCard),
      divider: mix(divider, other.divider),
      text1: mix(text1, other.text1),
      text2: mix(text2, other.text2),
      text3: mix(text3, other.text3),
      brand: mix(brand, other.brand),
      heartOrange: mix(heartOrange, other.heartOrange),
      violet: mix(violet, other.violet),
      systemBlue: mix(systemBlue, other.systemBlue),
      green: mix(green, other.green),
      amber: mix(amber, other.amber),
      danger: mix(danger, other.danger),
      photoScrim: mix(photoScrim, other.photoScrim),
    );
  }
}
