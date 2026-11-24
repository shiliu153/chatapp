import 'package:flutter/material.dart';

import '../../../core/ui/ember_ui.dart';

/// 资料页空态 / 错误态用的 unDraw 插画(E-5.4 page spec §5)。
///
/// **复用 E-5.2 已经导出的那两张**,不新增二进制:`Connection lost` 就是「加载失败」,
/// `No data` 就是「这个人不在了」;unDraw 的配色替换口径见
/// `assets/illustrations/README.md`(每张明暗两份,深色版换墨色)。要出资料页专属
/// 插画属于设计资产的增量,留给后续单,本单先把形态落地。
enum ProfileIllustrationKind {
  /// 资料加载失败(unDraw `Connection lost`)。
  loadFailed('discovery_load_failed'),

  /// 他人资料不存在 / 已注销(unDraw `No data`)。
  notFound('discovery_empty');

  const ProfileIllustrationKind(this.assetBase);

  /// 不带后缀的资产名(后缀由明暗决定)。
  final String assetBase;

  /// 取对应模式的资产路径。
  String assetPath({required bool dark}) =>
      'assets/illustrations/${assetBase}_${dark ? 'dark' : 'light'}.png';
}

/// 空态插画(`EmberEmpty` 的 `illustration` 参数)。
///
/// 尺寸取 `EmberEmpty` 的插画上沿 96(§8.3「插画 72–96」),高度按各图比例自适应。
/// 读屏:`EmberEmpty` 已经把标题 + 说明播报出来了,插画是**装饰**,所以
/// `excludeFromSemantics: true`(§8.4「纯装饰图形不念」)。
class ProfileIllustration extends StatelessWidget {
  /// 构造插画。
  const ProfileIllustration(
    this.kind, {
    super.key,
    this.size = EmberComponentSizes.illustrationMax,
  });

  /// 哪一张。
  final ProfileIllustrationKind kind;

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
