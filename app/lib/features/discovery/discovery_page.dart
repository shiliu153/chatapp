import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../chat/match_cache.dart';
import '../profile/models.dart';
import '../profile/profile_controller.dart';
import 'discovery_controller.dart';
import 'models.dart';
import 'widgets/match_overlay.dart';
import 'widgets/swipe_deck.dart';

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
            ? const _DeckView()
            : _IncompleteView(profile: data),
      ),
    );
  }
}

/// 资料不全时不能滑卡,先把人引去向导。
class _IncompleteView extends StatelessWidget {
  const _IncompleteView({required this.profile});

  final Profile profile;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Card(
        margin: const EdgeInsets.all(24),
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text('完善资料后就能开始滑卡'),
              const SizedBox(height: 8),
              Text('还差:${profile.missingFields.map(missingFieldLabel).join('、')}'),
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
    );
  }
}

class _DeckView extends ConsumerWidget {
  const _DeckView();

  Future<bool> _decide(BuildContext context, WidgetRef ref, Candidate candidate,
      {required bool like}) async {
    try {
      final matched =
          await ref.read(discoveryProvider.notifier).decide(candidate, like: like);
      if (matched && context.mounted) {
        final me = ref.read(profileProvider).value;
        ref.invalidate(matchCacheProvider); // 刚配对的人,昵称/头像要立刻能显示
        await showMatchOverlay(
          context,
          candidate: candidate,
          myAvatarUrl: me?.avatar?.url,
          onGoChat: () => context.push('/chat/u${candidate.userId}'),
        );
      }
      return matched;
    } on ApiException catch (error) {
      if (context.mounted) {
        ScaffoldMessenger.of(context)
          ..hideCurrentSnackBar()
          ..showSnackBar(SnackBar(content: Text(error.message)));
      }
      return false;
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final deck = ref.watch(discoveryProvider);
    return deck.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (error, _) => Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('$error'),
            FilledButton(
              onPressed: () => ref.read(discoveryProvider.notifier).reload(),
              child: const Text('重试'),
            ),
          ],
        ),
      ),
      data: (candidates) => candidates.isEmpty
          ? _EmptyView(
              onRefresh: () => ref.read(discoveryProvider.notifier).reload())
          : SwipeDeck(
              candidates: candidates,
              onDecide: (candidate, {required like}) =>
                  _decide(context, ref, candidate, like: like),
            ),
    );
  }
}

class _EmptyView extends StatelessWidget {
  const _EmptyView({required this.onRefresh});

  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.people_outline, size: 48),
          const SizedBox(height: 12),
          const Text('附近暂时没有新的人了'),
          const SizedBox(height: 4),
          const Text('过会儿再来看看吧',
              style: TextStyle(color: Colors.black54, fontSize: 13)),
          const SizedBox(height: 16),
          FilledButton(
            key: const Key('discovery.refresh'),
            onPressed: onRefresh,
            child: const Text('刷新'),
          ),
        ],
      ),
    );
  }
}
