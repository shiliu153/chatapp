import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_radius.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_avatar.dart';
import '../../core/widgets/app_card.dart';
import '../../core/widgets/app_error_view.dart';
import 'models.dart';
import 'profile_controller.dart';
import 'widgets/completion_ring.dart';
import 'widgets/profile_skeleton.dart';

/// 资料完善度的总项数:昵称/性别/生日/城市/简介/照片(与后端 missing_fields 同源)。
const _profileFieldCount = 6;

class MyProfilePage extends ConsumerWidget {
  const MyProfilePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profile = ref.watch(profileProvider);
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.pageH, AppSpacing.lg, AppSpacing.pageH, AppSpacing.md),
              child: Text('我的', style: AppText.display.copyWith(color: AppColors.text1)),
            ),
            Expanded(
              child: profile.when(
                loading: () => const ProfileSkeleton(),
                error: (error, _) => AppErrorView(
                  message: apiMessageOf(error),
                  onRetry: () => ref.read(profileProvider.notifier).reload(),
                ),
                data: (data) => _ProfileBody(profile: data),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ProfileBody extends StatelessWidget {
  const _ProfileBody({required this.profile});

  final Profile profile;

  @override
  Widget build(BuildContext context) => ListView(
        padding: const EdgeInsets.fromLTRB(
            AppSpacing.pageH, 0, AppSpacing.pageH, AppSpacing.xxl),
        children: [
          _IdentityCard(profile: profile),
          const SizedBox(height: AppSpacing.md),
          _Group(children: [
            _InfoRow(
              rowKey: 'my.row.gender',
              label: '性别',
              value: _genderLabel(profile.gender),
              onTap: () => context.push('/profile/edit'),
            ),
            _InfoRow(
              rowKey: 'my.row.birthday',
              label: '生日',
              value: profile.birthday ?? '',
              onTap: () => context.push('/profile/edit'),
            ),
            _InfoRow(
              rowKey: 'my.row.city',
              label: '城市',
              value: profile.city,
              onTap: () => context.push('/profile/edit'),
            ),
            _InfoRow(
              rowKey: 'my.row.bio',
              label: '简介',
              value: profile.bio,
              onTap: () => context.push('/profile/edit'),
            ),
            _InfoRow(
              rowKey: 'my.row.tags',
              label: '标签',
              value: profile.tags.map((tag) => tag.name).join('、'),
              onTap: () => context.push('/profile/edit'),
            ),
          ]),
          const SizedBox(height: AppSpacing.md),
          _Group(children: [
            _InfoRow(
              rowKey: 'my.row.posts',
              label: '我的动态',
              icon: Icons.grid_view_rounded,
              onTap: () => context.push('/my-posts'),
            ),
            _InfoRow(
              rowKey: 'my.row.preference',
              label: '想找的人',
              icon: Icons.favorite_rounded,
              onTap: () => context.push('/preference'),
            ),
            _InfoRow(
              rowKey: 'my.row.settings',
              label: '设置',
              icon: Icons.settings_rounded,
              onTap: () => context.push('/settings'),
            ),
          ]),
        ],
      );
}

String _genderLabel(String? gender) => switch (gender) {
      'male' => '男',
      'female' => '女',
      _ => '',
    };

/// 附录 C.2 身份卡:身份区(整段可点进编辑)+ 完成度区(仅资料不完整时)。
/// 分两段是为了避免可点区域嵌套(内层「去完善」不能被外层吞掉)。
class _IdentityCard extends StatelessWidget {
  const _IdentityCard({required this.profile});

  final Profile profile;

  @override
  Widget build(BuildContext context) {
    final missing = profile.missingFields;
    final done = (_profileFieldCount - missing.length).clamp(0, _profileFieldCount);
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          GestureDetector(
            key: const Key('my.card.identity'),
            behavior: HitTestBehavior.opaque,
            onTap: () => context.push('/profile/edit'),
            child: Row(
              children: [
                AppAvatar(
                  imageUrl: profile.avatar?.url,
                  size: 72,
                  fallbackText: profile.nickname,
                ),
                const SizedBox(width: AppSpacing.lg),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        profile.nickname,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppText.title.copyWith(color: AppColors.text1),
                      ),
                      const SizedBox(height: AppSpacing.xs),
                      Text('ID:u${profile.userId}',
                          style: AppText.micro.copyWith(color: AppColors.text3)),
                    ],
                  ),
                ),
              ],
            ),
          ),
          if (missing.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.lg),
            const Divider(height: 1, thickness: 1, color: AppColors.divider),
            const SizedBox(height: AppSpacing.md),
            Row(
              children: [
                CompletionRing(done: done, total: _profileFieldCount),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Text(
                    '还差:${missing.map(missingFieldLabel).join('、')}',
                    style: AppText.caption.copyWith(color: AppColors.text2),
                  ),
                ),
                TextButton(
                  key: const Key('my.goOnboarding'),
                  onPressed: () => context.go('/onboarding'),
                  child: Text('去完善',
                      style: AppText.body
                          .copyWith(color: AppColors.brand, fontWeight: FontWeight.w600)),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

/// 白底分组:组与组之间露出页面底色。
class _Group extends StatelessWidget {
  const _Group({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Container(
        decoration: BoxDecoration(
          color: AppColors.bgCard,
          borderRadius: BorderRadius.circular(AppRadius.card),
        ),
        clipBehavior: Clip.antiAlias,
        child: Column(children: children),
      );
}

/// 附录 C.3 行:标签 13 text2 定宽 72 + 取值 15 text1 + chevron;空值显示「未填」。
class _InfoRow extends StatelessWidget {
  const _InfoRow({
    required this.rowKey,
    required this.label,
    this.value,
    this.icon,
    this.onTap,
  });

  final String rowKey;
  final String label;
  final String? value;
  final IconData? icon;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    // value == null:纯入口行,不显示取值;空串:数据字段未填
    final text = value == null ? '' : (value!.isEmpty ? '未填' : value!);
    final leading = icon;
    return InkWell(
      key: Key(rowKey),
      onTap: onTap,
      child: Container(
        constraints: const BoxConstraints(minHeight: 56),
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
        decoration: const BoxDecoration(
          border: Border(bottom: BorderSide(color: AppColors.divider)),
        ),
        child: Row(
          children: [
            if (leading != null) ...[
              Icon(leading, size: 22, color: AppColors.text2),
              const SizedBox(width: AppSpacing.md),
            ],
            SizedBox(
              width: 72,
              child: Text(label, style: AppText.caption.copyWith(color: AppColors.text2)),
            ),
            Expanded(
              child: Text(
                text,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: AppText.body.copyWith(color: AppColors.text1),
              ),
            ),
            const Icon(Icons.chevron_right_rounded, color: AppColors.text3, size: 20),
          ],
        ),
      ),
    );
  }
}
