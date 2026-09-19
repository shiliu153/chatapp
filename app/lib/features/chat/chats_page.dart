import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_gradients.dart';
import '../../core/theme/app_radius.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_avatar.dart';
import '../../core/widgets/app_badge.dart';
import '../../core/widgets/app_empty_state.dart';
import '../../core/widgets/app_error_view.dart';
import '../../im/im_client.dart';
import '../../im/im_manager.dart';
import '../../im/im_repository.dart';
import '../presence/models.dart';
import '../presence/presence_controller.dart';
import 'conversations_controller.dart';
import 'match_cache.dart';
import 'widgets/chat_bubbles_mark.dart';
import 'widgets/chats_skeleton.dart';

class ChatsPage extends ConsumerWidget {
  const ChatsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(imStatusProvider);
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.pageH, AppSpacing.lg, AppSpacing.pageH, AppSpacing.md),
              child: Text('消息',
                  style: AppText.display.copyWith(color: AppColors.text1)),
            ),
            Expanded(
              child: switch (status) {
                ImConnecting() => const ChatsSkeleton(),
                ImFailed(:final message) => AppErrorView(
                    message: message,
                    retryKey: const Key('chats.retry'),
                    onRetry: () => ref.read(imStatusProvider.notifier).retry(),
                  ),
                _ => const _ConversationList(),
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _ConversationList extends ConsumerWidget {
  const _ConversationList();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final conversations = ref.watch(conversationsProvider);
    final cache = ref.watch(matchCacheProvider).value ?? const <String, MatchEntry>{};
    final presenceById = ref.watch(presenceProvider);
    return conversations.when(
      loading: () => const ChatsSkeleton(),
      error: (error, _) => AppErrorView(
        message: apiMessageOf(error),
        retryKey: const Key('chats.retry'),
        onRetry: () => ref.read(conversationsProvider.notifier).reload(),
      ),
      data: (items) {
        if (items.isEmpty) {
          return const Center(
            child: AppEmptyState(
              mark: ChatBubblesMark(),
              title: '还没有消息',
              description: '互相喜欢之后就能开聊了',
            ),
          );
        }
        ImConversation? system;
        final others = <ImConversation>[];
        for (final item in items) {
          if (item.peerId == systemNoticePeerId) {
            system = item;
          } else {
            others.add(item);
          }
        }
        final ids = <int>[];
        for (final item in others) {
          final uid = userIdFromImId(item.peerId);
          if (uid != null) ids.add(uid);
        }
        ref.read(presenceProvider.notifier).track('chats', ids);
        return Column(
          children: [
            if (others.isNotEmpty)
              _RecentStrip(friends: others, cache: cache, presenceById: presenceById),
            Expanded(
              child: ListView(
                children: [
                  if (system != null) ...[
                    _SystemNoticeTile(conversation: system),
                    Container(height: AppSpacing.sm, color: AppColors.bgPage),
                  ],
                  for (var i = 0; i < others.length; i++) ...[
                    if (i > 0)
                      const Divider(height: 1, thickness: 1, color: AppColors.divider),
                    _ConversationTile(
                        conversation: others[i], cache: cache, presenceById: presenceById),
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

/// 最近联系人横滑条(附录 B.1;不含系统通知)。
class _RecentStrip extends StatelessWidget {
  const _RecentStrip({required this.friends, required this.cache, required this.presenceById});

  final List<ImConversation> friends;
  final Map<String, MatchEntry> cache;
  final Map<int, Presence> presenceById;

  @override
  Widget build(BuildContext context) {
    final recent = friends.take(10).toList();
    return SizedBox(
      height: 88,
      child: ListView.separated(
        key: const Key('chats.strip'),
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(
            AppSpacing.pageH, AppSpacing.xs, AppSpacing.pageH, AppSpacing.md),
        itemCount: recent.length,
        separatorBuilder: (_, _) => const SizedBox(width: 14),
        itemBuilder: (context, index) {
          final conversation = recent[index];
          final name =
              displayNameFor(cache, conversation.peerId, imName: conversation.showName);
          final avatar =
              avatarUrlFor(cache, conversation.peerId, imFaceUrl: conversation.faceUrl);
          final uid = userIdFromImId(conversation.peerId);
          final online = uid != null && (presenceById[uid]?.online ?? false);
          return InkWell(
            key: Key('chats.stripItem:${conversation.peerId}'),
            onTap: () => context.push('/chat/${conversation.peerId}'),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                AppAvatar(
                    imageUrl: avatar,
                    size: 48,
                    showOnlineDot: online,
                    fallbackText: name),
                const SizedBox(height: AppSpacing.xs),
                SizedBox(
                  width: 56,
                  child: Text(
                    name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    textAlign: TextAlign.center,
                    style: AppText.micro.copyWith(color: AppColors.text2),
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

/// 「系统通知」置顶行:官方渐变头像 + 官方标(附录 B.5)。
class _SystemNoticeTile extends StatelessWidget {
  const _SystemNoticeTile({required this.conversation});

  final ImConversation conversation;

  @override
  Widget build(BuildContext context) {
    final last = conversation.lastMessage;
    return ListTile(
      key: const Key('chats.systemNotice'),
      onTap: () => context.push('/chat/${conversation.peerId}'),
      leading: Container(
        width: 48,
        height: 48,
        decoration: const BoxDecoration(
          shape: BoxShape.circle,
          gradient: AppGradients.system,
        ),
        child: const Icon(Icons.notifications_rounded, color: Colors.white, size: 24),
      ),
      title: Row(
        children: [
          Text('系统通知', style: AppText.subtitle),
          const SizedBox(width: AppSpacing.sm),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
            decoration: BoxDecoration(
              border: Border.all(color: AppColors.violet),
              borderRadius: BorderRadius.circular(AppRadius.chip),
            ),
            child: Text('官方',
                style: AppText.micro.copyWith(
                    fontSize: 10,
                    fontWeight: FontWeight.w500,
                    color: AppColors.violet)),
          ),
        ],
      ),
      subtitle: Text(_previewOf(last),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: AppText.caption.copyWith(color: AppColors.text2)),
      trailing: _TimeBadge(last: last, unread: conversation.unreadCount),
    );
  }
}

class _ConversationTile extends StatelessWidget {
  const _ConversationTile(
      {required this.conversation, required this.cache, required this.presenceById});

  final ImConversation conversation;
  final Map<String, MatchEntry> cache;
  final Map<int, Presence> presenceById;

  @override
  Widget build(BuildContext context) {
    final name = displayNameFor(cache, conversation.peerId, imName: conversation.showName);
    final avatar = avatarUrlFor(cache, conversation.peerId, imFaceUrl: conversation.faceUrl);
    final uid = userIdFromImId(conversation.peerId);
    final online = uid != null && (presenceById[uid]?.online ?? false);
    return ListTile(
      key: Key('chats.tile:${conversation.peerId}'),
      onTap: () => context.push('/chat/${conversation.peerId}'),
      leading: AppAvatar(
          imageUrl: avatar, size: 48, showOnlineDot: online, fallbackText: name),
      title: Text(name,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: AppText.subtitle.copyWith(color: AppColors.text1)),
      subtitle: Text(_previewOf(conversation.lastMessage),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: AppText.caption.copyWith(color: AppColors.text2)),
      trailing: _TimeBadge(last: conversation.lastMessage, unread: conversation.unreadCount),
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
              style: AppText.micro.copyWith(color: AppColors.text3),
            ),
          const SizedBox(height: AppSpacing.xs),
          AppBadge(count: unread),
        ],
      );
}

String _previewOf(ChatMessage? last) {
  if (last == null) return '';
  return switch (last.kind) {
    ChatMessageKind.text => last.text,
    ChatMessageKind.matchNotice => last.text.isEmpty ? '你们已互相喜欢,开始聊天吧' : last.text,
    ChatMessageKind.banNotice => last.text.isEmpty ? '系统通知' : last.text,
    ChatMessageKind.image => '[图片]',
    ChatMessageKind.other => '[消息]',
  };
}

