import 'package:flutter/material.dart';
import 'package:flutter/physics.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../core/theme/app_shadows.dart';
import '../../core/theme/ember_motion.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';

/// 底栏:常驻导航,四个 tab(E-5.1 page spec §3 / 「余烬 Ember」§8.2、§8.3、§8.5、§9.1)。
///
/// 与旧 `AppBottomBar` 的差别只有三处(其余是底座替换):
/// 1. 命名:发现 / 广场 / 消息 / 我的 → **遇见 / 回声 / 对话 / 我**(§9.1);
/// 2. 选中态:粉→橙渐变胶囊 → **`brand.default` 实色胶囊**(§8.3 底栏行);
/// 3. 切换动效:`duration + curve` → **`spring.fast` 位移**;图标弹跳同一条弹簧(§8.5)。
///
/// 几何(§8.2「底栏」):`surface.card` 胶囊、高 64、左右外距 12、底距 10、
/// 圆角 `radius.xl`;浅色用 `elev.2` 浮层阴影,深色**不用阴影**改 `border.strong`
/// 1px 描边(§5.3「深色模式不用阴影」)。
///
/// 无障碍(§8.4):每一项都是 `Semantics(button, selected, label)`,标签形如
/// 「遇见 tab,已选中」/「对话 tab,3 条未读」—— 选中与未读都不只靠颜色传达;
/// 热区宽 = 1/4 底栏、高 = 64,远超 48×48。
class EmberNavBar extends StatelessWidget {
  /// 构造底栏。
  const EmberNavBar({
    super.key,
    required this.currentIndex,
    required this.onTap,
    this.unreadCount = 0,
  });

  /// 当前选中的 tab 下标(0–3)。
  final int currentIndex;

  /// 点击某个 tab 的回调,参数是目标下标。
  final ValueChanged<int> onTap;

  /// 「对话」tab 的未读数;`0` 不渲染角标(沿用 `unreadTotalProvider`,不新开数据源)。
  final int unreadCount;

  /// 四个 tab 的名称与图标(§9.1 主轴 + page spec §3 的图标映射)。
  ///
  /// 图标一律来自 `phosphor_glyphs`(§6 指定的 Flutter 包):未选中 Regular、
  /// 选中 Fill —— 这正是 §6「状态」那一行的口径,所以同一语义要两张 `IconData`。
  static const List<_NavTabSpec> _tabs = [
    _NavTabSpec(
      label: '遇见',
      icon: PhosphorIconsRegular.cards,
      selectedIcon: PhosphorIconsFill.cards,
    ),
    _NavTabSpec(
      label: '回声',
      icon: PhosphorIconsRegular.broadcast,
      selectedIcon: PhosphorIconsFill.broadcast,
    ),
    _NavTabSpec(
      label: '对话',
      icon: PhosphorIconsRegular.chatCircle,
      selectedIcon: PhosphorIconsFill.chatCircle,
    ),
    _NavTabSpec(
      label: '我',
      icon: PhosphorIconsRegular.user,
      selectedIcon: PhosphorIconsFill.user,
    ),
  ];

  /// 未读角标挂在「对话」tab(§8.5 角标归属,page spec §4)。
  static const int unreadTabIndex = 2;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return SafeArea(
      top: false,
      // 左右外距 12、底距 10(§8.2);高度本身走 token `size.nav.height`。
      // 外边距挂在 Padding 上而不是 `Container.margin`:这样「带装饰的 Container」
      // 的矩形就是胶囊本体(宽 - 24 × 64),几何断言与 golden 不必再加/减外边距。
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
          tokens.space12,
          0,
          tokens.space12,
          EmberComponentSizes.navBottomInset,
        ),
        child: Container(
          height: tokens.sizeNavHeight,
          decoration: BoxDecoration(
            color: colors.surfaceCard,
            borderRadius: BorderRadius.circular(tokens.radiusXl),
            // §5.3:浮层用 `elev.2`;深色模式阴影不可见,改成描边 + 表面色差分层。
            boxShadow: isDark ? null : AppShadows.floatingBar,
            border: isDark ? Border.all(color: colors.borderStrong) : null,
          ),
          child: LayoutBuilder(
            builder: (context, constraints) {
              final slot = constraints.maxWidth / _tabs.length;
              return Stack(
                // 弹簧位移可能轻微过冲,别被底栏自己的圆角裁掉(§8.5 的「弹跳」就是过冲)。
                clipBehavior: Clip.none,
                children: [
                  _SelectedCapsule(
                    index: currentIndex,
                    slotWidth: slot,
                    barHeight: tokens.sizeNavHeight,
                  ),
                  Row(
                    children: [
                      for (var i = 0; i < _tabs.length; i++)
                        Expanded(
                          child: _NavItem(
                            key: navTabKey(i),
                            spec: _tabs[i],
                            selected: i == currentIndex,
                            badgeCount: i == unreadTabIndex ? unreadCount : 0,
                            onTap: () => onTap(i),
                          ),
                        ),
                    ],
                  ),
                ],
              );
            },
          ),
        ),
      ),
    );
  }

  /// 第 [index] 个 tab 的 [Key](语义断言与定点点击都按它取,避开与页面标题重名)。
  static Key navTabKey(int index) => ValueKey<String>('nav.tab.$index');

  /// 选中胶囊的 [Key](golden 与几何断言按它定位;本身不参与交互)。
  static const Key capsuleKey = ValueKey<String>('nav.capsule');
}

/// 一个 tab 的静态描述:名称 + 未选中图标 + 选中图标。
@immutable
class _NavTabSpec {
  const _NavTabSpec({
    required this.label,
    required this.icon,
    required this.selectedIcon,
  });

  /// 显示文案(§9.1)。
  final String label;

  /// 未选中图标(Phosphor Regular 24)。
  final IconData icon;

  /// 选中图标(Phosphor Fill 20,白/`brand.on` 颜色)。
  final IconData selectedIcon;
}

/// 选中胶囊:跟着选中项走的实色胶囊(§8.3 底栏 selected)。
///
/// 为什么不用 `AnimatedPositioned` + curve:§8.5 指定的是 `spring.fast` **弹簧**,
/// 弹簧才能在中途被打断时按当前位置续接(连点两个 tab 不会「跳一下」)。
///
/// 减弱动态效果(§4 reduced motion)时**不位移**:直接落到新格子,用 120ms 线性
/// 淡入交代「选中变了」这件事。
class _SelectedCapsule extends StatefulWidget {
  const _SelectedCapsule({
    required this.index,
    required this.slotWidth,
    required this.barHeight,
  });

  /// 目标格子的下标(选中项)。
  final int index;

  /// 每个 tab 占的槽宽(底栏可用宽度 / 4)。
  final double slotWidth;

  /// 底栏高度,用于把胶囊垂直居中。
  final double barHeight;

  @override
  State<_SelectedCapsule> createState() => _SelectedCapsuleState();
}

class _SelectedCapsuleState extends State<_SelectedCapsule>
    with TickerProviderStateMixin {
  /// 胶囊「当前落在第几格」的连续值:由弹簧从旧位推到新位。
  late final AnimationController _position = AnimationController.unbounded(
    vsync: this,
    value: widget.index.toDouble(),
  );

  /// 减弱动态效果下的淡入进度(正常模式下恒为 1)。
  late final AnimationController _fade = AnimationController(
    vsync: this,
    duration: EmberMotion.reduced,
    value: 1,
  );

  @override
  void didUpdateWidget(covariant _SelectedCapsule oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.index == widget.index) return;
    if (EmberMotion.reducedOf(context)) {
      _position.value = widget.index.toDouble();
      _fade.forward(from: 0);
      return;
    }
    _position.animateWith(
      SpringSimulation(
        EmberMotion.fast,
        _position.value,
        widget.index.toDouble(),
        0,
      ),
    );
  }

  @override
  void dispose() {
    _position.dispose();
    _fade.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Positioned(
      // 起点固定在「第 0 格居中」,位移量 = 当前值 × 槽宽。
      left: (widget.slotWidth - EmberComponentSizes.navCapsuleWidth) / 2,
      top: (widget.barHeight - EmberComponentSizes.navCapsuleHeight) / 2,
      child: IgnorePointer(
        child: AnimatedBuilder(
          animation: _position,
          builder: (context, child) => Transform.translate(
            offset: Offset(_position.value * widget.slotWidth, 0),
            child: child,
          ),
          child: FadeTransition(
            opacity: _fade,
            child: Container(
              key: EmberNavBar.capsuleKey,
              width: EmberComponentSizes.navCapsuleWidth,
              height: EmberComponentSizes.navCapsuleHeight,
              decoration: BoxDecoration(
                // 纯容器,不叠 `emberGlow`:一屏最多一处高音,底栏不是(page spec §3)。
                color: colors.brandDefault,
                borderRadius: BorderRadius.circular(tokens.radiusPill),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 单个 tab:图标 + 标签 + 可选未读角标,按 §8.3 的 default / selected / pressed /
/// focus 四态取值。
class _NavItem extends StatefulWidget {
  const _NavItem({
    super.key,
    required this.spec,
    required this.selected,
    required this.badgeCount,
    required this.onTap,
  });

  /// 名称与两张图标。
  final _NavTabSpec spec;

  /// 是否选中。
  final bool selected;

  /// 未读数(只有「对话」tab 会传非 0)。
  final int badgeCount;

  /// 点击回调。
  final VoidCallback onTap;

  @override
  State<_NavItem> createState() => _NavItemState();
}

class _NavItemState extends State<_NavItem> with SingleTickerProviderStateMixin {
  /// 选中时图标「弹跳」的缩放(§8.5「spring.fast 弹跳」)。
  late final AnimationController _pop = AnimationController.unbounded(
    vsync: this,
    value: 1,
  );

  @override
  void didUpdateWidget(covariant _NavItem oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.selected == widget.selected) return;
    if (EmberMotion.reducedOf(context)) {
      // §4 reduced motion:图标**不缩放**(不是「瞬间缩放到 1.1」)。
      _pop.value = 1;
      return;
    }
    final target = widget.selected ? EmberComponentSizes.navIconPopScale : 1.0;
    _pop.animateWith(SpringSimulation(EmberMotion.fast, _pop.value, target, 0));
  }

  @override
  void dispose() {
    _pop.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final selected = widget.selected;

    // 读屏标签把「选中」与「未读」都说出来(§8.4「颜色不是唯一线索」)。
    final semanticLabel = _semanticLabel();

    return Semantics(
      container: true,
      button: true,
      selected: selected,
      label: semanticLabel,
      onTap: widget.onTap,
      // 图标 / 标签 / 角标不再各自播报:这个 tab 是一件事,标签已经把两件事说完,
      // 否则读屏会先念「遇见」再念「3 条未读」,听起来像两行。
      excludeSemantics: true,
      child: EmberPressable(
        onTap: widget.onTap,
        // pressed = 卡片口径的 `scale .98`、颜色不变(page spec §4;规范未定义底栏按压)。
        pressedScale: EmberComponentSizes.cardPressedScale,
        borderRadius: BorderRadius.circular(tokens.radiusPill),
        builder: (context, state) => Column(
          mainAxisAlignment: MainAxisAlignment.center,
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              // 固定 24 的图标格:选中时图标缩到 20,格子不缩 —— 否则标签会上下跳一下。
              width: tokens.sizeIcon24,
              height: tokens.sizeIcon24,
              child: Stack(
                clipBehavior: Clip.none,
                children: [
                  Center(
                    child: AnimatedBuilder(
                      animation: _pop,
                      builder: (context, child) => Transform.scale(
                        scale: _pop.value,
                        child: child,
                      ),
                      child: Icon(
                        selected ? widget.spec.selectedIcon : widget.spec.icon,
                        size: selected ? tokens.sizeIcon20 : tokens.sizeIcon24,
                        color: selected ? colors.brandOn : colors.textTertiary,
                      ),
                    ),
                  ),
                  if (widget.badgeCount > 0)
                    // 偏移沿用现状(规范只定尺寸没定位置,page spec §7 拍板 #3)。
                    Positioned(
                      top: -6,
                      right: -12,
                      child: EmberBadge(count: widget.badgeCount),
                    ),
                ],
              ),
            ),
            const SizedBox(height: tokens.space4),
            Text(
              widget.spec.label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              // §8.4:micro 档固定不跟随系统字号,避免撑破选中胶囊。
              textScaler: TextScaler.noScaling,
              style: TextStyle(
                fontSize: tokens.fontSizeMicro,
                fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
                height: tokens.fontLineHeightMicro,
                color: selected ? colors.brandOn : colors.textTertiary,
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// 「遇见 tab,已选中」/「对话 tab,3 条未读」(page spec §6 第 3 条)。
  String _semanticLabel() {
    final parts = <String>['${widget.spec.label} tab'];
    if (widget.selected) parts.add('已选中');
    if (widget.badgeCount > 0) parts.add('${widget.badgeCount} 条未读');
    return parts.join('，');
  }
}
