import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import '../../core/theme/ember_colors.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import '../chat/widgets/chat_illustration.dart';
import 'models.dart';
import 'notifications_controller.dart';

/// 站内通知页:列表 + 下拉刷新 + 游标分页 + 全部已读(E-5.6d page spec §1 D 组)。
///
/// 入口是消息页顶栏的铃铛(带未读角标)。点击一条:先标已读,再按
/// `target.kind` 跳转(`post` → 动态详情;`user` → 与该用户聊天;`none` → 只标已读)。
///
/// 本单只换视觉与动效,`notifications_controller` / `notifications_repository` 一行没动。
/// 用户看得见的变化(page spec §1 的表):
/// 1. 顶栏换 [`EmberPageScaffold`](§9.4:高 52、返回 22 Phosphor `caret-left`、标题
///    17/w600 居中),「全部已读」从文字动作换 [`EmberButton`] 的文字变体;
/// 2. 列表行换 [`EmberPressable`] + [`EmberAvatar`]:头像 40、正文 17/w600、
///    时间 13 `text.secondary`,行高 68、分隔线 1px `border.divider`(§5.2);
/// 3. 未读点从心跳渐变圆点换 [`EmberBadge`] 的纯圆点形态(`brand.default`,§3.3
///    「品牌色只出现在引导视线处」);
/// 4. 空态 / 错误态换 [`EmberEmpty`] + unDraw 插画(灰色图标占位是 §6 明令禁止的);
/// 5. 骨架换 [`EmberSkeleton`](`surface.sunken` 色块);
/// 6. 反馈从 `AppToast` 换 [`EmberToast`](§9.3 轻量结果反馈)。
class NotificationsPage extends ConsumerWidget {
  /// 构造通知页。
  const NotificationsPage({super.key});

  Future<void> _open(
      BuildContext context, WidgetRef ref, AppNotification item) async {
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
      if (context.mounted) EmberToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(notificationsProvider);
    final hasUnread = state.value?.hasUnread ?? false;
    return EmberPageScaffold(
      title: '通知',
      backKey: const Key('notifications.back'),
      // 列表行要整行铺满(分隔线横贯),横向 20 由行自己给(§5.2 / §9.4)。
      contentPadding: EdgeInsets.zero,
      trailing: EmberButton(
        key: const Key('notifications.markAll'),
        label: '全部已读',
        variant: EmberButtonVariant.text,
        // 没有未读时置灰(§8.3 disabled = 不可点),与改造前的判据一致。
        onPressed: hasUnread ? () => _markAll(context, ref) : null,
      ),
      body: state.when(
        loading: () => const _NotificationsSkeleton(),
        error: (error, _) => _NotificationsError(
          message: error is ApiException ? error.message : '加载失败,请重试',
          onRetry: () => ref.read(notificationsProvider.notifier).reload(),
        ),
        data: (data) => data.items.isEmpty
            ? const _NotificationsEmpty()
            : _NotificationsList(
                items: data.items,
                onTap: (item) => _open(context, ref, item),
                onRefresh: () =>
                    ref.read(notificationsProvider.notifier).reload(),
                onLoadMore: () =>
                    ref.read(notificationsProvider.notifier).loadMore(),
              ),
      ),
    );
  }
}

/// 通知列表:下拉刷新 + 触底翻页。
///
/// 触底翻页沿用改造前的判据(距底 120 内即请求下一页):控制器自己幂等
/// (`loadMore` 在加载中 / 没有下一页时直接返回),这里不需要再做去抖。
class _NotificationsList extends StatelessWidget {
  const _NotificationsList({
    required this.items,
    required this.onTap,
    required this.onRefresh,
    required this.onLoadMore,
  });

  final List<AppNotification> items;
  final ValueChanged<AppNotification> onTap;
  final Future<void> Function() onRefresh;
  final VoidCallback onLoadMore;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return NotificationListener<ScrollNotification>(
      onNotification: (notification) {
        if (notification.metrics.pixels >=
            notification.metrics.maxScrollExtent - 120) {
          onLoadMore();
        }
        return false;
      },
      child: RefreshIndicator(
        backgroundColor: colors.surfaceCard,
        color: colors.brandDefault,
        onRefresh: onRefresh,
        child: ListView.builder(
          key: const Key('notifications.list'),
          physics: const AlwaysScrollableScrollPhysics(),
          padding: EdgeInsets.only(bottom: tokens.space24),
          itemCount: items.length,
          itemBuilder: (context, index) {
            final item = items[index];
            return _NotificationRow(
              item: item,
              onTap: () => onTap(item),
            );
          },
        ),
      ),
    );
  }
}

/// 一行通知:头像(或系统通知图标)+ 正文 + 相对时间 + 未读点。
///
/// 为什么不用 [`EmberSettingsTile`]:那一行的左侧槽只收 `IconData`,通知行要的是
/// **头像**(page spec §3「列表项(通知 / 收藏 / 点赞)」给的两条路里,带缩略图的
/// 列表走自绘行 + `EmberAvatar`);行高、字号、分隔线取值仍与
/// [`EmberSettingsTile`] 对齐(68 / 17-w600 / 13,见 §5.2)。
///
/// 读屏(page spec §6 第 3 条):整行播报「正文,时间」,内部文字与未读点一律
/// `ExcludeSemantics` —— 否则同一段标题会被念两遍。
class _NotificationRow extends StatelessWidget {
  const _NotificationRow({required this.item, required this.onTap});

  final AppNotification item;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final actor = item.actor;
    final time = formatPostTime(item.createdAt);
    final content = Padding(
      padding: EdgeInsets.symmetric(
        horizontal: tokens.space20,
        vertical: tokens.space12,
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          if (actor == null)
            _SystemNoticeAvatar(colors: colors)
          else
            EmberAvatar(
              image: (actor.avatarUrl == null || actor.avatarUrl!.isEmpty)
                  ? null
                  : NetworkImage(actor.avatarUrl!),
              size: EmberComponentSizes.avatarMd,
              name: actor.nickname,
            ),
          SizedBox(width: tokens.space12),
          Expanded(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  item.text,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: tokens.fontSizeSubtitle,
                    fontWeight: FontWeight.w600,
                    height: tokens.fontLineHeightSubtitle,
                    color: colors.textPrimary,
                  ),
                ),
                SizedBox(height: tokens.space4),
                Text(
                  time,
                  style: TextStyle(
                    fontSize: tokens.fontSizeCaption,
                    height: tokens.fontLineHeightCaption,
                    color: colors.textSecondary,
                  ),
                ),
              ],
            ),
          ),
          if (!item.isRead) ...[
            SizedBox(width: tokens.space12),
            // 未读点:8×8 `brand.default`(§3.3 品牌色只出现在引导视线处)。
            // 用 `EmberBadge` 的圆点形态而不是自绘 Container:圆点直径与读屏标签
            // 都由组件层统一给,页面里不再写 8 这个数。
            const EmberBadge(
              key: Key('notifications.unreadDot'),
              count: 1,
              dot: true,
              semanticLabel: '未读',
            ),
          ],
        ],
      ),
    );

    return Semantics(
      container: true,
      button: true,
      label: '${item.text}，$time',
      onTap: onTap,
      child: ExcludeSemantics(
        child: EmberPressable(
          key: Key('notifications.row.${item.id}'),
          onTap: onTap,
          pressedScale: 0.97,
          builder: (context, state) => ColoredBox(
            color: state.pressed ? colors.surfaceSunken : Colors.transparent,
            child: ConstrainedBox(
              // 行高下沿 68(spec §5.2「列表行高 68–76」)。
              constraints: const BoxConstraints(minHeight: _minRowHeight),
              child: DecoratedBox(
                decoration: BoxDecoration(
                  border: Border(
                    bottom: BorderSide(color: colors.borderDivider, width: 1),
                  ),
                ),
                child: content,
              ),
            ),
          ),
        ),
      ),
    );
  }

  /// 行高下沿 68(与 `EmberSettingsTile` 同一口径)。
  static const double _minRowHeight = 68;
}

/// 系统通知(没有触发者)的头像位:40 圆 + Phosphor `bell`。
///
/// 这不是「灰色图标占位」:§6 / §8.3 禁止的是**空态**用灰图标糊弄,而这里是一个
/// 有内容的列表行缺头像,给的是 `surface.sunken` 圆 + `text.secondary` 图标 ——
/// 与 [`EmberAvatar`] 无照片时的柔色底同一档取值。
class _SystemNoticeAvatar extends StatelessWidget {
  const _SystemNoticeAvatar({required this.colors});

  final EmberColors colors;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: EmberComponentSizes.avatarMd,
      height: EmberComponentSizes.avatarMd,
      decoration: BoxDecoration(
        color: colors.surfaceSunken,
        shape: BoxShape.circle,
      ),
      child: Icon(
        PhosphorIconsRegular.bell,
        size: tokens.sizeIcon20,
        color: colors.textSecondary,
      ),
    );
  }
}

/// 空态:还没有任何通知(page spec §5)。
///
/// 插画复用对话线的 unDraw `Chatting`(`assets/illustrations/chat_empty_*.png`):
/// 语义上同为「还没有人找你」,而 `assets/illustrations/` 是**页面组共用**的资产
/// (README 的「用在哪」一列本来就允许一图多处使用)。为什么不新导一张:本单范围
/// 只到 5 个页面文件,新资产要连带动 README 的导出口径,已记入 PR「遗留」。
class _NotificationsEmpty extends StatelessWidget {
  const _NotificationsEmpty();

  @override
  Widget build(BuildContext context) {
    return _CenteredScrollable(
      child: EmberEmpty(
        key: const Key('notifications.empty'),
        illustration: const ChatIllustration(ChatIllustrationKind.emptyThreads),
        title: '还没有通知',
        description: '有人赞你、评论你,或者配对成功时,会在这里提醒你',
      ),
    );
  }
}

/// 加载失败:错误形态 + 重试(page spec §5「加载失败」)。
class _NotificationsError extends StatelessWidget {
  const _NotificationsError({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return _CenteredScrollable(
      child: EmberEmpty(
        illustration: const ChatIllustration(ChatIllustrationKind.loadFailed),
        title: '加载失败',
        description: message,
        actionLabel: '重试',
        actionKey: const Key('notifications.retry'),
        onAction: onRetry,
      ),
    );
  }
}

/// 骨架:6 行「圆头像 + 两行文字」(`surface.sunken` 呼吸,§8.3)。
class _NotificationsSkeleton extends StatelessWidget {
  const _NotificationsSkeleton();

  @override
  Widget build(BuildContext context) {
    return ListView(
      key: const Key('notifications.skeleton'),
      padding: EdgeInsets.symmetric(vertical: tokens.space12),
      children: [
        for (var i = 0; i < 6; i++)
          Padding(
            padding: EdgeInsets.symmetric(
              horizontal: tokens.space20,
              vertical: tokens.space12,
            ),
            child: Row(
              children: [
                const EmberSkeleton(
                  width: EmberComponentSizes.avatarMd,
                  height: EmberComponentSizes.avatarMd,
                  shape: BoxShape.circle,
                ),
                SizedBox(width: tokens.space12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      EmberSkeleton(height: tokens.fontSizeSubtitle),
                      SizedBox(height: tokens.space8),
                      EmberSkeleton(
                        width: 96,
                        height: tokens.fontSizeCaption,
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

/// 空 / 错两态居中且可滚动(小屏 + 大字号的组合下不溢出)。
class _CenteredScrollable extends StatelessWidget {
  const _CenteredScrollable({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: constraints.maxHeight),
          child: Center(
            child: Padding(
              padding: EdgeInsets.all(tokens.space24),
              child: child,
            ),
          ),
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
  /// 构造铃铛入口。
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
    final colors = context.ember;
    final unread = ref.watch(notificationsUnreadCountProvider).value ?? 0;
    return Stack(
      clipBehavior: Clip.none,
      children: [
        EmberPressable(
          key: const Key('chats.notifications'),
          onTap: () => context.push('/notifications'),
          pressedScale: 0.97,
          borderRadius: BorderRadius.circular(tokens.radiusPill),
          // 读屏标签是规范硬要求(§8.4「图标按钮必须有 Semantics(label:)」);
          // 原来靠 `IconButton.tooltip` 顺带给出,换成自绘按压层后要显式给。
          semanticLabel: '通知',
          builder: (context, state) => SizedBox(
            width: tokens.sizeTouchApp,
            height: tokens.sizeTouchApp,
            child: Center(
              child: Icon(
                PhosphorIconsRegular.bell,
                size: tokens.sizeIcon24,
                color: colors.textPrimary,
              ),
            ),
          ),
        ),
        if (unread > 0)
          Positioned(
            right: 4,
            top: 4,
            child: IgnorePointer(
              // 角标数字已由按钮读屏标签 / 通知页承担,这里只出画面不出声。
              child: ExcludeSemantics(child: EmberBadge(count: unread)),
            ),
          ),
      ],
    );
  }
}
