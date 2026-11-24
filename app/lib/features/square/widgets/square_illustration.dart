import 'package:flutter/material.dart';

import '../../../core/ui/ember_ui.dart';

/// 回声(广场)线空态与错误态用的 unDraw 插画(E-5.5 page spec §5)。
///
/// 资产与配色口径见 `assets/illustrations/README.md`(与 E-5.2 / E-5.3 同一套导出
/// 口径):每张图明暗两份 PNG —— unDraw 的深墨落在深色页上会整张消失,深色版
/// 必须换墨色。
enum SquareIllustrationKind {
  /// 动态流为空(unDraw `Online posts`)。
  emptyFeed('square_empty'),

  /// 加载失败 / 动态已被删除(unDraw `Connection lost`)。
  loadFailed('square_error');

  const SquareIllustrationKind(this.assetBase);

  /// 不带明暗后缀的资产名。
  final String assetBase;

  /// 取对应模式的资产路径。
  String assetPath({required bool dark}) =>
      'assets/illustrations/${assetBase}_${dark ? 'dark' : 'light'}.png';
}

/// 空态插画([EmberEmpty] 的 `illustration` 参数)。
///
/// 尺寸取 `EmberEmpty` 的插画上沿 96(§8.3「插画 72–96」),高度按各图比例自适应,
/// 所以宽图(加载失败 1.86:1)不会被拉成方块。
///
/// 读屏:[EmberEmpty] 已经把标题 + 说明播报出来了,插画是**装饰**,
/// 所以 `excludeFromSemantics: true`(§8.4「纯装饰图形不念」)。
class SquareIllustration extends StatelessWidget {
  /// 构造插画。
  const SquareIllustration(
    this.kind, {
    super.key,
    this.size = EmberComponentSizes.illustrationMax,
  });

  /// 哪一张。
  final SquareIllustrationKind kind;

  /// 宽度上限(高度按比例)。
  final double size;

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    return Image.asset(
      kind.assetPath(dark: dark),
      width: size,
      fit: BoxFit.contain,
      excludeFromSemantics: true,
    );
  }
}
