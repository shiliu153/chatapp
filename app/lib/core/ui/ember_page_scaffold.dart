import 'package:flutter/material.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../theme/ember_theme_context.dart';
import '../theme/tokens.g.dart' as tokens;
import 'ember_pressable.dart';

/// 二级页统一 shell(spec §9.4):顶栏 52(返回 22 Phosphor `caret-left` + 标题
/// 17/w600 **居中**)+ 内容区(水平内边距 20)+ 可选底部主操作区。
///
/// 为什么要抽成组件:二级页有二十来个(E-5.6 四组),每页各写一遍 52 顶栏必然走味
/// —— E-5.6 之前「心跳」期的 [AppSubPageBar] 就被复制过两份(见该文件注释)。
/// 抽一处之后,b/c/d 三组只消费、不再实现。
///
/// 状态(见 page spec §4):
/// - `default`:顶栏 `surface.page` 底、无下边线;
/// - `滚动`:内容滚动后顶栏补 1px `border.divider` 下边线(见 [showScrollDivider])。
///   只做颜色切换、不做位移补间 —— 规范没给这一档动效,而减弱动态效果时本来也只能
///   取终态(§7.3),省掉一条补间就等于省掉一条降级分支。
///
/// ```dart
/// EmberPageScaffold(
///   title: '用户协议',
///   body: SingleChildScrollView(child: EmberCard(child: Text(text))),
///   bottomBar: EmberButton(label: '知道了', onPressed: pop),
/// )
/// ```
///
/// 读屏(§8.4):返回键读「返回」;标题按 header 播报。
class EmberPageScaffold extends StatefulWidget {
  /// 构造二级页骨架。
  const EmberPageScaffold({
    super.key,
    required this.title,
    required this.body,
    this.onBack,
    this.backKey,
    this.showBack = true,
    this.trailing,
    this.bottomBar,
    this.contentPadding,
    this.showScrollDivider = true,
  });

  /// 顶栏标题(17/w600 居中)。
  final String title;

  /// 内容区。需要滚动时由调用方自己给滚动视图(本组件不猜内容形态)。
  final Widget body;

  /// 返回回调;`null` 时取 `Navigator.maybePop()`。
  final VoidCallback? onBack;

  /// 返回键的 Key(页面测试按它取)。
  final Key? backKey;

  /// 是否显示返回键(首屏类页面关掉)。
  final bool showBack;

  /// 右侧动作槽(用 Stack 定位,不影响标题居中)。
  final Widget? trailing;

  /// 底部主操作区;`null` 时不占高度。放在安全区上方,内边距沿用页面水平 20。
  final Widget? bottomBar;

  /// 内容区内边距;默认水平 20(§5.2 / §9.4)。
  ///
  /// 内容**自己要贴边**时(例如整页 `PageView`、满宽分割线列表)传
  /// `EdgeInsets.zero`,再在内容里自己加内边距。
  final EdgeInsetsGeometry? contentPadding;

  /// 内容滚动后是否给顶栏补一条 `border.divider` 下边线(page spec §4)。
  ///
  /// 关掉它的场景:内容根本不滚动,或者页面自带图片头图(§9.4 的「顶栏可透明化」)。
  final bool showScrollDivider;

  /// 顶栏高度 52(spec §9.4)。
  ///
  /// 复用 token `size.control.height`(= 52):规范里「控件高 52」与「顶栏高 52」
  /// 是同一个数,补一个 `size.topbar.height` 需要同时改三份生成物 + 六道设计门禁,
  /// 而两者没有各自独立演化的迹象 —— 复用并在 PR「遗留」里记一条待拍的歧义。
  static const double topBarHeight = tokens.sizeControlHeight;

  @override
  State<EmberPageScaffold> createState() => _EmberPageScaffoldState();
}

class _EmberPageScaffoldState extends State<EmberPageScaffold> {
  /// 内容是否已离开顶部(滚动检测的结果)。
  var _scrolled = false;

  bool _onScroll(ScrollNotification notification) {
    // 只看纵向滚动,且只关心「是否离开顶部」这一个布尔:横向列表(标签条、照片条)
    // 滚动不该让顶栏长出下边线。
    if (notification.metrics.axis != Axis.vertical) return false;
    final scrolled = notification.metrics.pixels > 0;
    if (scrolled != _scrolled) setState(() => _scrolled = scrolled);
    // 不吞通知:页面里可能有别的 `NotificationListener`(下拉刷新、回顶按钮)。
    return false;
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final showDivider = widget.showScrollDivider && _scrolled;

    return Scaffold(
      backgroundColor: colors.surfacePage,
      // 输入法弹出时内容让位(登录 / 完善资料都是手输流程)。
      resizeToAvoidBottomInset: true,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            DecoratedBox(
              decoration: BoxDecoration(
                color: colors.surfacePage,
                border: Border(
                  bottom: BorderSide(
                    color: showDivider ? colors.borderDivider : Colors.transparent,
                    width: 1,
                  ),
                ),
              ),
              child: _TopBar(
                title: widget.title,
                onBack: widget.onBack,
                backKey: widget.backKey,
                showBack: widget.showBack,
                trailing: widget.trailing,
              ),
            ),
            Expanded(
              child: NotificationListener<ScrollNotification>(
                onNotification: _onScroll,
                child: Padding(
                  padding: widget.contentPadding ??
                      const EdgeInsets.symmetric(horizontal: tokens.space20),
                  child: widget.body,
                ),
              ),
            ),
            if (widget.bottomBar != null)
              SafeArea(
                top: false,
                child: Padding(
                  padding: EdgeInsets.symmetric(
                    horizontal: tokens.space20,
                    vertical: tokens.space12,
                  ),
                  child: widget.bottomBar,
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// 顶栏本体:52 高、返回 22、标题 17/w600 居中、右侧动作槽(spec §9.4)。
class _TopBar extends StatelessWidget {
  const _TopBar({
    required this.title,
    required this.onBack,
    required this.backKey,
    required this.showBack,
    required this.trailing,
  });

  final String title;
  final VoidCallback? onBack;
  final Key? backKey;
  final bool showBack;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return SizedBox(
      // 必须撑满宽度:放进 Column 时子件拿到的是宽松横向约束,只写 height 会让
      // Stack 缩到标题宽度,返回键与右侧槽压在标题上(AppSubPageBar 踩过同一坑)。
      width: double.infinity,
      height: EmberPageScaffold.topBarHeight,
      child: Stack(
        alignment: Alignment.center,
        children: [
          Semantics(
            header: true,
            child: Text(
              title,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: tokens.fontSizeSubtitle,
                fontWeight: FontWeight.w600,
                height: tokens.fontLineHeightSubtitle,
                color: colors.textPrimary,
              ),
            ),
          ),
          if (showBack)
            Positioned(
              left: 0,
              top: 0,
              bottom: 0,
              child: Center(
                child: EmberPressable(
                  key: backKey,
                  // 读屏标签是规范硬要求(§8.4「图标按钮必须有 Semantics(label:)」),
                  // 也是本单 Semantics 断言的判据。
                  semanticLabel: '返回',
                  onTap: onBack ?? () => Navigator.of(context).maybePop(),
                  pressedScale: 0.97,
                  borderRadius: BorderRadius.circular(tokens.radiusPill),
                  builder: (context, state) => SizedBox(
                    // 热区 48×48(§8.4);图标本体 22(§9.4),不撑热区。
                    width: tokens.sizeTouchApp,
                    height: tokens.sizeTouchApp,
                    child: Center(
                      child: Icon(
                        PhosphorIconsRegular.caretLeft,
                        size: _backIconSize,
                        color: colors.textPrimary,
                      ),
                    ),
                  ),
                ),
              ),
            ),
          if (trailing != null)
            Positioned(
              right: 0,
              top: 0,
              bottom: 0,
              child: Center(child: trailing),
            ),
        ],
      ),
    );
  }

  /// 返回图标 22(spec §9.4 原文「返回 22」)。
  ///
  /// 规范给的是 22,而 token 只有 16 / 20 / 24 三档(§6),所以这一档落在组件层
  /// (与 `EmberComponentSizes` 的其它空隙值同一处理),已记入 PR「遗留」。
  static const double _backIconSize = 22;
}
