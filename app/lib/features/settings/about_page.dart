import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/app_info.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_brand_mark.dart';
import '../../core/widgets/app_list_row.dart';
import '../../core/widgets/app_row_group.dart';
import '../../core/widgets/app_sub_page_bar.dart';

/// 关于页:应用名、版本、协议入口与版权。
class AboutPage extends StatelessWidget {
  const AboutPage({super.key});

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: AppColors.bgPage,
        body: SafeArea(
          bottom: false,
          child: Column(
            children: [
              const AppSubPageBar(title: '关于'),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(AppSpacing.pageH,
                      AppSpacing.xxl, AppSpacing.pageH, AppSpacing.xxl),
                  children: [
                    const Center(child: AppBrandMark(size: 72)),
                    const SizedBox(height: AppSpacing.md),
                    Center(
                      child: Text(appDisplayName,
                          style: AppText.title.copyWith(color: AppColors.text1)),
                    ),
                    const SizedBox(height: AppSpacing.xs),
                    Center(
                      child: Text(
                        '版本 $appVersion',
                        key: const Key('about.version'),
                        style: AppText.caption.copyWith(color: AppColors.text3),
                      ),
                    ),
                    const SizedBox(height: AppSpacing.xxl),
                    AppRowGroup(
                      children: [
                        AppListRow(
                          key: const Key('about.agreement'),
                          icon: Icons.description_rounded,
                          title: '用户协议',
                          onTap: () => context.push('/legal/agreement'),
                        ),
                        AppListRow(
                          key: const Key('about.privacy'),
                          icon: Icons.privacy_tip_rounded,
                          title: '隐私政策',
                          onTap: () => context.push('/legal/privacy'),
                        ),
                      ],
                    ),
                    const SizedBox(height: AppSpacing.xxl),
                    if (appIcpNumber.isNotEmpty)
                      Center(
                        child: Text(appIcpNumber,
                            style: AppText.micro.copyWith(color: AppColors.text3)),
                      ),
                    Center(
                      child: Text('© 2026 $appDisplayName',
                          style: AppText.micro.copyWith(color: AppColors.text3)),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
}
