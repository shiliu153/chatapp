import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import '../../core/theme/heart_theme_context.dart';
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
import '../notifications/notifications_page.dart';
import 'conversation_actions.dart';
import 'conversations_controller.dart';
import 'match_cache.dart';
import 'widgets/chat_bubbles_mark.dart';
import 'widgets/chats_skeleton.dart';

class ChatsPage extends ConsumerWidget {
  const ChatsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = context.heart;
    final status = ref.watch(imStatusProvider);
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.pageH, AppSpacing.lg, AppSpacing.xs, AppSpacing.md),
              child: Row(
                children: [
                  Expanded(
                    child: Text('消息',
                        style: AppText.display.copyWith(color: colors.text1)),
                  ),
                  // 搜索入口:仅支持搜索的实现显示
                  if (ref.read(imClientProvider).capabilities.search)
                    IconButton(
                      key: const Key('chats.search'),
                      tooltip: '搜索聊天记录',
                      onPressed: () => context.push('/search'),
                      icon: Icon(Icons.search_rounded,
                          size: 24, color: colors.text1),
                    ),
                  // 站内通知入口(批次 H):铃铛 + 未读角标,不加底栏 tab
                  const NotificationsBell(),
                ],
              ),
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
    final colors = context.heart;
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
        // 置顶分组(批次 N):顺序由服务端排好(`pinned_at` 倒序在前),客户端只数
        // 出「最前面有几个置顶的」用来插分组标题,绝不自己再排一遍。
        var pinnedCount = 0;
        while (pinnedCount < others.length && others[pinnedCount].pinned) {
          pinnedCount++;
        }
        return Column(
          children: [
            if (others.isNotEmpty)
              _RecentStrip(friends: others, cache: cache, presenceById: presenceById),
            Expanded(
              child: ListView(
                children: [
                  if (system != null) ...[
                    _SystemNoticeTile(conversation: system),
                    Container(height: AppSpacing.sm, color: colors.bgPage),
                  ],
                  for (var i = 0; i < others.length; i++) ...[
                    if (i == 0 && pinnedCount > 0)
                      const _GroupHeader(key: Key('chats.groupHeader.pinned'), label: '置顶'),
                    if (i > 0)
                      Divider(height: 1, thickness: 1, color: colors.divider),
                    _ConversationTile(
                      conversation: others[i],
                      cache: cache,
                      presenceById: presenceById,
                      onLongPress: () => showConversationActions(context, ref, others[i]),
                    ),
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
    final colors = context.heart;
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
                    style: AppText.micro.copyWith(color: colors.text2),
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
    final colors = context.heart;
    final last = conversation.lastMessage;
    return ListTile(
      key: const Key('chats.systemNotice'),
      onTap: () => context.push('/chat/${conversation.peerId}'),
      leading: Container(
        width: 48,
        height: 48,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: AppGradients.systemOf(colors),
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
              border: Border.all(color: colors.violet),
              borderRadius: BorderRadius.circular(AppRadius.chip),
            ),
            child: Text('官方',
                style: AppText.micro.copyWith(
                    fontSize: 10,
                    fontWeight: FontWeight.w500,
                    color: colors.violet)),
          ),
        ],
      ),
      subtitle: Text(_previewOf(last),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: AppText.caption.copyWith(color: colors.text2)),
      trailing: _TimeBadge(
          last: last, unread: conversation.unreadCount, muted: false, peerId: conversation.peerId),
    );
  }
}

class _ConversationTile extends StatelessWidget {
  const _ConversationTile(
      {required this.conversation,
      required this.cache,
      required this.presenceById,
      required this.onLongPress});

  final ImConversation conversation;
  final Map<String, MatchEntry> cache;
  final Map<int, Presence> presenceById;

  /// 长按 → 置顶 / 免打扰 / 删除会话(批次 N,见 conversation_actions.dart)。
  final VoidCallback onLongPress;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    final name = displayNameFor(cache, conversation.peerId, imName: conversation.showName);
    final avatar = avatarUrlFor(cache, conversation.peerId, imFaceUrl: conversation.faceUrl);
    final uid = userIdFromImId(conversation.peerId);
    final online = uid != null && (presenceById[uid]?.online ?? false);
    return ListTile(
      key: Key('chats.tile:${conversation.peerId}'),
      onTap: () => context.push('/chat/${conversation.peerId}'),
      onLongPress: onLongPress,
      leading: AppAvatar(
          imageUrl: avatar, size: 48, showOnlineDot: online, fallbackText: name),
      title: Row(
        children: [
          Flexible(
            child: Text(name,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: AppText.subtitle.copyWith(color: colors.text1)),
          ),
          // 免打扰标记(批次 N):声音关掉了,用静音铃铛代替「有声音」的暗示。
          if (conversation.muted) ...[
            const SizedBox(width: AppSpacing.xs),
            Icon(Icons.notifications_off_rounded,
                key: Key('chats.muted:${conversation.peerId}'),
                size: 16,
                color: colors.text3),
          ],
        ],
      ),
      subtitle: Text(_previewOf(conversation.lastMessage),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: AppText.caption.copyWith(color: colors.text2)),
      trailing: _TimeBadge(
        last: conversation.lastMessage,
        unread: conversation.unreadCount,
        muted: conversation.muted,
        peerId: conversation.peerId,
      ),
    );
  }
}

/// 分组标题(批次 N「置顶」组):13/w600 `text2`,贴左,不用卡片底。
class _GroupHeader extends StatelessWidget {
  const _GroupHeader({super.key, required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          AppSpacing.pageH, AppSpacing.md, AppSpacing.pageH, AppSpacing.xs),
      child: Text(label,
          style: AppText.caption
              .copyWith(color: colors.text2, fontWeight: FontWeight.w600)),
    );
  }
}

class _TimeBadge extends StatelessWidget {
  const _TimeBadge(
      {required this.last, required this.unread, required this.muted, required this.peerId});

  final ChatMessage? last;
  final int unread;
  final bool muted;
  final String peerId;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    // 免打扰的未读只给灰点(批次 N):不显示数字,避免用户以为要立刻处理。
    final showDot = muted && unread > 0;
    return Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (last != null)
            Text(
              formatMessageTime(DateTime.fromMillisecondsSinceEpoch(last!.timestamp)),
              style: AppText.micro.copyWith(color: colors.text3),
            ),
          const SizedBox(height: AppSpacing.xs),
          if (showDot)
            _MutedDot(key: Key('chats.mutedDot:$peerId'))
          else
            AppBadge(count: unread),
        ],
      );
  }
}

/// 免打扰会话的未读灰点:直径 8(§5.3 小场景在线点同档),`text3` 实心圆。
class _MutedDot extends StatelessWidget {
  const _MutedDot({super.key});

  static const _diameter = 8.0;

  @override
  Widget build(BuildContext context) {
    final colors = context.heart;
    return Container(
      width: _diameter,
      height: _diameter,
      decoration: BoxDecoration(color: colors.text3, shape: BoxShape.circle),
    );
  }
}

String _previewOf(ChatMessage? last) {
  if (last == null) return '';
  return switch (last.kind) {
    ChatMessageKind.text => last.text,
    ChatMessageKind.matchNotice => last.text.isEmpty ? '你们已互相喜欢,开始聊天吧' : last.text,
    ChatMessageKind.banNotice => last.text.isEmpty ? '系统通知' : last.text,
    ChatMessageKind.image => '[图片]',
    ChatMessageKind.voice => '[语音]',
    ChatMessageKind.sticker => '[贴纸]',
    ChatMessageKind.other => '[消息]',
  };
}

