import 'package:flutter/material.dart';

import '../../../core/ui/ember_ui.dart';

/// 设置线(E-5.6b)空态 / 错误态用的 unDraw 插画。
///
/// **复用已有的两张,不新增二进制**(与 E-5.4 / E-5.5 同一处理):`No data` 就是
/// 「列表里还没有东西」,`Connection lost` 就是「加载失败」;unDraw 的配色替换口径见
/// `assets/illustrations/README.md`(每张明暗两份,深色版换墨色)。设置线专属插画
/// 属于设计资产增量,留给后续单。
enum SettingsIllustrationKind {
  /// 列表为空(unDraw `No data`)。
  listEmpty('discovery_empty'),

  /// 加载失败(unDraw `Connection lost`)。
  loadFailed('discovery_load_failed');

  const SettingsIllustrationKind(this.assetBase);

  /// 不带后缀的资产名(后缀由明暗决定)。
  final String assetBase;

  /// 取对应模式的资产路径。
  String assetPath({required bool dark}) =>
      'assets/illustrations/${assetBase}_${dark ? 'dark' : 'light'}.png';
}

/// 空态插画([`EmberEmpty`] 的 `illustration` 参数)。
///
/// 尺寸取 `EmberEmpty` 的插画上沿 96(spec §8.3「插画 72–96」),高度按各图比例自适应。
/// 读屏:`EmberEmpty` 已经把标题 + 说明播报出来了,插画是**装饰**,所以
/// `excludeFromSemantics: true`(§8.4「纯装饰图形不念」)。
class SettingsIllustration extends StatelessWidget {
  /// 构造插画。
  const SettingsIllustration(
    this.kind, {
    super.key,
    this.size = EmberComponentSizes.illustrationMax,
  });

  /// 哪一张。
  final SettingsIllustrationKind kind;

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
