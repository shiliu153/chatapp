import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_typography.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import '../moderation/models.dart';
import '../moderation/moderation_controller.dart';
import '../moderation/moderation_repository.dart';
import 'widgets/blocked_users_skeleton.dart';
import 'widgets/settings_illustration.dart';
import 'widgets/settings_rows.dart';

/// 黑名单(附录 E,E-5.6b 迁移到 Ember):§9.4 shell + 圆头像列表 + 解除确认。
///
/// 只换皮:解除请求、二次确认与提示文案不变。形态 = 一张分组卡,每行「头像 48 +
/// 昵称 17/w600 + 拉黑日期 13 `text.secondary` + 右侧文字按钮『解除』」。
///
/// 为什么这一组**不**直接用 [`EmberSettingsTile`]:它的左槽只收 `IconData`,而黑名单
/// 行必须显示头像;page spec §3 对这种行给的是「`EmberCard` + `EmberAvatar`」。
/// 给 `EmberSettingsTile` 加头像参数会改公共组件的 API(波及其它页单),本单不做。
class BlockedUsersPage extends ConsumerWidget {
  /// 构造黑名单页。
  const BlockedUsersPage({super.key});

  Future<void> _unblock(
      BuildContext context, WidgetRef ref, BlockedUser user) async {
    final confirmed = await showEmberDialog(
      context,
      icon: PhosphorIconsRegular.userMinus,
      title: '解除对 ${user.nickname} 的拉黑?',
      message: '解除后你们将重新互相可见',
      confirmLabel: '解除',
      confirmKey: const Key('unblock.confirm'),
    );
    if (!confirmed) return;
    try {
      await ref.read(moderationRepositoryProvider).unblock(user.userId);
      await ref.read(blockedUsersProvider.notifier).reload();
      if (context.mounted) EmberToast.show(context, '已解除拉黑');
    } on ApiException catch (error) {
      if (context.mounted) EmberToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final blocked = ref.watch(blockedUsersProvider);
    return EmberPageScaffold(
      title: '黑名单',
      backKey: const Key('blocked.back'),
      body: blocked.when(
        loading: () => const BlockedUsersSkeleton(),
        // §5「加载失败」:EmberEmpty 错误形态 + 「重试」
        error: (error, _) => Center(
          child: Padding(
            padding: EdgeInsets.all(tokens.space24),
            child: EmberEmpty(
              illustration: const SettingsIllustration(
                SettingsIllustrationKind.loadFailed,
              ),
              title: '黑名单没能加载出来',
              description: apiMessageOf(error),
              actionLabel: '重试',
              actionKey: const Key('blocked.retry'),
              onAction: () => ref.read(blockedUsersProvider.notifier).reload(),
            ),
          ),
        ),
        data: (items) => items.isEmpty
            ? Center(
                child: Padding(
                  padding: EdgeInsets.all(tokens.space24),
                  child: EmberEmpty(
                    key: const Key('blocked.empty'),
                    illustration: const SettingsIllustration(
                      SettingsIllustrationKind.listEmpty,
                    ),
                    title: '还没有拉黑任何人',
                    description: '被你拉黑的人不会再出现在发现页',
                  ),
                ),
              )
            : ListView(
                padding: EdgeInsets.only(
                  top: tokens.space12,
                  bottom: tokens.space40 +
                      MediaQuery.viewPaddingOf(context).bottom,
                ),
                children: [
                  SettingsGroup(
                    children: [
                      for (final (index, user) in items.indexed)
                        _BlockedUserRow(
                          key: Key('blocked.row.${user.userId}'),
                          user: user,
                          showDivider: index < items.length - 1,
                          onUnblock: () => _unblock(context, ref, user),
                        ),
                    ],
                  ),
                ],
              ),
      ),
    );
  }
}

/// 黑名单的一行:头像 + 昵称 + 拉黑日期 + 「解除」文字按钮。
class _BlockedUserRow extends StatelessWidget {
  const _BlockedUserRow({
    super.key,
    required this.user,
    required this.showDivider,
    required this.onUnblock,
  });

  final BlockedUser user;
  final bool showDivider;
  final VoidCallback onUnblock;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final avatarUrl = user.avatarUrl;
    final row = Padding(
      padding: settingsRowPadding,
      child: Row(
        children: [
          EmberAvatar(
            image: (avatarUrl == null || avatarUrl.isEmpty)
                ? null
                : NetworkImage(avatarUrl),
            size: EmberComponentSizes.avatarLg,
            name: user.nickname,
          ),
          SizedBox(width: tokens.space12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  user.nickname,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppText.subtitle.copyWith(color: colors.textPrimary),
                ),
                SizedBox(height: tokens.space4),
                Text(
                  _dateLabel(user.blockedAt),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppText.caption.copyWith(color: colors.textSecondary),
                ),
              ],
            ),
          ),
          SizedBox(width: tokens.space12),
          // 「解除」不是破坏性动作(解除的是限制),所以走文字按钮而不是危险变体
          EmberButton(
            key: Key('unblock.${user.userId}'),
            label: '解除',
            variant: EmberButtonVariant.text,
            onPressed: onUnblock,
          ),
        ],
      ),
    );
    if (!showDivider) return row;
    return DecoratedBox(
      decoration: BoxDecoration(
        border: Border(bottom: BorderSide(color: colors.borderDivider, width: 1)),
      ),
      child: row,
    );
  }
}

/// 拉黑时间的展示文案(精确到天;缺时间时只说明「已拉黑」)。
String _dateLabel(DateTime? time) {
  if (time == null) return '已拉黑';
  String two(int value) => value.toString().padLeft(2, '0');
  return '拉黑于 ${time.year}-${two(time.month)}-${two(time.day)}';
}
