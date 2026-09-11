import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/format.dart';
import '../../im/im_client.dart';
import '../../im/im_manager.dart';
import '../../im/im_repository.dart';
import 'conversations_controller.dart';
import 'match_cache.dart';

class ChatsPage extends ConsumerWidget {
  const ChatsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(imStatusProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('会话')),
      body: switch (status) {
        ImConnecting() => const Center(child: CircularProgressIndicator()),
        ImFailed(:final message) => _FailedView(message: message),
        _ => const _ConversationList(),
      },
    );
  }
}

class _FailedView extends ConsumerWidget {
  const _FailedView({required this.message});

  final String message;

  @override
  Widget build(BuildContext context, WidgetRef ref) => Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(message),
            const SizedBox(height: 12),
            FilledButton(
              key: const Key('chats.retry'),
              onPressed: () => ref.read(imStatusProvider.notifier).retry(),
              child: const Text('重试'),
            ),
          ],
        ),
      );
}

class _ConversationList extends ConsumerWidget {
  const _ConversationList();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final conversations = ref.watch(conversationsProvider);
    final cache = ref.watch(matchCacheProvider).value ?? const <String, MatchEntry>{};
    return conversations.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (error, _) => Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('$error'),
            const SizedBox(height: 12),
            FilledButton(
              onPressed: () => ref.read(conversationsProvider.notifier).reload(),
              child: const Text('重试'),
            ),
          ],
        ),
      ),
      data: (items) => items.isEmpty
          ? const _EmptyView()
          : ListView.separated(
              itemCount: items.length,
              separatorBuilder: (_, _) => const Divider(height: 1, indent: 72),
              itemBuilder: (context, index) =>
                  _ConversationTile(conversation: items[index], cache: cache),
            ),
    );
  }
}

class _ConversationTile extends StatelessWidget {
  const _ConversationTile({required this.conversation, required this.cache});

  final ImConversation conversation;
  final Map<String, MatchEntry> cache;

  String get _preview {
    final last = conversation.lastMessage;
    if (last == null) return '';
    return switch (last.kind) {
      ChatMessageKind.text => last.text,
      ChatMessageKind.matchNotice => last.text.isEmpty ? '你们已互相喜欢,开始聊天吧' : last.text,
      ChatMessageKind.banNotice => last.text.isEmpty ? '系统通知' : last.text,
      ChatMessageKind.other => '[消息]',
    };
  }

  @override
  Widget build(BuildContext context) {
    final avatar = avatarUrlFor(cache, conversation.peerId, imFaceUrl: conversation.faceUrl);
    final name = displayNameFor(cache, conversation.peerId, imName: conversation.showName);
    final last = conversation.lastMessage;
    return ListTile(
      onTap: () => context.push('/chat/${conversation.peerId}'),
      leading: CircleAvatar(
        backgroundImage: avatar == null ? null : NetworkImage(avatar),
        onBackgroundImageError: avatar == null ? null : (error, stack) {},
        child: avatar == null ? const Icon(Icons.person) : null,
      ),
      title: Text(name, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text(_preview, maxLines: 1, overflow: TextOverflow.ellipsis),
      trailing: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (last != null)
            Text(
              formatMessageTime(DateTime.fromMillisecondsSinceEpoch(last.timestamp)),
              style: const TextStyle(fontSize: 12, color: Colors.black45),
            ),
          const SizedBox(height: 4),
          if (conversation.unreadCount > 0) Badge.count(count: conversation.unreadCount),
        ],
      ),
    );
  }
}

class _EmptyView extends StatelessWidget {
  const _EmptyView();

  @override
  Widget build(BuildContext context) => const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.chat_bubble_outline, size: 48),
            SizedBox(height: 12),
            Text('还没有会话'),
            SizedBox(height: 4),
            Text('互相喜欢之后就能开聊了', style: TextStyle(color: Colors.black54, fontSize: 13)),
          ],
        ),
      );
}
