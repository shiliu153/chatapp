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
      body: SafeArea(
        child: Column(
          children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(16, 10, 16, 8),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text('消息',
                    style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
              ),
            ),
            Expanded(
              child: switch (status) {
                ImConnecting() => const Center(child: CircularProgressIndicator()),
                ImFailed(:final message) => _FailedView(message: message),
                _ => const _ConversationList(),
              },
            ),
          ],
        ),
      ),
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
      data: (items) {
        if (items.isEmpty) return const _EmptyView();
        ImConversation? system;
        final others = <ImConversation>[];
        for (final item in items) {
          if (item.peerId == systemNoticePeerId) {
            system = item;
          } else {
            others.add(item);
          }
        }
        return Column(
          children: [
            if (others.isNotEmpty) _RecentStrip(friends: others, cache: cache),
            Expanded(
              child: ListView(
                children: [
                  if (system != null) ...[
                    _SystemNoticeTile(conversation: system),
                    Container(height: 8, color: const Color(0xFFF7F8FA)),
                  ],
                  for (var i = 0; i < others.length; i++) ...[
                    if (i > 0)
                      const Divider(height: 1, thickness: 1, color: Color(0xFFF5F6F7)),
                    _ConversationTile(conversation: others[i], cache: cache),
                  ],
                ],
              ),
            ),
          ],
        );
      },
    );
  }
}

/// 最近联系人横滑条(抖音式;不含系统通知)。
class _RecentStrip extends StatelessWidget {
  const _RecentStrip({required this.friends, required this.cache});

  final List<ImConversation> friends;
  final Map<String, MatchEntry> cache;

  @override
  Widget build(BuildContext context) {
    final recent = friends.take(10).toList();
    return SizedBox(
      height: 84,
      child: ListView.separated(
        key: const Key('chats.strip'),
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 6),
        itemCount: recent.length,
        separatorBuilder: (_, _) => const SizedBox(width: 14),
        itemBuilder: (context, index) {
          final conversation = recent[index];
          final name =
              displayNameFor(cache, conversation.peerId, imName: conversation.showName);
          final avatar =
              avatarUrlFor(cache, conversation.peerId, imFaceUrl: conversation.faceUrl);
          return InkWell(
            key: Key('chats.stripItem:${conversation.peerId}'),
            onTap: () => context.push('/chat/${conversation.peerId}'),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                _Avatar(name: name, url: avatar, size: 48),
                const SizedBox(height: 4),
                SizedBox(
                  width: 56,
                  child: Text(
                    name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 11, color: Color(0xFF555B63)),
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

/// 「系统通知」置顶行:蓝底铃铛 + 官方标。
class _SystemNoticeTile extends StatelessWidget {
  const _SystemNoticeTile({required this.conversation});

  final ImConversation conversation;

  @override
  Widget build(BuildContext context) {
    final last = conversation.lastMessage;
    return ListTile(
      key: const Key('chats.systemNotice'),
      onTap: () => context.push('/chat/${conversation.peerId}'),
      leading: const CircleAvatar(
        radius: 24,
        backgroundColor: Color(0xFFE8F0FE),
        child: Icon(Icons.notifications_none, color: Color(0xFF2C7BE5)),
      ),
      title: Row(
        children: [
          const Text('系统通知',
              style: TextStyle(fontSize: 15.5, fontWeight: FontWeight.w600)),
          const SizedBox(width: 6),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 3),
            decoration: BoxDecoration(
              border: Border.all(color: const Color(0xFF2C7BE5)),
              borderRadius: BorderRadius.circular(3),
            ),
            child: const Text('官方',
                style: TextStyle(fontSize: 10, color: Color(0xFF2C7BE5))),
          ),
        ],
      ),
      subtitle: Text(_previewOf(last),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(fontSize: 13, color: Color(0xFF8A8F98))),
      trailing: _TimeBadge(last: last, unread: conversation.unreadCount),
    );
  }
}

class _ConversationTile extends StatelessWidget {
  const _ConversationTile({required this.conversation, required this.cache});

  final ImConversation conversation;
  final Map<String, MatchEntry> cache;

  @override
  Widget build(BuildContext context) {
    final name = displayNameFor(cache, conversation.peerId, imName: conversation.showName);
    final avatar = avatarUrlFor(cache, conversation.peerId, imFaceUrl: conversation.faceUrl);
    return ListTile(
      key: Key('chats.tile:${conversation.peerId}'),
      onTap: () => context.push('/chat/${conversation.peerId}'),
      leading: _Avatar(name: name, url: avatar),
      title: Text(name,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(fontSize: 15.5, fontWeight: FontWeight.w600)),
      subtitle: Text(_previewOf(conversation.lastMessage),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(fontSize: 13, color: Color(0xFF8A8F98))),
      trailing: _TimeBadge(last: conversation.lastMessage, unread: conversation.unreadCount),
    );
  }
}

/// 圆头像:有图用图(失败静默),没图用昵称首字。
class _Avatar extends StatelessWidget {
  const _Avatar({required this.name, this.url, this.size = 48});

  final String name;
  final String? url;
  final double size;

  @override
  Widget build(BuildContext context) {
    final radius = size / 2;
    if (url != null && url!.isNotEmpty) {
      return CircleAvatar(
        radius: radius,
        backgroundImage: NetworkImage(url!),
        onBackgroundImageError: (error, stack) {},
      );
    }
    return CircleAvatar(
      radius: radius,
      backgroundColor: const Color(0xFFD6E8FF),
      child: Text(
        name.isEmpty ? '?' : name.substring(0, 1),
        style: TextStyle(
            fontSize: size * 0.38,
            fontWeight: FontWeight.w600,
            color: const Color(0xFF40454C)),
      ),
    );
  }
}

class _TimeBadge extends StatelessWidget {
  const _TimeBadge({required this.last, required this.unread});

  final ChatMessage? last;
  final int unread;

  @override
  Widget build(BuildContext context) => Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (last != null)
            Text(
              formatMessageTime(DateTime.fromMillisecondsSinceEpoch(last!.timestamp)),
              style: const TextStyle(fontSize: 11, color: Color(0xFF9AA0A8)),
            ),
          const SizedBox(height: 4),
          _UnreadBadge(count: unread),
        ],
      );
}

class _UnreadBadge extends StatelessWidget {
  const _UnreadBadge({required this.count});

  final int count;

  @override
  Widget build(BuildContext context) => count <= 0
      ? const SizedBox(height: 17)
      : Container(
          height: 17,
          padding: const EdgeInsets.symmetric(horizontal: 5),
          constraints: const BoxConstraints(minWidth: 17),
          decoration: BoxDecoration(
            color: const Color(0xFFFF2C55),
            borderRadius: BorderRadius.circular(9),
          ),
          // 不用 Container 的 alignment:有界约束下它会撑满整格宽(ListTile trailing 断言)
          child: Center(
            widthFactor: 1,
            child: Text('$count',
                style: const TextStyle(color: Colors.white, fontSize: 11)),
          ),
        );
}

String _previewOf(ChatMessage? last) {
  if (last == null) return '';
  return switch (last.kind) {
    ChatMessageKind.text => last.text,
    ChatMessageKind.matchNotice => last.text.isEmpty ? '你们已互相喜欢,开始聊天吧' : last.text,
    ChatMessageKind.banNotice => last.text.isEmpty ? '系统通知' : last.text,
    ChatMessageKind.other => '[消息]',
  };
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
            Text('还没有消息'),
            SizedBox(height: 4),
            Text('互相喜欢之后就能开聊了', style: TextStyle(color: Colors.black54, fontSize: 13)),
          ],
        ),
      );
}
