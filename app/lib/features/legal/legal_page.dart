import 'package:flutter/material.dart';

import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_section_card.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import 'legal_texts.dart';

/// 协议/隐私全文页(附录 E):二级页顶栏 + 白卡长文。
/// 正文来自 `legal_texts.dart`,**一字不动**。
class LegalPage extends StatelessWidget {
  const LegalPage.agreement({super.key}) : _title = '用户协议', _text = userAgreementText;

  const LegalPage.privacy({super.key}) : _title = '隐私政策', _text = privacyPolicyText;

  final String _title;
  final String _text;

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: AppColors.bgPage,
        body: SafeArea(
          bottom: false,
          child: Column(
            children: [
              AppSubPageBar(title: _title, backKey: const Key('legal.back')),
              Expanded(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(AppSpacing.pageH,
                      AppSpacing.md, AppSpacing.pageH, AppSpacing.xxl),
                  child: AppSectionCard(
                    children: [
                      Text(
                        _text,
                        style: AppText.body.copyWith(
                          color: AppColors.text1,
                          height: 1.6,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      );
}
