import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../im/im_client.dart';
import '../../im/im_repository.dart';
import '../profile/profile_controller.dart';
import 'chat_controller.dart';
import 'chat_items.dart';
import 'conversations_controller.dart';
import 'match_cache.dart';
import 'widgets/message_bubble.dart';

class ChatPage extends ConsumerStatefulWidget {
  const ChatPage({super.key, required this.peerId});

  /// 对方的 IM id,如 'u9'。
  final String peerId;

  @override
  ConsumerState<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends ConsumerState<ChatPage> {
  final _input = TextEditingController();
  bool _sending = false;

  @override
  void dispose() {
    _input.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty || _sending) return;
    setState(() => _sending = true);
    await ref.read(chatProvider(widget.peerId).notifier).send(text);
    _input.clear();
    if (mounted) setState(() => _sending = false);
  }

  void _openProfile(BuildContext context, Map<String, MatchEntry> cache) {
    // 优先用 matches 缓存里的真实 id;缓存没有(如刚被清)就按 u9 → 9 兜底
    final userId =
        cache[widget.peerId]?.userId ?? int.tryParse(widget.peerId.replaceFirst('u', ''));
    if (userId == null) return;
    context.push('/users/$userId');
  }

  /// 标题降级链的第三级:IM 会话名(昵称已由后端同步到 IM 资料)。
  String? _imNameOf(WidgetRef ref) {
    final conversations = ref.watch(conversationsProvider).value;
    if (conversations == null) return null;
    for (final conversation in conversations) {
      if (conversation.peerId == widget.peerId) return conversation.showName;
    }
    return null;
  }

  Future<void> _showMessageMenu(BuildContext context, ChatMessage message) async {
    final renderObject = context.findRenderObject();
    final overlay = Overlay.of(context).context.findRenderObject();
    final position = (renderObject is RenderBox && overlay is RenderBox)
        ? RelativeRect.fromRect(
            Rect.fromPoints(
              renderObject.localToGlobal(Offset.zero, ancestor: overlay),
              renderObject.localToGlobal(renderObject.size.bottomRight(Offset.zero),
                  ancestor: overlay),
            ),
            Offset.zero & overlay.size,
          )
        : RelativeRect.fill;
    final action = await showMenu<String>(
      context: context,
      position: position,
      items: [
        if (message.kind == ChatMessageKind.text)
          const PopupMenuItem(
              key: Key('chat.menu.copy'), value: 'copy', child: Text('复制')),
        const PopupMenuItem(
            key: Key('chat.menu.delete'), value: 'delete', child: Text('删除')),
      ],
    );
    if (action == null || !context.mounted) return;
    if (action == 'copy') {
      await Clipboard.setData(ClipboardData(text: message.text));
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('已复制')));
      }
    } else if (action == 'delete') {
      await ref.read(chatProvider(widget.peerId).notifier).deleteLocal(message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final messages = ref.watch(chatProvider(widget.peerId));
    final cache = ref.watch(matchCacheProvider).value ?? const <String, MatchEntry>{};
    final selfAvatarUrl = ref.watch(profileProvider).value?.avatar?.url;
    final peerName = displayNameFor(cache, widget.peerId, imName: _imNameOf(ref));
    final peerAvatarUrl = avatarUrlFor(cache, widget.peerId);
    return Scaffold(
      appBar: AppBar(
        title: InkWell(
          key: const Key('chat.title'),
          onTap: () => _openProfile(context, cache),
          child: Text(peerName),
        ),
        actions: [
          IconButton(
            key: const Key('chat.more'),
            icon: const Icon(Icons.more_horiz),
            onPressed: () => _openProfile(context, cache),
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: messages.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (error, _) => Center(child: Text('$error')),
              data: (items) {
                if (items.isEmpty) {
                  return const Center(
                      child: Text('打个招呼吧', style: TextStyle(color: Colors.black45)));
                }
                final chatItems = buildChatItems(items);
                return ListView.builder(
                  key: const Key('chat.list'),
                  reverse: true, // 新消息在底部,进来就停在最新一条
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  itemCount: chatItems.length,
                  itemBuilder: (context, index) {
                    final item = chatItems[chatItems.length - 1 - index];
                    return switch (item) {
                      ChatTimeItem(:final label) => _TimeSeparator(label),
                      // Builder 包一层:itemBuilder 的 context 是 sliver,取不到气泡自己的
                      // 渲染对象(长按菜单要定位到气泡)
                      ChatMessageItem(:final message) => Builder(
                          builder: (itemContext) => MessageBubble(
                            message: message,
                            peerName: peerName,
                            peerAvatarUrl: peerAvatarUrl,
                            selfAvatarUrl: selfAvatarUrl,
                            onLongPress: () => _showMessageMenu(itemContext, message),
                            onRetry: () =>
                                ref.read(chatProvider(widget.peerId).notifier).retry(message),
                          ),
                        ),
                    };
                  },
                );
              },
            ),
          ),
          _InputBar(controller: _input, sending: _sending, onSend: _send),
        ],
      ),
    );
  }
}

class _TimeSeparator extends StatelessWidget {
  const _TimeSeparator(this.label);

  final String label;

  @override
  Widget build(BuildContext context) => Padding(
        key: const Key('chat.time'),
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Center(
          child: Text(label,
              style: const TextStyle(fontSize: 11, color: Color(0xFF9AA0A8))),
        ),
      );
}

class _InputBar extends StatelessWidget {
  const _InputBar({required this.controller, required this.sending, required this.onSend});

  final TextEditingController controller;
  final bool sending;
  final VoidCallback onSend;

  @override
  Widget build(BuildContext context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  key: const Key('chat.input'),
                  controller: controller,
                  textInputAction: TextInputAction.send,
                  onSubmitted: (_) => onSend(),
                  decoration: const InputDecoration(
                    hintText: '说点什么…',
                    border: OutlineInputBorder(
                        borderRadius: BorderRadius.all(Radius.circular(24))),
                    contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  ),
                ),
              ),
              IconButton(
                key: const Key('chat.send'),
                onPressed: sending ? null : onSend,
                icon: const Icon(Icons.send),
              ),
            ],
          ),
        ),
      );
}
