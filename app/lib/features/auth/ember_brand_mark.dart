import 'package:flutter/material.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;

/// 准入线(启动 / 登录 / 完善资料)的品牌 mark:朱砂圆角方 + `brand.on` 心形。
///
/// 为什么不再用 `core/widgets/app_brand_mark.dart`:那个是「心跳」期的**渐变**方块
/// (§2 心跳渐变),而 Ember 是「暖纸 + 朱砂、单一强调色、没有渐变主按钮」
/// (§1 / §3.5)—— 品牌区留渐变等于把旧语言钉在最显眼的位置。这里只用
/// `brand.default` 实底 + `radius.lg`,不新增色值、不新增 token。
///
/// **必须静态、不带任何常驻动画**:启动页 / 登录页有一批 `pumpAndSettle` 用例
/// (login_page_test / startup_flow_test / account_switch_test / kicked_offline_test /
/// agreement_gate_test),常驻无限动画会让它们永不收敛(心跳期实测坑)。
class EmberBrandMark extends StatelessWidget {
  /// 构造品牌 mark;默认 72(与 `AppBrandMark` 同尺寸,版式不变)。
  const EmberBrandMark({super.key, this.size = 72});

  /// 边长(正方形)。
  final double size;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: colors.brandDefault,
        borderRadius: BorderRadius.circular(tokens.radiusLg),
      ),
      child: Center(
        // 装饰图形:品牌名由下方标题念出,图标本身不再占读屏(§8.4)。
        child: ExcludeSemantics(
          child: Icon(
            PhosphorIconsFill.heart,
            // 心形占 mark 的 4/9 —— 沿用旧 mark 的比例,视觉重量不变。
            size: size * 4 / 9,
            color: colors.brandOn,
          ),
        ),
      ),
    );
  }
}
