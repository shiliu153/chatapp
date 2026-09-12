import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../chat/widgets/photo_viewer.dart';
import 'models.dart';
import 'post_actions.dart';
import 'square_controller.dart';
import 'widgets/post_card.dart';

/// 我的动态:自己的全部动态(可删)。
class MyPostsPage extends ConsumerStatefulWidget {
  const MyPostsPage({super.key});

  @override
  ConsumerState<MyPostsPage> createState() => _MyPostsPageState();
}

class _MyPostsPageState extends ConsumerState<MyPostsPage> {
  final _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.extentAfter < 300) {
        ref.read(myPostsProvider.notifier).loadMore();
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

  Future<void> _deletePost(Post post) async {
    final confirmed = await confirmDeletePost(context);
    if (!confirmed || !mounted) return;
    try {
      await ref.read(myPostsProvider.notifier).remove(post.id);
      ref.invalidate(squareProvider);
      if (mounted) _show('已删除');
    } on ApiException catch (error) {
      if (mounted) _show(error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final posts = ref.watch(myPostsProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('我的动态')),
      backgroundColor: const Color(0xFFF7F3F5),
      body: posts.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(
          child: Text(error is ApiException ? error.message : '加载失败,请重试'),
        ),
        data: (items) => items.isEmpty
            ? const Center(child: Text('还没发过动态'))
            : ListView.separated(
                key: const Key('myPosts.list'),
                controller: _scroll,
                itemCount: items.length,
                separatorBuilder: (_, _) => const SizedBox(height: 8),
                itemBuilder: (context, index) {
                  final post = items[index];
                  return PostCard(
                    post: post,
                    isMine: true,
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
    );
  }
}
