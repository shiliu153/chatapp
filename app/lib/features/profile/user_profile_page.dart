import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../im/im_manager.dart';
import '../chat/conversations_controller.dart';
import '../chat/widgets/photo_viewer.dart';
import '../moderation/models.dart';
import '../moderation/moderation_controller.dart';
import '../moderation/moderation_repository.dart';
import '../moderation/widgets/report_sheet.dart';

class UserProfilePage extends ConsumerWidget {
  const UserProfilePage({super.key, required this.userId});

  final int userId;

  void _snack(BuildContext context, String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _report(BuildContext context, WidgetRef ref) async {
    final result = await showModalBottomSheet<({String type, String detail})>(
      context: context,
      isScrollControlled: true,
      builder: (context) => const ReportSheet(),
    );
    if (result == null) return;
    try {
      await ref.read(moderationRepositoryProvider).report(
          targetUserId: userId, type: result.type, detail: result.detail);
      if (context.mounted) _snack(context, '已收到举报,我们会尽快处理');
    } on ApiException catch (error) {
      if (context.mounted) _snack(context, error.message);
    }
  }

  Future<void> _block(BuildContext context, WidgetRef ref) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('拉黑这位用户?'),
        content: const Text('拉黑后你们将互相不可见,本机聊天记录会被清除'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
          FilledButton(
            key: const Key('user.block.confirm'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('拉黑'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await ref.read(moderationRepositoryProvider).block(userId);
    } on ApiException catch (error) {
      if (context.mounted) _snack(context, error.message);
      return;
    }
    // 黑名单列表是全局缓存的:拉黑后不失效,设置里再打开还是旧列表(2026-09-11 手测 bug)
    ref.invalidate(blockedUsersProvider);
    try {
      // 拉黑已生效,清本机会话只是收尾:失败不打断流程(对方消息已被 IM 黑名单拦)
      await ref.read(imClientProvider).deleteConversation('u$userId');
      await ref.read(conversationsProvider.notifier).reload();
    } catch (_) {}
    if (context.mounted) {
      _snack(context, '已拉黑');
      context.pop();
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profile = ref.watch(userProfileProvider(userId));
    return Scaffold(
      appBar: AppBar(
        title: const Text('详细资料'),
        actions: [
          PopupMenuButton<String>(
            key: const Key('user.more'),
            icon: const Icon(Icons.more_horiz),
            onSelected: (value) =>
                value == 'report' ? _report(context, ref) : _block(context, ref),
            itemBuilder: (context) => const [
              PopupMenuItem(key: Key('user.report'), value: 'report', child: Text('举报')),
              PopupMenuItem(key: Key('user.block'), value: 'block', child: Text('拉黑')),
            ],
          ),
        ],
      ),
      backgroundColor: const Color(0xFFF7F3F5),
      body: profile.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(error is ApiException ? error.message : '加载失败,请重试'),
              const SizedBox(height: 12),
              FilledButton(
                key: const Key('user.retry'),
                onPressed: () => ref.invalidate(userProfileProvider(userId)),
                child: const Text('重试'),
              ),
            ],
          ),
        ),
        data: (data) => _ProfileBody(profile: data),
      ),
    );
  }
}

class _ProfileBody extends StatelessWidget {
  const _ProfileBody({required this.profile});

  final UserProfile profile;

  @override
  Widget build(BuildContext context) {
    final photos = profile.photos.map((photo) => photo.url).toList();
    return ListView(
      padding: const EdgeInsets.only(bottom: 24),
      children: [
        Container(
          color: Colors.white,
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              _SquareAvatar(
                  name: profile.nickname, url: photos.isEmpty ? null : photos.first),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${profile.nickname}'
                      '${profile.age == null ? '' : ' · ${profile.age} 岁'}',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 4),
                    Text('ID:u${profile.userId}',
                        style: const TextStyle(fontSize: 12, color: Color(0xFF999999))),
                  ],
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 8),
        Container(
          color: Colors.white,
          child: Column(
            children: [
              _InfoLine(label: '地区', value: profile.city),
              _InfoLine(label: '个性签名', value: profile.bio),
              _InfoLine(
                  label: '标签', value: profile.tags.map((tag) => tag.name).join(' ')),
            ],
          ),
        ),
        const SizedBox(height: 8),
        Container(
          color: Colors.white,
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('相册', style: TextStyle(fontSize: 13, color: Color(0xFF666666))),
              const SizedBox(height: 10),
              if (photos.isEmpty)
                const Text('还没有照片', style: TextStyle(fontSize: 13, color: Color(0xFF999999)))
              else
                GridView.count(
                  shrinkWrap: true,
                  physics: const NeverScrollableScrollPhysics(),
                  crossAxisCount: 3,
                  mainAxisSpacing: 6,
                  crossAxisSpacing: 6,
                  children: [
                    for (var i = 0; i < photos.length; i++)
                      GestureDetector(
                        key: Key('user.album.photo:$i'),
                        onTap: () =>
                            openPhotoViewer(context, urls: photos, initialIndex: i),
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(4),
                          child: Image.network(
                            photos[i],
                            fit: BoxFit.cover,
                            errorBuilder: (c, e, s) => Container(
                              color: const Color(0xFFEFE3E7),
                              child: const Icon(Icons.image_outlined,
                                  color: Colors.white70),
                            ),
                          ),
                        ),
                      ),
                  ],
                ),
            ],
          ),
        ),
      ],
    );
  }
}

/// 微信「详细资料」式行:标签定宽,取值左对齐。
class _InfoLine extends StatelessWidget {
  const _InfoLine({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final text = value.isEmpty ? '未填' : value;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 13),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: Color(0xFFF5F6F7))),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: 72, child: Text(label, style: const TextStyle(fontSize: 15))),
          Expanded(
            child: Text(text,
                style: const TextStyle(fontSize: 15, color: Color(0xFF888888))),
          ),
        ],
      ),
    );
  }
}

/// 方形圆角头像(微信式);无图显示首字。
class _SquareAvatar extends StatelessWidget {
  const _SquareAvatar({required this.name, this.url});

  final String name;
  final String? url;

  @override
  Widget build(BuildContext context) {
    final image = url;
    final placeholder = Center(
      child: Text(name.isEmpty ? '?' : name.substring(0, 1),
          style: const TextStyle(color: Colors.white, fontSize: 24)),
    );
    return Container(
      width: 56,
      height: 56,
      decoration: BoxDecoration(
        color: const Color(0xFFC9CDD4),
        borderRadius: BorderRadius.circular(8),
      ),
      clipBehavior: Clip.antiAlias,
      child: image == null || image.isEmpty
          ? placeholder
          : Image.network(image, fit: BoxFit.cover,
              errorBuilder: (c, e, s) => placeholder),
    );
  }
}
