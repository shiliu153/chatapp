import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../profile/models.dart';
import '../profile/profile_controller.dart';

class DiscoveryPage extends ConsumerWidget {
  const DiscoveryPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profile = ref.watch(profileProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('发现')),
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
        data: (data) => data.isComplete
            ? const Center(child: Text('卡片流开发中,下一步就来'))
            : Center(
                child: Card(
                  margin: const EdgeInsets.all(24),
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Text('完善资料后就能开始滑卡'),
                        const SizedBox(height: 8),
                        Text('还差:${data.missingFields.map(missingFieldLabel).join('、')}'),
                        const SizedBox(height: 16),
                        FilledButton(
                          key: const Key('discovery.goOnboarding'),
                          onPressed: () => context.go('/onboarding'),
                          child: const Text('去完善'),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
      ),
    );
  }
}
