import 'package:flutter/material.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../theme/ember_colors.dart';
import '../theme/ember_theme_context.dart';
import '../theme/tokens.g.dart' as tokens;
import 'ember_pressable.dart';

/// 设置行 / 列表行:标题 + 副标题 + 右侧 slot(值 / 开关 / 箭头)(spec §5.2 / §8.3)。
///
/// 逐格对齐 §8.3 与 E-5.6 page spec §4:
///
/// | 状态 | 取值 |
/// |---|---|
/// | default | 行高 68–76(带副标题时自然撑到 76 一侧);标题 `subtitle` 17/w600;副标题 `caption` 13 `text.secondary` |
/// | pressed | 底 `surface.sunken` + 按压 `scale .97` |
/// | disabled | 标题 / 副标题转 `text.tertiary`,不可点 |
/// | 开关行 on / off | `Switch` 选中 `brand.default`;关闭取 `surface.sunken` |
/// | 分隔线 | [showDivider] 时底部 1px `border.divider` |
///
/// 一个组件覆盖全部右侧 slot:[value](纯文字值)、[trailing](自定义控件)、
/// [switchValue](开关行),外加 [showChevron](可点进下级的箭头)。一个都不给就是最
/// 简单的一行字。
///
/// **水平内边距默认 0**:本行按「整行铺满」设计,横向 20 由页面 / [`EmberPageScaffold`]
/// 给(§5.2 / §9.4);嵌进 `EmberCard`(卡片自带 20 内边距)时正好也不用再加。
/// 只有裸放在页面底上的列表才自己包一层 20。
///
/// 读屏(E-5.6 page spec §6 第 3 条 / §8.4):开关行整行播报「标题,已开启 / 已关闭」,
/// 并把 `toggled` 交给系统;内部的 `Switch` 与文字被 [ExcludeSemantics] 掉,避免同一个
/// 开关连念三遍。
class EmberSettingsTile extends StatelessWidget {
  /// 构造设置行。
  const EmberSettingsTile({
    super.key,
    required this.title,
    this.subtitle,
    this.value,
    this.icon,
    this.trailing,
    this.onTap,
    this.switchValue,
    this.onChanged,
    this.showChevron = false,
    this.enabled = true,
    this.showDivider = false,
    this.semanticLabel,
    this.padding,
  }) : assert(
          switchValue == null || trailing == null,
          '开关行与自定义 trailing 槽二选一(同一行右侧只能放一件事)',
        );

  /// 行标题(17/w600)。
  final String title;

  /// 副标题(13 `text.secondary`);给出后行高落到 76 一侧。
  final String? subtitle;

  /// 右侧文字值(如「深色」「中文」);有 [trailing] 或 [switchValue] 时不渲染。
  final String? value;

  /// 左侧图标(Phosphor,24 档,`text.secondary`)。
  final IconData? icon;

  /// 右侧自定义控件(优先于 [value] 与 [showChevron])。
  final Widget? trailing;

  /// 整行点击;`null` 即不可点(开关行除外 —— 开关行整行点击 = 切换)。
  final VoidCallback? onTap;

  /// 开关行:当前是否开启。**非 `null` 即渲染开关**,选中取 `brand.default`。
  final bool? switchValue;

  /// 开关切换回调;为 `null` 时开关不可切换(等价 disabled)。
  final ValueChanged<bool>? onChanged;

  /// 是否显示右侧箭头(进下级的行)。
  final bool showChevron;

  /// 是否可用;`false` 时文字转 `text.tertiary` 且不可点。
  final bool enabled;

  /// 是否在底部画 1px `border.divider` 分隔线。
  final bool showDivider;

  /// 覆盖读屏标签;开关行默认「标题,已开启 / 已关闭」。
  final String? semanticLabel;

  /// 内边距;默认只有纵向 12(横向留给页面,见类注释)。
  final EdgeInsetsGeometry? padding;

  /// 是否开关行。
  bool get _isSwitch => switchValue != null;

  /// 开关切换的真值(开关行整行点击与读屏动作共用一处)。
  bool get _nextSwitchValue => !(switchValue ?? false);

  /// 整行是否可点:开关行只要回调在就算可点。
  bool get _tappable => enabled && (_isSwitch ? onChanged != null : onTap != null);

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final titleColor = enabled ? colors.textPrimary : colors.textTertiary;
    final subtitleColor = enabled ? colors.textSecondary : colors.textTertiary;
    final slot = _trailingSlot(colors);

    final row = ConstrainedBox(
      // 行高 68–76(§5.2,含纵向内边距):单行 68,带副标题时内容自己撑到 76 一带。
      constraints: const BoxConstraints(minHeight: _minRowHeight),
      child: Padding(
        padding: padding ?? const EdgeInsets.symmetric(vertical: tokens.space12),
        child: Row(
          children: [
            if (icon != null) ...[
              Icon(
                icon,
                size: tokens.sizeIcon24,
                color: enabled ? colors.textSecondary : colors.textTertiary,
              ),
              SizedBox(width: tokens.space12),
            ],
            Expanded(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: tokens.fontSizeSubtitle,
                      fontWeight: FontWeight.w600,
                      height: tokens.fontLineHeightSubtitle,
                      color: titleColor,
                    ),
                  ),
                  if (subtitle != null) ...[
                    SizedBox(height: tokens.space4),
                    Text(
                      subtitle!,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: tokens.fontSizeCaption,
                        height: tokens.fontLineHeightCaption,
                        color: subtitleColor,
                      ),
                    ),
                  ],
                ],
              ),
            ),
            if (slot != null) ...[
              SizedBox(width: tokens.space12),
              slot,
            ],
          ],
        ),
      ),
    );

    if (showDivider) {
      return DecoratedBox(
        decoration: BoxDecoration(
          border: Border(
            bottom: BorderSide(color: colors.borderDivider, width: 1),
          ),
        ),
        child: _pressable(row),
      );
    }
    return _pressable(row);
  }

  /// 包一层按压层:能点时响应整行点击,不能点时只保留文字(不吃手势)。
  Widget _pressable(Widget child) {
    if (!_tappable) {
      // 不可点的行(纯展示 / disabled)不进读屏的按钮集合,但标题 + 副标题仍要念出来。
      return Semantics(
        container: true,
        enabled: false,
        label: _isSwitch ? _switchSemanticsLabel : _rowSemanticsLabel,
        child: ExcludeSemantics(child: child),
      );
    }

    final rowTap = _isSwitch ? () => onChanged?.call(_nextSwitchValue) : onTap;

    if (_isSwitch) {
      // 开关行:外层 Semantics 给「标题,已开启/已关闭」+ toggled + 读屏可切换动作;
      // 内层的 Switch 与文字都 exclude 掉(否则同一行会念出三遍「开关」)。
      return Semantics(
        container: true,
        enabled: enabled,
        toggled: switchValue,
        label: _switchSemanticsLabel,
        onTap: rowTap,
        child: ExcludeSemantics(child: _pressableBody(child, rowTap)),
      );
    }

    // 可点行(进下级的行):标签 = 标题(+ 副标题),按钮语义 + 读屏点击动作都由这层给;
    // 行内文字与自绘 slot 一律 exclude —— 否则读屏会把同一个标题念两遍
    // (「设备管理\n设备管理」),这是把 `Semantics(label:)` 与行内 `Text` 叠在
    // 一棵树里的必踩坑。
    return Semantics(
      container: true,
      button: true,
      enabled: enabled,
      label: _rowSemanticsLabel,
      onTap: rowTap,
      child: ExcludeSemantics(child: _pressableBody(child, rowTap)),
    );
  }

  /// 真正的按压反馈层(`pressed` = `surface.sunken` + `scale .97`)。
  ///
  /// 这里**不挂** `semanticLabel`:读屏标签统一由外层 `Semantics` 给(开关行一条、
  /// 可点行一条),否则同一行会出现两个语义节点。
  Widget _pressableBody(Widget child, VoidCallback? onTap) => EmberPressable(
        onTap: onTap,
        enabled: onTap != null,
        pressedScale: 0.97,
        builder: (context, state) => ColoredBox(
          color: state.pressed ? context.ember.surfaceSunken : Colors.transparent,
          child: child,
        ),
      );

  /// 开关行的读屏标签:「标题,已开启 / 已关闭」。
  String get _switchSemanticsLabel =>
      semanticLabel ?? '$title,${(switchValue ?? false) ? '已开启' : '已关闭'}';

  /// 非开关行的读屏标签:标题(+ 副标题)。
  String get _rowSemanticsLabel =>
      semanticLabel ?? [title, ?subtitle].join('，');

  /// 右侧 slot:自定义控件 > 开关 > 文字值 > 箭头(一行右侧只放一件事)。
  Widget? _trailingSlot(EmberColors colors) {
    if (trailing != null) return trailing;
    if (_isSwitch) {
      return Switch(
        value: switchValue!,
        // 整行点击也走 `onChanged`(与「心跳」期的 `VisitsHiddenRow` 同一口径:
        // 点开关与点整行都只切换一次)。
        onChanged: enabled && onChanged != null ? onChanged : null,
        activeThumbColor: colors.brandOn,
        activeTrackColor: colors.brandDefault,
        inactiveThumbColor: colors.surfaceCard,
        inactiveTrackColor: colors.surfaceSunken,
      );
    }
    if (value != null) {
      return Text(
        value!,
        style: TextStyle(
          fontSize: tokens.fontSizeBody,
          height: tokens.fontLineHeightBody,
          color: enabled ? colors.textSecondary : colors.textTertiary,
        ),
      );
    }
    if (showChevron) {
      return Icon(
        PhosphorIconsRegular.caretRight,
        size: tokens.sizeIcon20,
        color: colors.textTertiary,
      );
    }
    return null;
  }

  /// 行高下沿 68(spec §5.2「列表行高 68–76」)。
  static const double _minRowHeight = 68;
}
