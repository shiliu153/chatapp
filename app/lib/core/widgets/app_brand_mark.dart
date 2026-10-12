import 'package:flutter/material.dart';

import '../theme/app_gradients.dart';
import '../theme/app_radius.dart';

/// 品牌 mark(§2 心跳渐变):72 圆角方 + 白色心形图标。
///
/// **必须静态,不带任何常驻动画** —— 登录页/启动页有大量 `pumpAndSettle` 用例
/// (login_page_test / startup_flow_test / account_switch_test / kicked_offline_test /
/// agreement_gate_test),常驻无限动画会让它们永不收敛(批次⑤实测坑,附录 E.3)。
class AppBrandMark extends StatelessWidget {
  const AppBrandMark({super.key, this.size = 72});

  final double size;

  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          gradient: AppGradients.heart,
          borderRadius: BorderRadius.circular(AppRadius.sheet),
        ),
        child: Icon(Icons.favorite_rounded, size: size * 4 / 9, color: Colors.white),
      );
}
