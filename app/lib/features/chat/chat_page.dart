import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/image_pick.dart';
import '../../im/im_client.dart';
import '../../im/im_repository.dart';
import '../presence/models.dart';
import '../presence/presence_controller.dart';
import '../profile/profile_controller.dart';
import 'chat_controller.dart';
import 'chat_items.dart';
import 'conversations_controller.dart';
import 'match_cache.dart';
import 'widgets/emoji_panel.dart';
import 'widgets/message_bubble.dart';
import 'widgets/more_panel.dart';
import 'widgets/photo_viewer.dart';

class ChatPage extends ConsumerStatefulWidget {
  const ChatPage({super.key, required this.peerId, this.pickImage = pickImageFromGallery});

  /// 对方的 IM id,如 'u9'。
  final String peerId;

  /// 相册选图(测试注入用)。
  final PickImage pickImage;

  @override
  ConsumerState<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends ConsumerState<ChatPage> {
  final _input = TextEditingController();
  final _focusNode = FocusNode();
  bool _sending = false;
  bool _showEmoji = false;
  bool _showMore = false;

  @override
  void initState() {
    super.initState();
    // 键盘弹起时收起表情/＋面板
    _focusNode.addListener(() {
      if (_focusNode.hasFocus && (_showEmoji || _showMore)) {
        setState(() {
          _showEmoji = false;
          _showMore = false;
        });
      }
    });
  }

  @override
  void dispose() {
    _input.dispose();
    _focusNode.dispose();
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

  void _toggleEmoji() {
    setState(() {
      _showEmoji = !_showEmoji;
      _showMore = false;
    });
    if (_showEmoji) FocusScope.of(context).unfocus();
  }

  void _toggleMore() {
    setState(() {
      _showMore = !_showMore;
      _showEmoji = false;
    });
    if (_showMore) FocusScope.of(context).unfocus();
  }

  void _insertEmoji(String emoji) {
    final selection = _input.selection;
    final start = selection.start >= 0 ? selection.start : _input.text.length;
    final end = selection.end >= 0 ? selection.end : _input.text.length;
    final text = _input.text.replaceRange(start, end, emoji);
    _input.value = TextEditingValue(
      text: text,
      selection: TextSelection.collapsed(offset: start + emoji.length),
    );
  }

  Future<void> _pickAndSendImage() async {
    final file = await widget.pickImage();
    if (file == null || !mounted) return;
    setState(() => _showMore = false);
    await ref.read(chatProvider(widget.peerId).notifier).sendImage(file.path);
  }

  void _openImage(ChatMessage message) {
    final url = (message.imageLargeUrl?.isNotEmpty ?? false)
        ? message.imageLargeUrl!
        : message.imageUrl;
    if (url == null || url.isEmpty) return;
    openPhotoViewer(context, urls: [url]);
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

  /// 头像降级链的第三级:IM 会话头像(同样来自后端同步的 IM 资料)。
  String? _imFaceUrlOf(WidgetRef ref) {
    final conversations = ref.watch(conversationsProvider).value;
    if (conversations == null) return null;
    for (final conversation in conversations) {
      if (conversation.peerId == widget.peerId) return conversation.faceUrl;
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
    final peerAvatarUrl =
        avatarUrlFor(cache, widget.peerId, imFaceUrl: _imFaceUrlOf(ref));
    final presenceById = ref.watch(presenceProvider);
    final peerUserId = userIdFromImId(widget.peerId);
    if (peerUserId != null) {
      ref.read(presenceProvider.notifier).track('chat:${widget.peerId}', [peerUserId]);
    }
    final peerPresence = peerUserId == null ? null : presenceById[peerUserId];
    final peerStatusLabel = presenceLabel(peerPresence);
    return Scaffold(
      appBar: AppBar(
        title: InkWell(
          key: const Key('chat.title'),
          onTap: () => _openProfile(context, cache),
          child: peerStatusLabel == null
              ? Text(peerName)
              : Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(peerName),
                    Text(
                      peerStatusLabel,
                      style: TextStyle(
                        fontSize: 11,
                        color: peerPresence!.online
                            ? const Color(0xFF34C759)
                            : const Color(0xFF8A8F98),
                      ),
                    ),
                  ],
                ),
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
                            onTapImage: () => _openImage(message),
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
          _InputBar(
            controller: _input,
            focusNode: _focusNode,
            sending: _sending,
            onSend: _send,
            onToggleEmoji: _toggleEmoji,
            onToggleMore: _toggleMore,
          ),
          if (_showEmoji)
            EmojiPanel(onSelect: _insertEmoji)
          else if (_showMore)
            MorePanel(onPickImage: _pickAndSendImage),
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
  const _InputBar({
    required this.controller,
    required this.focusNode,
    required this.sending,
    required this.onSend,
    required this.onToggleEmoji,
    required this.onToggleMore,
  });

  final TextEditingController controller;
  final FocusNode focusNode;
  final bool sending;
  final VoidCallback onSend;
  final VoidCallback onToggleEmoji;
  final VoidCallback onToggleMore;

  @override
  Widget build(BuildContext context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 4, 8),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  key: const Key('chat.input'),
                  controller: controller,
                  focusNode: focusNode,
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
                key: const Key('chat.emoji.button'),
                onPressed: onToggleEmoji,
                icon: const Icon(Icons.emoji_emotions_outlined),
              ),
              IconButton(
                key: const Key('chat.more.button'),
                onPressed: onToggleMore,
                icon: const Icon(Icons.add_circle_outline),
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
