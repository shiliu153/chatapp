import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:phosphor_glyphs/phosphor_glyphs.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import '../../core/theme/app_typography.dart';
import '../../core/theme/ember_theme_context.dart';
import '../../core/theme/tokens.g.dart' as tokens;
import '../../core/ui/ember_ui.dart';
import '../../im/im_client.dart';
import '../../im/im_manager.dart';
import '../../im/im_repository.dart';
import '../notifications/notifications_page.dart';
import '../presence/models.dart';
import '../presence/presence_controller.dart';
import '../shell/shell_tab.dart';
import 'conversation_actions.dart';
import 'conversations_controller.dart';
import 'draft_store.dart';
import 'match_cache.dart';
import 'widgets/chat_illustration.dart';
import 'widgets/chats_skeleton.dart';
import 'widgets/conversation_tile.dart';

/// 对话 tab 根页面:会话列表(E-5.3 page spec §1 / §3 / §5)。
///
/// 本单只换视觉与动效:`conversations_controller` / `im/` 传输层一行没动。
/// 与心跳期相比,用户看得见的变化(见 page spec §1 的表):
/// 1. 页面水平内边距 16 → **20**(§5.2),标题仍走 `display` 档(Fraunces 32/w700);
/// 2. 会话行自绘(`ConversationTile`):头像 [`EmberAvatar`]、昵称 17/w600(未读 w700)、
///    摘要 13、时间 13、未读 [`EmberBadge`](自绘红点退役);
/// 3. 系统通知的「官方」标从**蓝色渐变**改 `status.info` **单色**(§18.2 删除「系统蓝」);
/// 4. 空态 / 错误态改 [`EmberEmpty`] + unDraw 插画(灰色图标占位是 §6 明令禁止的);
/// 5. 骨架换 [`EmberSkeleton`](`surface.sunken` 色块)。
class ChatsPage extends ConsumerWidget {
  /// 构造页面。
  const ChatsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = context.ember;
    final status = ref.watch(imStatusProvider);
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: EdgeInsets.fromLTRB(
                tokens.space20,
                tokens.space16,
                tokens.space20,
                tokens.space12,
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      '消息',
                      style: AppText.display.copyWith(color: colors.textPrimary),
                    ),
                  ),
                  // 搜索入口:仅支持搜索的实现显示
                  if (ref.read(imClientProvider).capabilities.search)
                    _HeaderIcon(
                      entryKey: const Key('chats.search'),
                      icon: PhosphorIconsRegular.magnifyingGlass,
                      label: '搜索聊天记录',
                      onTap: () => context.push('/search'),
                    ),
                  // 站内通知入口(批次 H):铃铛 + 未读角标,不加底栏 tab
                  const NotificationsBell(),
                ],
              ),
            ),
            Expanded(
              child: switch (status) {
                ImConnecting() => const ChatsSkeleton(),
                ImFailed(:final message) => _ChatsErrorView(
                    message: message,
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

/// 顶栏图标入口:热区 48×48、图标 24(§6 工具栏档 + §8.4 触控),读屏必带标签。
class _HeaderIcon extends StatelessWidget {
  const _HeaderIcon({
    required this.entryKey,
    required this.icon,
    required this.label,
    required this.onTap,
  });

  final Key entryKey;
  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return EmberPressable(
      key: entryKey,
      onTap: onTap,
      pressedScale: 0.97,
      borderRadius: BorderRadius.circular(tokens.radiusPill),
      semanticLabel: label,
      builder: (context, state) => SizedBox(
        width: tokens.sizeTouchApp,
        height: tokens.sizeTouchApp,
        child: Icon(icon, size: tokens.sizeIcon24, color: colors.textPrimary),
      ),
    );
  }
}

class _ConversationList extends ConsumerWidget {
  const _ConversationList();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = context.ember;
    final conversations = ref.watch(conversationsProvider);
    final cache = ref.watch(matchCacheProvider).value ?? const <String, MatchEntry>{};
    final presenceById = ref.watch(presenceProvider);
    // 草稿(批次 T-2):watch 着,输入框里存/删草稿时这一行会跟着变。
    final drafts = ref.watch(draftStoreProvider);
    return conversations.when(
      loading: () => const ChatsSkeleton(),
      error: (error, _) => _ChatsErrorView(
        message: apiMessageOf(error),
        onRetry: () => ref.read(conversationsProvider.notifier).reload(),
      ),
      data: (items) {
        if (items.isEmpty) return const _ChatsEmptyView();
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
                    Divider(height: 1, thickness: 1, color: colors.borderDivider),
                  ],
                  for (var i = 0; i < others.length; i++) ...[
                    if (i == 0 && pinnedCount > 0)
                      const _GroupHeader(
                        key: Key('chats.groupHeader.pinned'),
                        label: '置顶',
                      ),
                    if (i > 0)
                      Divider(height: 1, thickness: 1, color: colors.borderDivider),
                    ConversationTile(
                      key: Key('chats.tile:${others[i].peerId}'),
                      peerId: others[i].peerId,
                      name: displayNameFor(
                        cache,
                        others[i].peerId,
                        imName: others[i].showName,
                      ),
                      avatarUrl: avatarUrlFor(
                        cache,
                        others[i].peerId,
                        imFaceUrl: others[i].faceUrl,
                      ),
                      online: _onlineOf(presenceById, others[i].peerId),
                      // 有草稿就显示草稿原文(行内自己加「[草稿] 」前缀)。
                      preview: (drafts[others[i].peerId] ?? '').trim().isNotEmpty
                          ? drafts[others[i].peerId]!
                          : _previewOf(others[i].lastMessage),
                      draft: (drafts[others[i].peerId] ?? '').trim().isNotEmpty,
                      timeLabel: _timeLabelOf(others[i].lastMessage),
                      unread: others[i].unreadCount,
                      muted: others[i].muted,
                      onTap: () => context.push('/chat/${others[i].peerId}'),
                      onLongPress: () =>
                          showConversationActions(context, ref, others[i]),
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

/// 这个对端是否在线(公开信息,不依赖配对)。
///
/// Args:
///   presenceById: 在线状态表(账号 id → presence)。
///   peerId: 会话对端 IM id(如 `u9`)。
///
/// Returns:
///   在线返回 true。
bool _onlineOf(Map<int, Presence> presenceById, String peerId) {
  final uid = userIdFromImId(peerId);
  return uid != null && (presenceById[uid]?.online ?? false);
}

/// 会话行右上角的时间文案;没有最后一条消息时返回 null。
///
/// Args:
///   last: 会话的最后一条可见消息(可能为 null)。
///
/// Returns:
///   `HH:mm` / `MM-DD` 文案或 null。
String? _timeLabelOf(ChatMessage? last) => last == null
    ? null
    : formatMessageTime(DateTime.fromMillisecondsSinceEpoch(last.timestamp));

/// 最近联系人横滑条(附录 B.1;不含系统通知)。E-5.3 拍板第 4 条:**保留**。
class _RecentStrip extends StatelessWidget {
  const _RecentStrip({
    required this.friends,
    required this.cache,
    required this.presenceById,
  });

  final List<ImConversation> friends;
  final Map<String, MatchEntry> cache;
  final Map<int, Presence> presenceById;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final recent = friends.take(10).toList();
    return SizedBox(
      height: 88,
      child: ListView.separated(
        key: const Key('chats.strip'),
        scrollDirection: Axis.horizontal,
        padding: EdgeInsets.fromLTRB(
          tokens.space20,
          tokens.space4,
          tokens.space20,
          tokens.space12,
        ),
        itemCount: recent.length,
        separatorBuilder: (_, _) => SizedBox(width: tokens.space12),
        itemBuilder: (context, index) {
          final conversation = recent[index];
          final name =
              displayNameFor(cache, conversation.peerId, imName: conversation.showName);
          final avatar =
              avatarUrlFor(cache, conversation.peerId, imFaceUrl: conversation.faceUrl);
          final online = _onlineOf(presenceById, conversation.peerId);
          return EmberPressable(
            key: Key('chats.stripItem:${conversation.peerId}'),
            onTap: () => context.push('/chat/${conversation.peerId}'),
            pressedScale: 0.97,
            borderRadius: BorderRadius.circular(tokens.radiusPill),
            semanticLabel: name,
            builder: (context, state) => Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                EmberAvatar(
                  image: (avatar == null || avatar.isEmpty) ? null : NetworkImage(avatar),
                  size: EmberComponentSizes.avatarLg,
                  name: name,
                  online: online,
                ),
                SizedBox(height: tokens.space4),
                SizedBox(
                  width: 56,
                  child: Text(
                    name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    textAlign: TextAlign.center,
                    textScaler: TextScaler.noScaling,
                    style: AppText.micro.copyWith(color: colors.textSecondary),
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

/// 「系统通知」置顶行:官方标改 `status.info` **单色**(§18.2 删除「系统蓝」),
/// 未读仍走 [`EmberBadge`]。
class _SystemNoticeTile extends StatelessWidget {
  const _SystemNoticeTile({required this.conversation});

  final ImConversation conversation;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    final last = conversation.lastMessage;
    return EmberPressable(
      key: const Key('chats.systemNotice'),
      onTap: () => context.push('/chat/${conversation.peerId}'),
      pressedScale: 0.98,
      semanticLabel: [
        '系统通知',
        if (conversation.unreadCount > 0) '${conversation.unreadCount} 条未读',
      ].join('，'),
      builder: (context, state) => Container(
        height: ConversationTile.rowHeight,
        color: state.pressed ? colors.surfaceSunken : Colors.transparent,
        padding: EdgeInsets.symmetric(horizontal: tokens.space20),
        child: Row(
          children: [
            // 单色官方标:status.info 淡底 + 同色铃铛,不再用渐变头像(§18.2)。
            Container(
              width: EmberComponentSizes.avatarLg,
              height: EmberComponentSizes.avatarLg,
              decoration: BoxDecoration(
                color: colors.statusInfo.withValues(alpha: 0.12),
                shape: BoxShape.circle,
              ),
              child: Icon(
                PhosphorIconsFill.bell,
                color: colors.statusInfo,
                size: tokens.sizeIcon24,
              ),
            ),
            SizedBox(width: tokens.space12),
            Expanded(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(
                        '系统通知',
                        style: AppText.subtitle.copyWith(color: colors.textPrimary),
                      ),
                      SizedBox(width: tokens.space8),
                      // 「官方」标签:1px status.info 描边 + 同色文字(单色标)。
                      Container(
                        padding: EdgeInsets.symmetric(
                          horizontal: tokens.space4,
                          vertical: 1,
                        ),
                        decoration: BoxDecoration(
                          border: Border.all(color: colors.statusInfo),
                          borderRadius: BorderRadius.circular(tokens.radiusXs),
                        ),
                        child: Text(
                          '官方',
                          textScaler: TextScaler.noScaling,
                          style: AppText.micro.copyWith(
                            fontSize: tokens.fontSizeMicro,
                            color: colors.statusInfo,
                          ),
                        ),
                      ),
                    ],
                  ),
                  SizedBox(height: tokens.space4),
                  Text(
                    _previewOf(last),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: AppText.caption.copyWith(color: colors.textSecondary),
                  ),
                ],
              ),
            ),
            SizedBox(width: tokens.space8),
            Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                if (_timeLabelOf(last) != null)
                  Text(
                    _timeLabelOf(last)!,
                    textScaler: TextScaler.noScaling,
                    style: AppText.micro.copyWith(color: colors.textTertiary),
                  ),
                SizedBox(height: tokens.space4),
                ExcludeSemantics(
                  child: EmberBadge(count: conversation.unreadCount),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// 分组标题(批次 N「置顶」组):13/w600 `text.secondary`,贴左,不用卡片底。
class _GroupHeader extends StatelessWidget {
  const _GroupHeader({super.key, required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    final colors = context.ember;
    return Padding(
      padding: EdgeInsets.fromLTRB(
        tokens.space20,
        tokens.space12,
        tokens.space20,
        tokens.space4,
      ),
      child: Text(
        label,
        style: AppText.caption.copyWith(
          color: colors.textSecondary,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

/// 会话列表空态:`EmberEmpty` + unDraw 插画 + 主按钮「去遇见」(page spec §5)。
///
/// 「去遇见」不是路由跳转 —— 四个 tab 是 `HomeShell` 的本地状态下标,所以走
/// `shellTabIndexProvider` 切到发现 tab(不新开路由,也不改导航结构)。
class _ChatsEmptyView extends ConsumerWidget {
  const _ChatsEmptyView();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return _CenteredScrollable(
      child: EmberEmpty(
        illustration: const ChatIllustration(ChatIllustrationKind.emptyThreads),
        title: '还没有对话',
        description: '互相喜欢之后就能开聊了',
        actionLabel: '去遇见',
        actionKey: const Key('chats.goDiscovery'),
        onAction: () =>
            ref.read(shellTabIndexProvider.notifier).select(ShellTab.discovery),
      ),
    );
  }
}

/// 加载失败 / IM 连不上:`EmberEmpty` 错误形态 + 「重试」(page spec §5)。
class _ChatsErrorView extends StatelessWidget {
  const _ChatsErrorView({required this.message, required this.onRetry});

  /// 后端 / IM 给的文案(页面不自己编)。
  final String message;

  /// 重试回调。
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return _CenteredScrollable(
      child: EmberEmpty(
        illustration: const ChatIllustration(ChatIllustrationKind.loadFailed),
        title: '没能加载出来',
        description: message,
        actionLabel: '重试',
        actionKey: const Key('chats.retry'),
        onAction: onRetry,
      ),
    );
  }
}

/// 空 / 错两态的**矮屏包装**:放得下就居中,放不下就能滚。
///
/// 顶部有 48 的标题行、下方有底栏,矮屏(600dp 上下)剩给空态的高度可能不足
/// 「插画 96 + 标题 + 说明 + 主按钮」一整列,直接 `Center` 会抛 `RenderFlex overflowed`。
/// 这是布局兜底,不是视觉的一部分(同 E-5.2 的口径)。
class _CenteredScrollable extends StatelessWidget {
  const _CenteredScrollable({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: constraints.maxHeight),
          child: Center(
            child: Padding(padding: EdgeInsets.all(tokens.space24), child: child),
          ),
        ),
      ),
    );
  }
}

/// 列表行摘要:有草稿就显示草稿(批次 T-2),否则按最后一条消息的类型出文案。
///
/// 草稿走「[草稿] 」前缀而不是替换成同一段灰字:微信口径 —— 一眼能分清
/// 「对方说了这句」和「我还没发出去」。
///
/// Args:
///   last: 会话的最后一条可见消息(可能为 null)。
///
/// Returns:
///   列表行的一句话摘要。
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
