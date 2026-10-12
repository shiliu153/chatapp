import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_radius.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_card.dart';
import '../../core/widgets/app_error_view.dart';
import '../../im/im_manager.dart';
import '../chat/conversations_controller.dart';
import '../chat/widgets/photo_viewer.dart';
import '../moderation/models.dart';
import '../moderation/moderation_controller.dart';
import '../moderation/moderation_repository.dart';
import '../moderation/widgets/report_sheet.dart';
import '../presence/presence_controller.dart';
import 'widgets/profile_photo_header.dart';
import 'widgets/user_profile_skeleton.dart';

class UserProfilePage extends ConsumerWidget {
  const UserProfilePage({super.key, required this.userId, this.heroTag});

  final int userId;

  /// Hero tag(附录 C.7);来自路由 extra。null(深链/无来源)时不包 Hero。
  final String? heroTag;

  void _snack(BuildContext context, String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _report(BuildContext context, WidgetRef ref) async {
    final result = await showModalBottomSheet<({String type, String detail})>(
      context: context,
      isScrollControlled: true,
      builder: (context) => const ReportSheet(),
    );
    if (result == null) return;
    try {
      await ref.read(moderationRepositoryProvider).report(
          targetUserId: userId, type: result.type, detail: result.detail);
      if (context.mounted) _snack(context, '已收到举报,我们会尽快处理');
    } on ApiException catch (error) {
      if (context.mounted) _snack(context, error.message);
    }
  }

  Future<void> _block(BuildContext context, WidgetRef ref) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('拉黑这位用户?'),
        content: const Text('拉黑后你们将互相不可见,本机聊天记录会被清除'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
          FilledButton(
            key: const Key('user.block.confirm'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('拉黑'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await ref.read(moderationRepositoryProvider).block(userId);
    } on ApiException catch (error) {
      if (context.mounted) _snack(context, error.message);
      return;
    }
    // 黑名单列表是全局缓存的:拉黑后不失效,设置里再打开还是旧列表(2026-09-11 手测 bug)
    ref.invalidate(blockedUsersProvider);
    try {
      // 拉黑已生效,清本机会话只是收尾:失败不打断流程(对方消息已被 IM 黑名单拦)
      await ref.read(imClientProvider).deleteConversation('u$userId');
      await ref.read(conversationsProvider.notifier).reload();
    } catch (_) {}
    if (context.mounted) {
      _snack(context, '已拉黑');
      context.pop();
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profile = ref.watch(userProfileProvider(userId));
    // 在线状态是公开信息(不依赖配对):与广场/动态详情同款写法
    ref.read(presenceProvider.notifier).track('user:$userId', [userId]);
    final online = ref.watch(presenceProvider)[userId]?.online ?? false;
    return Scaffold(
      body: profile.when(
        loading: () => const UserProfileSkeleton(),
        error: (error, _) => SafeArea(
          child: AppErrorView(
            message: apiMessageOf(error),
            retryKey: const Key('user.retry'),
            onRetry: () => ref.invalidate(userProfileProvider(userId)),
          ),
        ),
        data: (data) => _ProfileBody(
          profile: data,
          heroTag: heroTag,
          online: online,
          onBack: () => Navigator.of(context).maybePop(),
          onMore: (value) =>
              value == 'report' ? _report(context, ref) : _block(context, ref),
        ),
      ),
    );
  }
}

class _ProfileBody extends StatelessWidget {
  const _ProfileBody({
    required this.profile,
    required this.heroTag,
    required this.online,
    required this.onBack,
    required this.onMore,
  });

  final UserProfile profile;
  final String? heroTag;
  final bool online;
  final VoidCallback onBack;
  final ValueChanged<String> onMore;

  static const _topBarHeight = 52.0; // §5.2 二级页

  @override
  Widget build(BuildContext context) {
    final photos = profile.photos.map((photo) => photo.url).toList();
    return Stack(
      children: [
        ListView(
          padding: EdgeInsets.zero,
          children: [
            ProfilePhotoHeader(
              photoUrl: photos.isEmpty ? null : photos.first,
              nickname: profile.nickname,
              age: profile.age,
              city: profile.city,
              online: online,
              heroTag: heroTag,
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.pageH, AppSpacing.md, AppSpacing.pageH, AppSpacing.xxl),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  AppCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('ID:u${profile.userId}',
                            style: AppText.micro.copyWith(color: AppColors.text3)),
                        const SizedBox(height: AppSpacing.md),
                        _LabeledBlock(label: '个性签名', value: profile.bio),
                        if (profile.tags.isNotEmpty) ...[
                          const SizedBox(height: AppSpacing.lg),
                          // 纯标签用 _FieldLabel:不能用 _LabeledBlock(它会在空值时补「未填」)
                          const _FieldLabel(label: '标签'),
                          const SizedBox(height: AppSpacing.sm),
                          Wrap(
                            spacing: AppSpacing.sm,
                            runSpacing: AppSpacing.sm,
                            children: [
                              for (final tag in profile.tags)
                                Container(
                                  padding: const EdgeInsets.symmetric(
                                      horizontal: AppSpacing.sm, vertical: 3),
                                  decoration: BoxDecoration(
                                    color: AppColors.divider,
                                    borderRadius: BorderRadius.circular(AppRadius.chip),
                                  ),
                                  child: Text(tag.name,
                                      style:
                                          AppText.micro.copyWith(color: AppColors.text1)),
                                ),
                            ],
                          ),
                        ],
                      ],
                    ),
                  ),
                  if (photos.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.md),
                    AppCard(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const _FieldLabel(label: '相册'),
                          const SizedBox(height: AppSpacing.md),
                          GridView.count(
                            shrinkWrap: true,
                            physics: const NeverScrollableScrollPhysics(),
                            crossAxisCount: 3,
                            mainAxisSpacing: AppSpacing.sm,
                            crossAxisSpacing: AppSpacing.sm,
                            children: [
                              for (var i = 0; i < photos.length; i++)
                                GestureDetector(
                                  key: Key('user.album.photo:$i'),
                                  onTap: () => openPhotoViewer(context,
                                      urls: photos, initialIndex: i),
                                  child: ClipRRect(
                                    borderRadius: BorderRadius.circular(AppRadius.image),
                                    child: Image.network(
                                      photos[i],
                                      fit: BoxFit.cover,
                                      errorBuilder: (c, e, s) => const ColoredBox(
                                        color: AppColors.divider,
                                        child: Icon(Icons.image_rounded,
                                            color: AppColors.text3),
                                      ),
                                    ),
                                  ),
                                ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
        // 透明顶栏浮在照片上(附录 C.5)
        SafeArea(
          bottom: false,
          child: SizedBox(
            height: _topBarHeight,
            child: Row(
              children: [
                IconButton(
                  key: const Key('user.back'),
                  onPressed: onBack,
                  icon: const Icon(Icons.arrow_back_ios_new_rounded,
                      size: 22, color: Colors.white),
                ),
                const Spacer(),
                PopupMenuButton<String>(
                  key: const Key('user.more'),
                  icon: const Icon(Icons.more_horiz_rounded, size: 24, color: Colors.white),
                  onSelected: onMore,
                  itemBuilder: (context) => const [
                    PopupMenuItem(key: Key('user.report'), value: 'report', child: Text('举报')),
                    PopupMenuItem(key: Key('user.block'), value: 'block', child: Text('拉黑')),
                  ],
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

/// 白卡里的「标签 + 取值」块;取值为空显示「未填」。
class _LabeledBlock extends StatelessWidget {
  const _LabeledBlock({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _FieldLabel(label: label),
          const SizedBox(height: AppSpacing.xs),
          Text(value.isEmpty ? '未填' : value,
              style: AppText.body.copyWith(color: AppColors.text1)),
        ],
      );
}

/// 只有标签、内容自带渲染的块(如标签 chip 组):**不会**在空值时补「未填」。
class _FieldLabel extends StatelessWidget {
  const _FieldLabel({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) =>
      Text(label, style: AppText.caption.copyWith(color: AppColors.text2));
}
