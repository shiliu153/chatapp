import 'package:flutter/material.dart';

import 'tokens.g.dart' as tokens;

/// 「余烬 Ember」§4.1 字族策略在 Flutter 侧的翻译。
///
/// token `font.family.body` 是一条 **CSS 风格的字体链**(`PingFang SC, MiSans, …`),
/// 而 Flutter 的 `fontFamily` 只认**单个**字族名、链式优先级要写进 `fontFamilyFallback`。
/// 所以这里把 token 拆成列表:拉丁与数字落到平台默认(SF / Roboto),
/// 中文按 token 里的顺序取系统字族 —— 与规范「中文走系统、不打包中文字族」一致。
final List<String> kBodyFontFallback = tokens.fontFamilyBody
    .split(',')
    .map((family) => family.trim())
    .where((family) => family.isNotEmpty)
    .toList(growable: false);

/// 标题档(Fraunces)的中文回退: Fraunces 没有 CJK 字形,中文标题必须落到系统字族。
const List<String> kDisplayFontFallback = [
  'PingFang SC',
  'MiSans',
  'HarmonyOS Sans',
  'Noto Sans CJK SC',
  'sans-serif',
];

/// 按 §4.2 字阶造一条 TextStyle:字号 / 行高从 `design/tokens/scale.json` 的生成物取,
/// 只有 `display` / `title` 两档用 Fraunces(§4.1「Fraunces 只用于两档」)。
TextStyle _emberText({
  required double size,
  required FontWeight weight,
  required double height,
  double trackingEm = 0,
  bool display = false,
}) =>
    TextStyle(
      fontFamily: display ? tokens.fontFamilyDisplay : null,
      fontFamilyFallback: display ? kDisplayFontFallback : kBodyFontFallback,
      fontSize: size,
      fontWeight: weight,
      height: height,
      // Fraunces 是**可变字体**,pubspec 里刻意没写 weight(写了就等于声明「只有那个字重」,
      // 其余会被假粗体合成)。真实字重必须走 wght 轴,否则 32/w700 的 display 会是描边加粗。
      fontVariations: display ? [FontVariation('wght', weight.value.toDouble())] : null,
      // §4.2 的字距是 em 值(-0.02em / -0.01em / 0.01em):乘上该档字号得到像素值,
      // 这样字距也随字号联动,页面里不必再写一个魔法数。
      letterSpacing: size * trackingEm,
    );

/// §4.2 字阶(六档;`badge` / `emoji` 是 `micro` 与空态插图的特化)。
///
/// 备注:
/// - §18.4「`micro` 12 / `badge` 11 两档合一,取更小的 11」→ [badge] 直接复用 [micro]。
/// - §4.3「`micro` 档不跟随系统字号缩放」不在这里表达(那是组件在 `Text` 上设
///   `TextScaler.noScaling` 的事,底栏与角度都已照做)。
abstract final class AppText {
  /// §4.2 `display` 32 / w700 / 行高 1.15 / 字距 -0.02em / Fraunces(Tab 大标题、年龄大字)。
  static final display = _emberText(
    size: tokens.fontSizeDisplay,
    weight: FontWeight.w700,
    height: tokens.fontLineHeightDisplay,
    trackingEm: -0.02,
    display: true,
  );

  /// §4.2 `title` 24 / w600 / 1.25 / -0.01em / Fraunces(区块标题、弹层标题)。
  static final title = _emberText(
    size: tokens.fontSizeTitle,
    weight: FontWeight.w600,
    height: tokens.fontLineHeightTitle,
    trackingEm: -0.01,
    display: true,
  );

  /// §4.2 `subtitle` 17 / w600 / 1.35(列表主文字、昵称、会话名)。
  static final subtitle = _emberText(
    size: tokens.fontSizeSubtitle,
    weight: FontWeight.w600,
    height: tokens.fontLineHeightSubtitle,
  );

  /// §4.2 `body` 15 / w400 / **1.55**(正文、消息;按钮文字另按 §4.2 取 w600–700)。
  static final body = _emberText(
    size: tokens.fontSizeBody,
    weight: FontWeight.w400,
    height: tokens.fontLineHeightBody,
  );

  /// §4.2 `caption` 13 / w400 / 1.45(辅助说明、预览)。
  static final caption = _emberText(
    size: tokens.fontSizeCaption,
    weight: FontWeight.w400,
    height: tokens.fontLineHeightCaption,
  );

  /// §4.2 `micro` 11 / w500 / 1.3 / 0.01em(角标、标签、底栏文字)。
  static final micro = _emberText(
    size: tokens.fontSizeMicro,
    weight: FontWeight.w500,
    height: tokens.fontLineHeightMicro,
    trackingEm: 0.01,
  );

  /// 角标专用(§18.4:两档合一,取 `micro` 的 11)。
  static final badge = micro;

  /// 空态插图尺寸(§8.2「插画 72–96」取下沿) —— 不是字阶档位,故不入 token。
  static final emoji = _emberText(
    size: 72,
    weight: FontWeight.w400,
    height: 1.0,
  );
}
