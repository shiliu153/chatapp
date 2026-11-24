import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../core/api_exception.dart';
import '../../core/theme/app_typography.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import 'models.dart';
import 'profile_controller.dart';
import 'widgets/completion_ring.dart';
import 'widgets/profile_illustration.dart';
import 'widgets/profile_info_row.dart';
import 'widgets/profile_skeleton.dart';

/// 资料完善度的总项数:昵称/性别/生日/城市/简介/照片(与后端 missing_fields 同源)。
const _profileFieldCount = 6;

/// 「我」tab 的根页(E-5.4 page spec §2:tab 根页面,底栏常驻)。
///
/// 迁移口径:
/// - 身份卡 `EmberCard` + `EmberAvatar` 96;信息分组 `EmberCard` + [ProfileInfoRow]
///   (行高 68–76);标签 `EmberChip`;页面内边距 20;图标 Phosphor;动效 spring。
/// - 业务一行没动:身份卡 / 信息行 / 入口行仍是「点进编辑资料 / 各二级页」,
///   完成度环与「去完善」只在资料不完整时出现(key 与跳转目标全部沿用旧值)。
class MyProfilePage extends ConsumerWidget {
  /// 构造「我」页。
  const MyProfilePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = context.ember;
    final profile = ref.watch(profileProvider);
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: EdgeInsets.fromLTRB(
                tokens.space20,
                tokens.space24,
                tokens.space20,
                tokens.space12,
              ),
              // tab 根页大标题:§4.2 `display` 32 / Fraunces。
              child: Text('我的', style: AppText.display.copyWith(color: colors.textPrimary)),
            ),
            Expanded(
              child: profile.when(
                loading: () => const ProfileSkeleton(),
                // §5「资料加载失败」:EmberEmpty 错误形态 + 「重试」(不用灰色图标)。
                error: (error, _) => Center(
                  child: Padding(
                    padding: EdgeInsets.all(tokens.space24),
                    child: EmberEmpty(
                      illustration: const ProfileIllustration(
                        ProfileIllustrationKind.loadFailed,
                      ),
                      title: '资料没能加载出来',
                      description: apiMessageOf(error),
                      actionLabel: '重试',
                      actionKey: const Key('my.retry'),
                      onAction: () => ref.read(profileProvider.notifier).reload(),
                    ),
                  ),
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

/// 资料正文:身份卡 → 资料分组 → 入口分组。
class _ProfileBody extends StatelessWidget {
  const _ProfileBody({required this.profile});

  final Profile profile;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final tagNames = profile.tags.map((tag) => tag.name).join('、');
    return ListView(
      padding: EdgeInsets.fromLTRB(
        tokens.space20,
        0,
        tokens.space20,
        tokens.space32,
      ),
      children: [
        _IdentityCard(profile: profile),
        SizedBox(height: tokens.space12),
        // 资料分组:标签走 chip 组,其余是「标签 + 取值」两行行
        EmberCard(
          padding: EdgeInsets.zero,
          child: Column(
            children: [
              ProfileInfoRow(
                key: const Key('my.row.gender'),
                label: '性别',
                value: _genderLabel(profile.gender),
                onTap: () => context.push('/profile/edit'),
              ),
              ProfileInfoRow(
                key: const Key('my.row.birthday'),
                label: '生日',
                value: profile.birthday ?? '',
                onTap: () => context.push('/profile/edit'),
              ),
              ProfileInfoRow(
                key: const Key('my.row.city'),
                label: '城市',
                value: profile.city,
                onTap: () => context.push('/profile/edit'),
              ),
              ProfileInfoRow(
                key: const Key('my.row.bio'),
                label: '简介',
                value: profile.bio,
                onTap: () => context.push('/profile/edit'),
              ),
              ProfileInfoRow(
                key: const Key('my.row.tags'),
                label: '标签',
                // 标签用 chip 表达(§8.3 Chip 未选中态),读屏仍读「标签,运动、音乐」。
                value: tagNames,
                showDivider: false,
                onTap: () => context.push('/profile/edit'),
                child: tagNames.isEmpty
                    ? Text(
                        '未填',
                        style: AppText.body.copyWith(color: colors.textSecondary),
                      )
                    : _TagChips(profile: profile),
              ),
            ],
          ),
        ),
        SizedBox(height: tokens.space12),
        // 入口分组:纯入口行(没有「取值」概念,不显示「未填」)
        EmberCard(
          padding: EdgeInsets.zero,
          child: Column(
            children: [
              ProfileInfoRow(
                key: const Key('my.row.posts'),
                label: '我的动态',
                icon: PhosphorIconsRegular.gridFour,
                onTap: () => context.push('/my-posts'),
              ),
              // 收藏与动态并列:都是「我的内容」,只是收藏是私密书签
              ProfileInfoRow(
                key: const Key('my.row.favorites'),
                label: '我的收藏',
                icon: PhosphorIconsRegular.bookmark,
                onTap: () => context.push('/favorites'),
              ),
              ProfileInfoRow(
                key: const Key('my.row.preference'),
                label: '想找的人',
                icon: PhosphorIconsRegular.heart,
                onTap: () => context.push('/preference'),
              ),
              ProfileInfoRow(
                key: const Key('my.row.settings'),
                label: '设置',
                icon: PhosphorIconsRegular.gearSix,
                onTap: () => context.push('/settings'),
                showDivider: false,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// 性别取值的中文口径(后端给 `male` / `female`)。
String _genderLabel(String? gender) => switch (gender) {
      'male' => '男',
      'female' => '女',
      _ => '',
    };

/// 标签 chip 组:未选中态(`surface.sunken` + `text.secondary`),超过一行自动换行。
///
/// 点 chip 等同点这一行进编辑资料 —— chip 自己承担热区(≥48,§8.4),所以父行
/// 不再挂 `onTap`,免得两个可点区域嵌套。
class _TagChips extends StatelessWidget {
  const _TagChips({required this.profile});

  final Profile profile;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: tokens.space8,
      runSpacing: tokens.space8,
      children: [
        for (final tag in profile.tags)
          EmberChip(label: tag.name, onTap: () => context.push('/profile/edit')),
      ],
    );
  }
}

/// 身份卡:`EmberCard` + `EmberAvatar` 96 + 昵称 + ID;资料不完整时下方补完成度区。
///
/// 分两段是为了避免可点区域嵌套(内层「去完善」不能被外层吞掉)。
class _IdentityCard extends StatelessWidget {
  const _IdentityCard({required this.profile});

  final Profile profile;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final missing = profile.missingFields;
    final done = (_profileFieldCount - missing.length).clamp(0, _profileFieldCount);
    final avatarUrl = profile.avatar?.url;
    return EmberCard(
      padding: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          EmberPressable(
            key: const Key('my.card.identity'),
            onTap: () => context.push('/profile/edit'),
            pressedScale: EmberComponentSizes.cardPressedScale,
            borderRadius: BorderRadius.circular(tokens.radiusLg),
            semanticButton: false,
            semanticLabel: '${profile.nickname}，编辑资料',
            builder: (context, state) => Container(
              padding: EdgeInsets.all(tokens.space20),
              color: state.pressed ? colors.surfaceSunken : null,
              child: Row(
                children: [
                  EmberAvatar(
                    image: (avatarUrl == null || avatarUrl.isEmpty)
                        ? null
                        : NetworkImage(avatarUrl),
                    size: EmberComponentSizes.avatarHero,
                    name: profile.nickname,
                  ),
                  SizedBox(width: tokens.space20),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          profile.nickname,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: AppText.title.copyWith(color: colors.textPrimary),
                        ),
                        SizedBox(height: tokens.space4),
                        Text(
                          'ID:u${profile.userId}',
                          style: AppText.micro.copyWith(color: colors.textTertiary),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
          if (missing.isNotEmpty) ...[
            Padding(
              padding: EdgeInsets.symmetric(horizontal: tokens.space20),
              child: Divider(height: 1, thickness: 1, color: colors.borderDivider),
            ),
            Padding(
              padding: EdgeInsets.fromLTRB(
                tokens.space20,
                tokens.space16,
                tokens.space20,
                tokens.space20,
              ),
              child: Row(
                children: [
                  CompletionRing(done: done, total: _profileFieldCount),
                  SizedBox(width: tokens.space12),
                  Expanded(
                    child: Text(
                      '还差:${missing.map(missingFieldLabel).join('、')}',
                      style: AppText.caption.copyWith(color: colors.textSecondary),
                    ),
                  ),
                  SizedBox(width: tokens.space8),
                  // 「去完善」是这张卡唯一该引导的动作(§2「品牌色只出现在引导视线
                  // 处」),所以用主按钮形态;它跳到引导向导(与旧行为一致)。
                  EmberButton(
                    key: const Key('my.goOnboarding'),
                    label: '去完善',
                    variant: EmberButtonVariant.text,
                    onPressed: () => context.go('/onboarding'),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}
