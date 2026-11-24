import 'package:flutter/material.dart';

import '../theme/ember_colors.dart';
import '../theme/ember_theme_context.dart';
import '../theme/tokens.g.dart' as tokens;
import 'ember_component_sizes.dart';
import 'ember_glow.dart';
import 'ember_online_dot.dart';
import 'ember_skeleton.dart';

/// 头像:一律圆形;尺寸 28/32/40/48/56/96;无照片时首字 + 柔色底;
/// 在线点 `status.success` 直径 11(小场景 8)+ 呼吸;「新配对」用 `emberGlow` 环
/// 2.5px(spec §8.2 / §8.3)。
///
/// **不画渐变环**:§8.2 明确「新配对」是光晕不是渐变条 —— 渐变环是本轮要清掉的
/// 心跳期做法。
///
/// 柔色底为什么取 `surface.sunken`:规范允许 `ember.50` / `paper.100` / 派生柔色,
/// 但生成物只暴露**语义层**(§3.1 Tier 3 默认不建),因此取同为暖中性、且能在深色
/// 下自动翻转的 `surface.sunken` 最稳;要严格用 `ember.50` 需先让 flow 栈把
/// primitive 也生成出来(已记入 PR 遗留)。
class EmberAvatar extends StatelessWidget {
  /// 构造头像。
  const EmberAvatar({
    super.key,
    this.image,
    this.name,
    this.size = EmberComponentSizes.avatarMd,
    this.online = false,
    this.isNewMatch = false,
    this.loading = false,
    this.semanticLabel,
  });

  /// 头像图;`null` 时回落到首字。
  final ImageProvider? image;

  /// 昵称(取首字做占位;也用于读屏)。
  final String? name;

  /// 直径;只允许 spec §8.2 的六档。
  final double size;

  /// 是否显示在线点(§8.3 `selected(在线)`)。
  final bool online;

  /// 是否是「新配对」(§8.3 `selected(新配对)`,画 `emberGlow` 环)。
  final bool isNewMatch;

  /// 加载态:画一个同尺寸的圆形骨架(§8.3 `loading`)。
  final bool loading;

  /// 覆盖读屏标签。
  final String? semanticLabel;

  /// spec §8.2 允许的六档尺寸。
  static const List<double> allowedSizes = [
    EmberComponentSizes.avatarXs,
    EmberComponentSizes.avatarSm,
    EmberComponentSizes.avatarMd,
    EmberComponentSizes.avatarLg,
    EmberComponentSizes.avatarXl,
    EmberComponentSizes.avatarHero,
  ];

  @override
  Widget build(BuildContext context) {
    assert(
      allowedSizes.contains(size),
      '头像尺寸只能是 spec §8.2 的六档:28/32/40/48/56/96,收到 $size',
    );
    final colors = context.ember;
    final dotSize = size <= EmberComponentSizes.avatarSm
        ? EmberComponentSizes.onlineDotSmall
        : EmberComponentSizes.onlineDot;

    Widget core;
    if (loading) {
      core = EmberSkeleton(
        width: size,
        height: size,
        shape: BoxShape.circle,
      );
    } else if (image == null) {
      core = Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: colors.surfaceSunken,
        ),
        alignment: Alignment.center,
        child: _initialsText(colors),
      );
    } else {
      // 有图时走 `Image` + `errorBuilder` 而不是 `DecorationImage`:
      // 解码失败(网络图 404 / 半张包)时能**回落到首字**,而不是既画不出图又抛一个
      // 没人接的异常(踩过:widget 测试里 NetworkImage 一律 400,直接红)。
      core = ClipOval(
        child: SizedBox.square(
          dimension: size,
          child: Image(
            image: image!,
            fit: BoxFit.cover,
            errorBuilder: (context, error, stack) => ColoredBox(
              color: colors.surfaceSunken,
              child: Center(child: _initialsText(colors)),
            ),
          ),
        ),
      );
    }

    Widget content = core;
    if (online && !loading) {
      content = Stack(
        clipBehavior: Clip.none,
        children: [
          core,
          Positioned(
            right: 0,
            bottom: 0,
            child: EmberOnlineDot(size: dotSize, background: colors.surfaceCard),
          ),
        ],
      );
    }

    if (isNewMatch && !loading) {
      // 环用光晕画(§8.2),一屏最多一处。
      content = EmberGlow(
        shape: EmberGlowShape.circle,
        opacity: 0.12,
        spread: EmberComponentSizes.newMatchRing,
        child: content,
      );
    }

    final label = semanticLabel ??
        [
          if (name != null && name!.isNotEmpty) name!,
          if (online) '在线',
          if (isNewMatch) '新配对',
        ].join('，');
    if (label.isEmpty) return content;
    return Semantics(
      // `container: true`:头像自成一个语义节点,标签不会被上层卡片吞进
      // 「一行一大串」里(§8.4「列表行 = 一行一件事」的反面)。
      container: true,
      image: true,
      // 占位首字 / 头像图对读屏没有增量信息,只念「昵称,在线」(§8.4)。
      excludeSemantics: true,
      label: label,
      child: content,
    );
  }

  /// 取昵称首字(空昵称回落到「?」,避免渲染成空圈)。
  String _initials(String? name) {
    final trimmed = (name ?? '').trim();
    // 用 runes 而不是 `[0]`:后者按 UTF-16 取码元,会把 emoji 昵称劈成半个字符。
    return trimmed.isEmpty ? '?' : String.fromCharCode(trimmed.runes.first);
  }

  /// 首字占位文字:字号随尺寸档缩放(大图不打字,小图不溢出),`text.tertiary` 之外的
  /// 中性档取 `text.secondary` —— 它与 `surface.sunken` 的对比度过线(§3.4)。
  Widget _initialsText(EmberColors colors) => Text(
        _initials(name),
        textScaler: size >= EmberComponentSizes.avatarHero
            ? TextScaler.linear(1)
            : TextScaler.noScaling,
        style: TextStyle(
          fontSize: (size * 0.4).clamp(tokens.fontSizeMicro, tokens.fontSizeTitle),
          fontWeight: FontWeight.w600,
          color: colors.textSecondary,
        ),
      );
}
