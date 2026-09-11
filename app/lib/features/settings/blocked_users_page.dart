import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_exception.dart';
import '../moderation/models.dart';
import '../moderation/moderation_controller.dart';
import '../moderation/moderation_repository.dart';

class BlockedUsersPage extends ConsumerWidget {
  const BlockedUsersPage({super.key});

  Future<void> _unblock(BuildContext context, WidgetRef ref, BlockedUser user) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('解除对 ${user.nickname} 的拉黑?'),
        content: const Text('解除后你们将重新互相可见'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
          FilledButton(
            key: const Key('unblock.confirm'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('解除'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await ref.read(moderationRepositoryProvider).unblock(user.userId);
      await ref.read(blockedUsersProvider.notifier).reload();
      if (context.mounted) _snack(context, '已解除拉黑');
    } on ApiException catch (error) {
      if (context.mounted) _snack(context, error.message);
    }
  }

  void _snack(BuildContext context, String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final blocked = ref.watch(blockedUsersProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('黑名单')),
      body: blocked.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(error is ApiException ? error.message : '加载失败,请重试'),
              const SizedBox(height: 12),
              FilledButton(
                onPressed: () => ref.read(blockedUsersProvider.notifier).reload(),
                child: const Text('重试'),
              ),
            ],
          ),
        ),
        data: (items) => items.isEmpty
            ? const Center(child: Text('还没有拉黑任何人'))
            : ListView.separated(
                itemCount: items.length,
                separatorBuilder: (_, _) => const Divider(height: 1, indent: 72),
                itemBuilder: (context, index) {
                  final user = items[index];
                  final avatar = user.avatarUrl;
                  return ListTile(
                    leading: CircleAvatar(
                      backgroundImage: avatar == null ? null : NetworkImage(avatar),
                      onBackgroundImageError: avatar == null ? null : (error, stack) {},
                      child: avatar == null ? const Icon(Icons.person) : null,
                    ),
                    title: Text(user.nickname),
                    subtitle: Text(_dateLabel(user.blockedAt)),
                    trailing: TextButton(
                      key: Key('unblock.${user.userId}'),
                      onPressed: () => _unblock(context, ref, user),
                      child: const Text('解除'),
                    ),
                  );
                },
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
