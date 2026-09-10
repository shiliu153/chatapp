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
            const SizedBox(height: 16),
            Center(child: _Avatar(profile: data)),
            const SizedBox(height: 12),
            Center(
              child: Text(data.nickname.isEmpty ? '未填昵称' : data.nickname,
                  style: Theme.of(context).textTheme.titleLarge),
            ),
            Center(
              child: Text([
                if (data.age != null) '${data.age} 岁',
                if (data.city.isNotEmpty) data.city,
              ].join(' · ')),
            ),
            if (data.bio.isNotEmpty) ...[
              const SizedBox(height: 8),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 24),
                child: Text(data.bio, textAlign: TextAlign.center),
              ),
            ],
            if (data.tags.isNotEmpty) ...[
              const SizedBox(height: 12),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 24),
                child: Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  alignment: WrapAlignment.center,
                  children: [for (final tag in data.tags) Chip(label: Text(tag.name))],
                ),
              ),
            ],
            if (!data.isComplete) ...[
              const SizedBox(height: 16),
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
            const SizedBox(height: 16),
            const Divider(),
            ListTile(
              leading: const Icon(Icons.edit_outlined),
              title: const Text('编辑资料'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => context.push('/profile/edit'),
            ),
            ListTile(
              leading: const Icon(Icons.favorite_outline),
              title: const Text('想找的人'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => context.push('/preference'),
            ),
            ListTile(
              leading: const Icon(Icons.settings_outlined),
              title: const Text('设置'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => context.push('/settings'),
            ),
          ],
        ),
      ),
    );
  }
}

class _Avatar extends StatelessWidget {
  const _Avatar({required this.profile});

  final Profile profile;

  @override
  Widget build(BuildContext context) {
    final avatar = profile.avatar;
    return CircleAvatar(
      radius: 48,
      backgroundImage: avatar == null ? null : NetworkImage(avatar.url),
      child: avatar == null ? const Icon(Icons.person, size: 48) : null,
    );
  }
}
