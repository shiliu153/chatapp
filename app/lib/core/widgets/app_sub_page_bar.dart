import 'package:flutter/material.dart';

import '../theme/app_typography.dart';
import '../theme/heart_theme_context.dart';

/// 「心跳」规则 §5.2 二级页顶栏:高 52,返回箭头 22 `text1`,标题 17/w600 居中。
///
/// [trailing] 是右侧动作槽(文字按钮等),用 Stack 定位所以不影响标题居中。
/// 批次⑤ 曾在我的动态页与详情页各留一份私有副本,本批抽共享(附录 E.2)。
class AppSubPageBar extends StatelessWidget {
  const AppSubPageBar({
    super.key,
    required this.title,
    this.backKey,
    this.onBack,
    this.trailing,
    this.showBack = true,
  });

  final String title;
  final Key? backKey;

  /// 默认 `Navigator.of(context).maybePop()`。
  final VoidCallback? onBack;
  final Widget? trailing;
  final bool showBack;

  static const height = 52.0;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    return SizedBox(
        // 必须显式撑满宽度:放进 Column 时子件拿到的是**宽松**横向约束,
        // 只写 height 的话 Stack 会缩到标题文字的宽度,返回键与 trailing 就会
        // 压在标题上(2026-11-07 模拟器手测发现,编辑资料页的「保存」曾与标题重叠)。
        width: double.infinity,
        height: height,
        child: Stack(
          alignment: Alignment.center,
          children: [
            Text(
              title,
              style: AppText.subtitle
                  .copyWith(fontSize: 17, color: colors.text1), // 17/w600(§5.2)
            ),
            if (showBack)
              Positioned(
                left: 0,
                top: 0,
                bottom: 0,
                child: IconButton(
                  key: backKey,
                  onPressed: onBack ?? () => Navigator.of(context).maybePop(),
                  icon: Icon(Icons.arrow_back_ios_new_rounded,
                      size: 22, color: colors.text1),
                ),
              ),
            if (trailing != null)
              Positioned(
                right: 0,
                top: 0,
                bottom: 0,
                child: Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: Center(child: trailing),
                ),
              ),
          ],
        ),
      );
  }
}
