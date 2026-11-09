import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/theme/heart_theme_context.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_option_group.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import 'models.dart';
import 'stats_controller.dart';
import 'widgets/stats_cards.dart';
import 'widgets/stats_skeleton.dart';

/// 「我的数据」二级页(批次 P):周 / 月 / 年分段 + 区间标签 + 七张数字卡。
///
/// 只有读:切周期 = 重新请求一次 `GET /api/v1/stats/me`。周期状态与报告分成两个
/// provider,理由见 [StatsPeriodController];这里只负责把它们拼成三态页面。
class StatsPage extends ConsumerWidget {
  const StatsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = context.heart;
    final period = ref.watch(statsPeriodProvider);
    final report = ref.watch(statsReportProvider);
    return Scaffold(
      backgroundColor: colors.bgPage,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            const AppSubPageBar(title: '我的数据'),
            // 分段控件常驻:加载与失败态下也能切周期(否则失败一次就只能退出重进)
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.pageH, AppSpacing.md, AppSpacing.pageH, 0),
              child: AppOptionGroup<StatsPeriod>(
                options: [
                  for (final value in StatsPeriod.values)
                    AppOption(value: value, label: value.label),
                ],
                value: period,
                onChanged: (value) =>
                    ref.read(statsPeriodProvider.notifier).select(value),
              ),
            ),
            Expanded(
              child: report.when(
                loading: () => const StatsSkeleton(),
                error: (error, _) => AppErrorView(
                  message:
                      error is ApiException ? error.message : '加载失败,请重试',
                  retryKey: const Key('stats.retry'),
                  onRetry: () => ref.invalidate(statsReportProvider),
                ),
                data: (data) => ListView(
                  key: const Key('stats.content'),
                  // 底部让开系统手势条(同设置页)
                  padding: EdgeInsets.fromLTRB(
                      AppSpacing.pageH,
                      AppSpacing.md,
                      AppSpacing.pageH,
                      AppSpacing.xxl + MediaQuery.viewPaddingOf(context).bottom),
                  children: [
                    Text(
                      '${data.start} ~ ${data.end}',
                      key: const Key('stats.range'),
                      style: AppText.caption.copyWith(color: colors.text2),
                    ),
                    const SizedBox(height: AppSpacing.cardGap),
                    StatsCards(report: data),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
