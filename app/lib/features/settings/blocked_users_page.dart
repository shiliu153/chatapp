import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/widgets/app_avatar.dart';
import '../../core/widgets/app_dialog.dart';
import '../../core/widgets/app_empty_state.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_list_row.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_text_action.dart';
import '../../core/widgets/app_toast.dart';
import '../moderation/models.dart';
import '../moderation/moderation_controller.dart';
import '../moderation/moderation_repository.dart';
import 'widgets/blocked_users_skeleton.dart';

/// 黑名单(附录 E):二级页顶栏 + 圆头像列表行 + 解除确认。
class BlockedUsersPage extends ConsumerWidget {
  const BlockedUsersPage({super.key});

  Future<void> _unblock(
      BuildContext context, WidgetRef ref, BlockedUser user) async {
    final confirmed = await showConfirmDialog(
      context,
      title: '解除对 ${user.nickname} 的拉黑?',
      message: '解除后你们将重新互相可见',
      confirmLabel: '解除',
      confirmKey: const Key('unblock.confirm'),
    );
    if (!confirmed) return;
    try {
      await ref.read(moderationRepositoryProvider).unblock(user.userId);
      await ref.read(blockedUsersProvider.notifier).reload();
      if (context.mounted) AppToast.show(context, '已解除拉黑');
    } on ApiException catch (error) {
      if (context.mounted) AppToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final blocked = ref.watch(blockedUsersProvider);
    return Scaffold(
      backgroundColor: AppColors.bgPage,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            const AppSubPageBar(title: '黑名单'),
            Expanded(
              child: blocked.when(
                loading: () => const BlockedUsersSkeleton(),
                error: (error, _) => AppErrorView(
                  message:
                      error is ApiException ? error.message : '加载失败,请重试',
                  retryKey: const Key('blocked.retry'),
                  onRetry: () =>
                      ref.read(blockedUsersProvider.notifier).reload(),
                ),
                data: (items) => items.isEmpty
                    ? const Center(
                        child: AppEmptyState(
                          key: Key('blocked.empty'),
                          emoji: '🙈',
                          title: '还没有拉黑任何人',
                          description: '被你拉黑的人不会再出现在发现页',
                        ),
                      )
                    : ListView.separated(
                        padding:
                            const EdgeInsets.symmetric(vertical: AppSpacing.sm),
                        itemCount: items.length,
                        separatorBuilder: (_, _) => const Divider(
                          height: 1,
                          indent: 72,
                          color: AppColors.divider,
                        ),
                        itemBuilder: (context, index) {
                          final user = items[index];
                          return AppListRow(
                            avatar: AppAvatar(
                              size: 44,
                              imageUrl: user.avatarUrl,
                              fallbackText: user.nickname,
                            ),
                            title: user.nickname,
                            subtitle: _dateLabel(user.blockedAt),
                            trailing: AppTextAction(
                              key: Key('unblock.${user.userId}'),
                              label: '解除',
                              onPressed: () => _unblock(context, ref, user),
                            ),
                          );
                        },
                      ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

String _dateLabel(DateTime? time) {
  if (time == null) return '已拉黑';
  String two(int value) => value.toString().padLeft(2, '0');
  return '拉黑于 ${time.year}-${two(time.month)}-${two(time.day)}';
}
