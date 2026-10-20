import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/widgets/app_avatar.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_empty_state.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_list_row.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_text_action.dart';
import '../../core/widgets/app_toast.dart';
import '../../core/widgets/heart_ripple.dart';
import '../profile/profile_controller.dart';
import 'likes_received_controller.dart';
import 'models.dart';
import 'widgets/likes_skeleton.dart';
import 'widgets/match_overlay.dart';

/// 「喜欢我的人」二级页:列表 + 回喜欢 + 四态。
class LikesReceivedPage extends ConsumerWidget {
  const LikesReceivedPage({super.key});

  Future<void> _accept(BuildContext context, WidgetRef ref, LikeReceived item) async {
    try {
      final matched = await ref.read(likesReceivedProvider.notifier).accept(item);
      if (!context.mounted) return;
      if (matched == null) {
        AppToast.show(context, '已喜欢');
        return;
      }
      final me = ref.read(profileProvider).value;
      await showMatchOverlay(
        context,
        candidate: item.candidate,
        myAvatarUrl: me?.avatar?.url,
        onGoChat: () => context.push('/chat/u${item.candidate.userId}'),
      );
    } on ApiException catch (error) {
      if (context.mounted) AppToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final likes = ref.watch(likesReceivedProvider);
    return Scaffold(
      backgroundColor: AppColors.bgPage,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            const AppSubPageBar(title: '喜欢我的人'),
            Expanded(
              child: likes.when(
                loading: () => const LikesSkeleton(),
                error: (error, _) => AppErrorView(
                  message: error is ApiException ? error.message : '加载失败,请重试',
                  retryKey: const Key('likes.retry'),
                  onRetry: () => ref.read(likesReceivedProvider.notifier).reload(),
                ),
                data: (data) => data.items.isEmpty
                    ? Center(
                        child: AppEmptyState(
                          key: const Key('likes.empty'),
                          mark: const HeartRipple(),
                          title: '还没有人喜欢你',
                          description: '把资料完善一点,多滑几张卡,缘分快到了',
                          action: AppButton(
                            key: const Key('likes.goOnboarding'),
                            label: '去完善资料',
                            onPressed: () => context.go('/onboarding'),
                          ),
                        ),
                      )
                    : NotificationListener<ScrollNotification>(
                        onNotification: (notification) {
                          if (notification.metrics.pixels >=
                              notification.metrics.maxScrollExtent - 120) {
                            ref.read(likesReceivedProvider.notifier).loadMore();
                          }
                          return false;
                        },
                        child: RefreshIndicator(
                          onRefresh: () =>
                              ref.read(likesReceivedProvider.notifier).reload(),
                          child: ListView.separated(
                            physics: const AlwaysScrollableScrollPhysics(),
                            padding:
                                const EdgeInsets.symmetric(vertical: AppSpacing.sm),
                            itemCount: data.items.length,
                            separatorBuilder: (_, _) => const Divider(
                              height: 1,
                              indent: 72,
                              color: AppColors.divider,
                            ),
                            itemBuilder: (context, index) {
                              final item = data.items[index];
                              return AppListRow(
                                key: Key('likes.row.${item.candidate.userId}'),
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
                                  key: Key('likes.accept.${item.candidate.userId}'),
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

String _subtitle(LikeReceived item) {
  final candidate = item.candidate;
  final parts = [
    if (candidate.age != null) '${candidate.age} 岁',
    if (candidate.city.isNotEmpty) candidate.city,
    ...candidate.tags.take(3).map((tag) => tag.name),
    formatPostTime(item.likedAt),
  ];
  return parts.join(' · ');
}
