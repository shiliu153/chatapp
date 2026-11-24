import 'package:flutter/material.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../../core/theme/app_typography.dart';
import '../../../core/theme/ember_colors.dart';
import '../../../core/theme/ember_theme_context.dart';
import '../../../core/theme/tokens.g.dart' as tokens;
import '../../../core/ui/ember_ui.dart';
import '../profile_component_sizes.dart';

/// 资料页的**信息行**(E-5.4 page spec §3「信息行」/ 上游 §5.2)。
///
/// 逐格对齐 page spec 给的取值:
///
/// | 项 | 取值 |
/// |---|---|
/// | 行高 | 68–76(本单取 [ProfileComponentSizes.infoRowHeight] = 72) |
/// | 标签 | `subtitle` 17 / w600 / `text.primary` |
/// | 值 | `body` 15 / `text.secondary` |
/// | 分隔线 | `border.divider`(每行底边,最后一行不画由调用方控制) |
/// | pressed | `surface.sunken`(可点行) |
///
/// 为什么标签比取值更粗更大:规范把「信息行」定义成**以字段名为主语**的一行
/// (「性别 → 女」),视线先扫字段名再落到取值上,所以标签走 `subtitle`、取值走
/// `body`;这与心跳期「小标签 13 + 大取值 15」是**故意反过来的**,验收时不要按旧图改。
///
/// 读屏口径(§8.4「列表行 = 一行一件事」):整行读「标签,值」。可点行先由
/// [EmberPressable] 声明 `button: false` 的容器语义,再统一挂 label —— 这样读屏
/// 不会把行内的标签文字和取值文字念两遍。
class ProfileInfoRow extends StatelessWidget {
  /// 构造信息行。
  const ProfileInfoRow({
    super.key,
    required this.label,
    this.value,
    this.child,
    this.icon,
    this.onTap,
    this.showDivider = true,
  });

  /// 字段名(读屏标签的前半句)。
  final String label;

  /// 取值;空串按「未填」渲染(§5「资料不完整」同一口径)。
  final String? value;

  /// 自定义取值区(标签 chip 组等);给出时忽略 [value]。
  final Widget? child;

  /// 行首页图标(纯入口行用,16 档 `text.tertiary`? —— 入口行要给视线一个锚点,
  /// 取 20 档 `text.secondary`,与 §6「按钮内 20」同级)。
  final IconData? icon;

  /// 点击回调;`null` 即静态行(§8.1 的 Card 可点 / 静态同款区分)。
  final VoidCallback? onTap;

  /// 是否画底边分隔线(分组最后一行传 false)。
  final bool showDivider;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    // value == null:纯入口行,没有「取值」概念,不能显示「未填」。
    final text = value == null ? null : (value!.isEmpty ? '未填' : value!);
    final leading = icon;

    Widget body = Container(
      constraints: const BoxConstraints(
        minHeight: ProfileComponentSizes.infoRowHeight,
      ),
      padding: EdgeInsets.symmetric(
        horizontal: tokens.space20,
        vertical: tokens.space12,
      ),
      decoration: BoxDecoration(
        border: showDivider
            ? Border(bottom: BorderSide(color: colors.borderDivider))
            : null,
      ),
      child: Row(
        children: [
          if (leading != null) ...[
            Icon(leading, size: tokens.sizeIcon20, color: colors.textSecondary),
            SizedBox(width: tokens.space12),
          ],
          Expanded(child: _content(context, colors, text)),
          if (onTap != null)
            // `caret-right` 22:§6 工具栏档以下,和 17 号标签同高,不抢视线。
            Icon(
              PhosphorIconsRegular.caretRight,
              size: tokens.sizeIcon20,
              color: colors.textTertiary,
            ),
        ],
      ),
    );

    // 读屏一句话:标签 + 取值(自绘制行没有原生语义可依赖)。
    final semanticValue = child == null ? (text ?? '') : (value ?? '');
    final label = semanticValue.isEmpty
        ? this.label
        : '${this.label}，$semanticValue';

    // `excludeSemantics: true`:行内的标签文字 / 取值文字不再各自成一个节点,
    // 整行只念一遍「标签,值」(§8.4「列表行 = 一行一件事」)。
    Widget wrapSemantics(Widget child) => Semantics(
      container: true,
      excludeSemantics: true,
      label: label,
      child: child,
    );

    if (onTap == null) return wrapSemantics(body);
    return EmberPressable(
      onTap: onTap,
      pressedScale: 0.98,
      semanticButton: false,
      // 标签由内层 Semantics 提供:这一层只负责按压 / 焦点与 tap 语义。
      builder: (context, state) => wrapSemantics(
        ColoredBox(
          // 可点行按下压 `surface.sunken`(page spec §4「pressed」一格)。
          color: state.pressed ? colors.surfaceSunken : Colors.transparent,
          child: body,
        ),
      ),
    );
  }

  /// 取值区:「标签 + 取值」两行叠放;[child] 只替换**取值那一行**(标签 chip 组、
  /// 未填提示等),标签本身永远在 —— 行没有标签就不成其为「信息行」。
  Widget _content(BuildContext context, EmberColors colors, String? text) {
    final custom = child;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          label,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: AppText.subtitle.copyWith(color: colors.textPrimary),
        ),
        if (custom != null) ...[
          SizedBox(height: tokens.space8),
          custom,
        ] else if (text != null) ...[
          SizedBox(height: tokens.space4),
          Text(
            text,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: AppText.body.copyWith(color: colors.textSecondary),
          ),
        ],
      ],
    );
  }
}
