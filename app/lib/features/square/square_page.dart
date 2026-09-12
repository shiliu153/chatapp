import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../chat/widgets/photo_viewer.dart';
import '../profile/profile_controller.dart';
import 'feed_repository.dart';
import 'models.dart';
import 'post_actions.dart';
import 'square_controller.dart';
import 'widgets/post_card.dart';

class SquarePage extends ConsumerStatefulWidget {
  const SquarePage({super.key});

  @override
  ConsumerState<SquarePage> createState() => _SquarePageState();
}

class _SquarePageState extends ConsumerState<SquarePage> {
  final _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.extentAfter < 300) {
        ref.read(squareProvider.notifier).loadMore();
      }
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  void _show(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _toggleLike(Post post) async {
    try {
      await ref.read(squareProvider.notifier).toggleLike(post);
    } on ApiException catch (error) {
      if (mounted) _show(error.message);
    }
  }

  Future<void> _deletePost(Post post) async {
    final confirmed = await confirmDeletePost(context);
    if (!confirmed || !mounted) return;
    try {
      await ref.read(feedRepositoryProvider).deletePost(post.id);
      await ref.read(squareProvider.notifier).reload();
      ref.invalidate(myPostsProvider);
      if (mounted) _show('已删除');
    } on ApiException catch (error) {
      if (mounted) _show(error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final posts = ref.watch(squareProvider);
    final myId = ref.watch(profileProvider).value?.userId;
    return Scaffold(
      appBar: AppBar(title: const Text('广场')),
      backgroundColor: const Color(0xFFF7F3F5),
      floatingActionButton: FloatingActionButton(
        key: const Key('square.fab'),
        onPressed: () => context.push('/posts/compose'),
        child: const Icon(Icons.add),
      ),
      body: posts.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(error is ApiException ? error.message : '加载失败,请重试'),
              const SizedBox(height: 12),
              FilledButton(
                onPressed: () => ref.invalidate(squareProvider),
                child: const Text('重试'),
              ),
            ],
          ),
        ),
        data: (items) => items.isEmpty
            ? Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Text('还没有动态,发一条吧'),
                    const SizedBox(height: 12),
                    FilledButton(
                      key: const Key('square.refresh'),
                      onPressed: () => ref.invalidate(squareProvider),
                      child: const Text('刷新'),
                    ),
                  ],
                ),
              )
            : RefreshIndicator(
                onRefresh: () => ref.read(squareProvider.notifier).reload(),
                child: ListView.separated(
                  key: const Key('square.list'),
                  controller: _scroll,
                  itemCount: items.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 8),
                  itemBuilder: (context, index) {
                    final post = items[index];
                    return PostCard(
                      post: post,
                      isMine: post.author.userId == myId,
                      onToggleLike: () => _toggleLike(post),
                      onTap: () => context.push('/posts/${post.id}'),
                      onOpenImage: (i) =>
                          openPhotoViewer(context, urls: post.images, initialIndex: i),
                      menuAction: (action) => action == 'delete'
                          ? _deletePost(post)
                          : reportPostFromSheet(context, ref, post.id),
                    );
                  },
                ),
              ),
      ),
    );
  }
}
