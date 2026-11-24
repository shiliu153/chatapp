import 'package:flutter/material.dart';

import '../../../core/ui/ember_ui.dart';

/// 发现页空态 / 错误态用的三张 unDraw 插画(E-5.2 page spec §5 / 拍板 5)。
///
/// 资产与配色口径见 `assets/illustrations/README.md`:每张图有明暗两份 PNG,
/// 因为 unDraw 的深墨落在深色页上会整张消失 —— 这不是「多此一举的备图」,而是
/// §3.3「浅深两套都要过线」的一半判据。
enum DiscoveryIllustrationKind {
  /// 附近暂时没有新的人了(`No data`)。
  emptyNearby('discovery_empty'),

  /// 资料没完善(`Profile data`)。
  profileIncomplete('discovery_profile_incomplete'),

  /// 加载失败(`Connection lost`)。
  loadFailed('discovery_load_failed');

  const DiscoveryIllustrationKind(this.assetBase);

  /// 不带后缀的资产名(后缀由明暗决定)。
  final String assetBase;

  /// 取对应模式的资产路径。
  String assetPath({required bool dark}) =>
      'assets/illustrations/${assetBase}_${dark ? 'dark' : 'light'}.png';
}

/// 空态插画(`EmberEmpty` 的 `illustration` 参数)。
///
/// 尺寸取 `EmberEmpty` 的插画上沿 96(§8.3「插画 72–96」),高度按各图比例自适应,
/// 所以宽图(加载失败 1.86:1)不会被拉成方块。
///
/// 读屏:`EmberEmpty` 已经把标题 + 说明播报出来了,插画是**装饰**,所以
/// `excludeFromSemantics: true`(§8.4「纯装饰图形不念」)。
class DiscoveryIllustration extends StatelessWidget {
  /// 构造插画。
  const DiscoveryIllustration(
    this.kind, {
    super.key,
    this.size = EmberComponentSizes.illustrationMax,
  });

  /// 哪一张。
  final DiscoveryIllustrationKind kind;

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
