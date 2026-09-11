import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/session.dart';
import '../discovery/discovery_controller.dart';
import '../profile/models.dart';
import '../profile/profile_controller.dart';

/// 重封禁用户看到的整屏提示(替代主框架):原因 + 退出登录。
class BannedPage extends ConsumerWidget {
  const BannedPage({super.key, required this.profile});

  final Profile profile;

  @override
  Widget build(BuildContext context, WidgetRef ref) => Scaffold(
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.block, size: 56, color: Colors.red),
                const SizedBox(height: 16),
                const Text('账号已被封禁',
                    style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
                if (profile.banReason.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Text('原因:${profile.banReason}'),
                ],
                const SizedBox(height: 8),
                const Text('如有疑问请联系客服', style: TextStyle(color: Colors.black54)),
                const SizedBox(height: 24),
                FilledButton(
                  key: const Key('banned.logout'),
                  onPressed: () async {
                    await ref.read(sessionProvider.notifier).logout();
                    ref.invalidate(profileProvider);
                    ref.invalidate(discoveryProvider);
                  },
                  child: const Text('退出登录'),
                ),
              ],
            ),
          ),
        ),
      );
}
