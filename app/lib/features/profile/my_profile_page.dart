import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'models.dart';
import 'profile_controller.dart';

class MyProfilePage extends ConsumerWidget {
  const MyProfilePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profile = ref.watch(profileProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('我的')),
      backgroundColor: const Color(0xFFF7F3F5),
      body: profile.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text('$error'),
              FilledButton(
                onPressed: () => ref.read(profileProvider.notifier).reload(),
                child: const Text('重试'),
              ),
            ],
          ),
        ),
        data: (data) => ListView(
          children: [
            if (!data.isComplete) ...[
              const SizedBox(height: 8),
              Card(
                margin: const EdgeInsets.symmetric(horizontal: 16),
                child: ListTile(
                  leading: const Icon(Icons.error_outline),
                  title: const Text('资料还没完善'),
                  subtitle: Text('还差:${data.missingFields.map(missingFieldLabel).join('、')}'),
                  trailing: FilledButton(
                    key: const Key('my.goOnboarding'),
                    onPressed: () => context.go('/onboarding'),
                    child: const Text('去完善'),
                  ),
                ),
              ),
            ],
            _Group(children: [
              _InfoRow(
                rowKey: 'my.row.avatar',
                label: '头像',
                trailing: _AvatarThumb(profile: data),
                onTap: () => context.push('/profile/edit'),
              ),
              _InfoRow(
                rowKey: 'my.row.nickname',
                label: '昵称',
                value: data.nickname,
                onTap: () => context.push('/profile/edit'),
              ),
              _InfoRow(
                rowKey: 'my.row.id',
                label: 'ID',
                value: 'u${data.id}',
                onTap: () => context.push('/profile/edit'),
              ),
              _InfoRow(
                rowKey: 'my.row.gender',
                label: '性别',
                value: _genderLabel(data.gender),
                onTap: () => context.push('/profile/edit'),
              ),
              _InfoRow(
                rowKey: 'my.row.birthday',
                label: '生日',
                value: data.birthday ?? '',
                onTap: () => context.push('/profile/edit'),
              ),
              _InfoRow(
                rowKey: 'my.row.city',
                label: '城市',
                value: data.city,
                onTap: () => context.push('/profile/edit'),
              ),
              _InfoRow(
                rowKey: 'my.row.bio',
                label: '简介',
                value: data.bio,
                onTap: () => context.push('/profile/edit'),
              ),
              _InfoRow(
                rowKey: 'my.row.tags',
                label: '标签',
                value: data.tags.map((tag) => tag.name).join('、'),
                onTap: () => context.push('/profile/edit'),
              ),
            ]),
            _Group(children: [
              _InfoRow(
                rowKey: 'my.row.preference',
                label: '想找的人',
                onTap: () => context.push('/preference'),
              ),
              _InfoRow(
                rowKey: 'my.row.settings',
                label: '设置',
                onTap: () => context.push('/settings'),
              ),
            ]),
          ],
        ),
      ),
    );
  }
}

String _genderLabel(String? gender) => switch (gender) {
      'male' => '男',
      'female' => '女',
      _ => '',
    };

/// 白底分组:组与组之间露出页面底色。
class _Group extends StatelessWidget {
  const _Group({required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.only(top: 8),
        color: Colors.white,
        child: Column(children: children),
      );
}

/// 微信「个人信息」式行:标签列定宽,取值左对齐,`›` 固定最右;空值显示「未填」。
class _InfoRow extends StatelessWidget {
  const _InfoRow({
    required this.rowKey,
    required this.label,
    this.value,
    this.trailing,
    this.onTap,
  });

  final String rowKey;
  final String label;
  final String? value;
  final Widget? trailing;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    // value == null:纯入口行(头像/想找的人/设置),不显示取值;空串:数据字段未填
    final text = value == null ? '' : (value!.isEmpty ? '未填' : value!);
    return InkWell(
      key: Key(rowKey),
      onTap: onTap,
      child: Container(
        constraints: const BoxConstraints(minHeight: 48),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
        decoration: const BoxDecoration(
          border: Border(bottom: BorderSide(color: Color(0xFFF5F6F7))),
        ),
        child: Row(
          children: [
            SizedBox(width: 72, child: Text(label, style: const TextStyle(fontSize: 15))),
            Expanded(
              child: Text(
                text,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 15, color: Color(0xFF888888)),
              ),
            ),
            ?trailing,
            const Icon(Icons.chevron_right, color: Color(0xFFC0C0C0), size: 20),
          ],
        ),
      ),
    );
  }
}

/// 头像行右侧的小方图(微信式)。
class _AvatarThumb extends StatelessWidget {
  const _AvatarThumb({required this.profile});

  final Profile profile;

  @override
  Widget build(BuildContext context) {
    final avatar = profile.avatar;
    const placeholder = Icon(Icons.person, color: Colors.white, size: 22);
    return Container(
      width: 38,
      height: 38,
      decoration: BoxDecoration(
        color: const Color(0xFFF3B8C8),
        borderRadius: BorderRadius.circular(6),
      ),
      clipBehavior: Clip.antiAlias,
      child: avatar == null
          ? placeholder
          : Image.network(avatar.url, fit: BoxFit.cover,
              errorBuilder: (c, e, s) => placeholder),
    );
  }
}
