import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import '../../core/theme/app_gradients.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/heart_theme_context.dart';
import '../../core/widgets/app_avatar.dart';
import '../../core/widgets/app_badge.dart';
import '../../core/widgets/app_empty_state.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_list_row.dart';
import '../../core/widgets/app_list_skeleton.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_text_action.dart';
import '../../core/widgets/app_toast.dart';
import 'models.dart';
import 'notifications_controller.dart';

/// 站内通知页:列表 + 下拉刷新 + 游标分页 + 全部已读。
///
/// 入口是消息页顶栏的铃铛(带未读角标)。点击一条:先标已读,再按
/// `target.kind` 跳转(`post` → 动态详情;`user` → 与该用户聊天;`none` → 只标已读)。
class NotificationsPage extends ConsumerWidget {
  const NotificationsPage({super.key});

  Future<void> _open(BuildContext context, WidgetRef ref, AppNotification item) async {
    try {
      await ref.read(notificationsProvider.notifier).markRead(item);
    } on ApiException {
      // 标记已读失败不挡跳转:用户点的是内容,已读只是副作用
    }
    if (!context.mounted) return;
    final target = item.target;
    if (target.isPost) {
      context.push('/posts/${target.id}');
    } else if (target.isUser) {
      context.push('/chat/u${target.id}');
    }
  }

  Future<void> _markAll(BuildContext context, WidgetRef ref) async {
    try {
      await ref.read(notificationsProvider.notifier).markAllRead();
    } on ApiException catch (error) {
      if (context.mounted) AppToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = context.heart;
    final state = ref.watch(notificationsProvider);
    final hasUnread = state.value?.hasUnread ?? false;
    return Scaffold(
      backgroundColor: colors.bgPage,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            AppSubPageBar(
              title: '通知',
              trailing: AppTextAction(
                key: const Key('notifications.markAll'),
                label: '全部已读',
                onPressed: hasUnread ? () => _markAll(context, ref) : null,
              ),
            ),
            Expanded(
              child: state.when(
                loading: () =>
                    const AppListSkeleton(key: Key('notifications.skeleton')),
                error: (error, _) => AppErrorView(
                  message: error is ApiException ? error.message : '加载失败,请重试',
                  retryKey: const Key('notifications.retry'),
                  onRetry: () => ref.read(notificationsProvider.notifier).reload(),
                ),
                data: (data) => data.items.isEmpty
                    ? const Center(
                        child: AppEmptyState(
                          key: Key('notifications.empty'),
                          emoji: '🔔',
                          title: '还没有通知',
                          description: '有人赞你、评论你,或者配对成功时,会在这里提醒你',
                        ),
                      )
                    : NotificationListener<ScrollNotification>(
                        onNotification: (notification) {
                          if (notification.metrics.pixels >=
                              notification.metrics.maxScrollExtent - 120) {
                            ref.read(notificationsProvider.notifier).loadMore();
                          }
                          return false;
                        },
                        child: RefreshIndicator(
                          onRefresh: () =>
                              ref.read(notificationsProvider.notifier).reload(),
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
                              return _NotificationRow(
                                item: item,
                                onTap: () => _open(context, ref, item),
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

class _NotificationRow extends StatelessWidget {
  const _NotificationRow({required this.item, required this.onTap});

  final AppNotification item;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final actor = item.actor;
    return AppListRow(
      key: Key('notifications.row.${item.id}'),
      avatar: actor == null
          ? null
          : AppAvatar(
              size: 44,
              imageUrl: actor.avatarUrl,
              fallbackText: actor.nickname,
            ),
      icon: actor == null ? Icons.notifications_rounded : null,
      title: item.text,
      subtitle: formatPostTime(item.createdAt),
      showChevron: false,
      trailing: item.isRead ? null : const _UnreadDot(),
      onTap: onTap,
    );
  }
}

/// 未读点:8×8 心跳渐变圆点(品牌色只出现在引导视线处)。
class _UnreadDot extends StatelessWidget {
  const _UnreadDot();

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    return Padding(
      padding: const EdgeInsets.only(left: AppSpacing.sm),
      child: Container(
        key: const Key('notifications.unreadDot'),
        width: 8,
        height: 8,
        decoration: BoxDecoration(
          gradient: AppGradients.heartOf(colors),
          shape: BoxShape.circle,
        ),
      ),
    );
  }
}

/// 顶栏铃铛 + 未读角标(消息页入口)。
///
/// 单独抽出来是因为消息页与测试都要用:角标数字来自
/// [notificationsUnreadCountProvider],点进去就是通知页。
///
/// 角标是 `FutureProvider`,默认**每 60 秒**重新拉一次(间隔见
/// [notificationsBadgeRefreshIntervalProvider]):本项目不做离线推送,
/// 不轮询的话 App 常驻打开时永远看不到新角标(H 批已知限制,批次 I 补齐)。
class NotificationsBell extends ConsumerStatefulWidget {
  const NotificationsBell({super.key});

  @override
  ConsumerState<NotificationsBell> createState() => _NotificationsBellState();
}

class _NotificationsBellState extends ConsumerState<NotificationsBell> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    final interval = ref.read(notificationsBadgeRefreshIntervalProvider);
    if (interval != null) {
      _timer = Timer.periodic(interval, (_) {
        if (!mounted) return;
        ref.invalidate(notificationsUnreadCountProvider);
      });
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    final unread = ref.watch(notificationsUnreadCountProvider).value ?? 0;
    return Stack(
      clipBehavior: Clip.none,
      children: [
        IconButton(
          key: const Key('chats.notifications'),
          tooltip: '通知',
          onPressed: () => context.push('/notifications'),
          icon: Icon(Icons.notifications_rounded, size: 24, color: colors.text1),
        ),
        if (unread > 0)
          Positioned(
            right: 4,
            top: 4,
            child: IgnorePointer(
              child: AppBadge(count: unread),
            ),
          ),
      ],
    );
  }
}
