import 'package:flutter/material.dart';

import '../../core/theme/app_typography.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import 'legal_texts.dart';

/// 协议/隐私全文页(E-5.6a 迁移到 Ember):§9.4 二级页 shell + 白卡长文。
///
/// 正文来自 `legal_texts.dart`,**一字不动**;本页只换外壳(顶栏换 [`EmberPageScaffold`]、
/// 卡片换 [`EmberCard`]、正文换 token 字阶)。
class LegalPage extends StatelessWidget {
  /// 用户协议全文。
  const LegalPage.agreement({super.key}) : _title = '用户协议', _text = userAgreementText;

  /// 隐私政策全文。
  const LegalPage.privacy({super.key}) : _title = '隐私政策', _text = privacyPolicyText;

  final String _title;
  final String _text;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return EmberPageScaffold(
      title: _title,
      backKey: const Key('legal.back'),
      body: SingleChildScrollView(
        // 横向 20 由 shell 给(§9.4),这里只补纵向气口。
        padding: EdgeInsets.only(top: tokens.space16, bottom: tokens.space40),
        child: EmberCard(
          child: Text(
            _text,
            // 长文走 `body` 15 / 1.55(§4.2);旧版手工写 1.6 是为了压住「心跳」的
            // 紧行距,Ember 的 body 档行距本身就是正文档,不再覆盖。
            style: AppText.body.copyWith(color: colors.textPrimary),
          ),
        ),
      ),
    );
  }
}
