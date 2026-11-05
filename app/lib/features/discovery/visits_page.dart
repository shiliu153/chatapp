import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import '../../core/theme/heart_theme_context.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/widgets/app_avatar.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_empty_state.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_list_row.dart';
import '../../core/widgets/app_list_skeleton.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_text_action.dart';
import '../../core/widgets/app_toast.dart';
import '../../core/widgets/heart_ripple.dart';
import '../profile/profile_controller.dart';
import 'models.dart';
import 'visits_controller.dart';
import 'widgets/match_overlay.dart';

/// 「谁看过我」二级页:列表 + 回喜欢 + 四态。
class VisitsPage extends ConsumerWidget {
  const VisitsPage({super.key});

  Future<void> _accept(BuildContext context, WidgetRef ref, Visit item) async {
    try {
      final matched = await ref.read(visitsProvider.notifier).accept(item);
      if (!context.mounted) return;
      if (matched == null) {
        AppToast.show(context, '已喜欢');
        return;
      }
      final me = ref.read(profileProvider).value;
      await showMatchOverlay(
        context,
        candidate: matched.candidate,
        myAvatarUrl: me?.avatar?.url,
        sharedTags: matched.sharedTags,
        myCity: me?.city ?? '',
        onGoChat: () => context.push('/chat/u${matched.candidate.userId}'),
      );
    } on ApiException catch (error) {
      if (context.mounted) AppToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = context.heart;
    final visits = ref.watch(visitsProvider);
    return Scaffold(
      backgroundColor: colors.bgPage,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            const AppSubPageBar(title: '谁看过我'),
            Expanded(
              child: visits.when(
                loading: () => const AppListSkeleton(key: Key('visits.skeleton')),
                error: (error, _) => AppErrorView(
                  message: error is ApiException ? error.message : '加载失败,请重试',
                  retryKey: const Key('visits.retry'),
                  onRetry: () => ref.read(visitsProvider.notifier).reload(),
                ),
                data: (data) => data.items.isEmpty
                    ? Center(
                        child: AppEmptyState(
                          key: const Key('visits.empty'),
                          mark: const HeartRipple(),
                          title: '还没有人看过你',
                          description: '完善资料、多发动态,被看到的机会更多',
                          action: AppButton(
                            key: const Key('visits.goOnboarding'),
                            label: '去完善资料',
                            onPressed: () => context.go('/onboarding'),
                          ),
                        ),
                      )
                    : NotificationListener<ScrollNotification>(
                        onNotification: (notification) {
                          if (notification.metrics.pixels >=
                              notification.metrics.maxScrollExtent - 120) {
                            ref.read(visitsProvider.notifier).loadMore();
                          }
                          return false;
                        },
                        child: RefreshIndicator(
                          onRefresh: () => ref.read(visitsProvider.notifier).reload(),
                          child: ListView.separated(
                            physics: const AlwaysScrollableScrollPhysics(),
                            padding:
                                const EdgeInsets.symmetric(vertical: AppSpacing.sm),
                            itemCount: data.items.length,
                            separatorBuilder: (_, _) => Divider(
                              height: 1,
                              indent: 72,
                              color: colors.divider,
                            ),
                            itemBuilder: (context, index) {
                              final item = data.items[index];
                              return AppListRow(
                                key: Key('visits.row.${item.candidate.userId}'),
                                avatar: AppAvatar(
                                  size: 44,
                                  imageUrl: item.candidate.photos.isEmpty
                                      ? null
                                      : item.candidate.photos.first.url,
                                  fallbackText: item.candidate.nickname,
                                ),
                                title: item.candidate.nickname,
                                subtitle: _subtitle(item),
                                onTap: () =>
                                    context.push('/users/${item.candidate.userId}'),
                                trailing: AppTextAction(
                                  key: Key('visits.accept.${item.candidate.userId}'),
                                  label: data.busyUserId == item.candidate.userId
                                      ? '喜欢中'
                                      : '喜欢',
                                  onPressed: data.busyUserId == item.candidate.userId
                                      ? null
                                      : () => _accept(context, ref, item),
                                ),
                              );
                            },
                          ),
                        ),
                      ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

String _subtitle(Visit item) {
  final candidate = item.candidate;
  final parts = [
    if (candidate.age != null) '${candidate.age} 岁',
    if (candidate.city.isNotEmpty) candidate.city,
    ...candidate.tags.take(3).map((tag) => tag.name),
    formatPostTime(item.visitedAt),
  ];
  return parts.join(' · ');
}
