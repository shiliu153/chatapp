import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../im/im_client.dart';
import '../../im/im_repository.dart';
import 'chat_controller.dart';
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
    try {
      await ref.read(chatProvider(widget.peerId).notifier).send(text);
      _input.clear();
    } on ImException catch (error) {
      _showError('发送失败(${error.code})');
    } catch (_) {
      _showError('发送失败,请重试');
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  void _showError(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  void _openProfile(BuildContext context, Map<String, MatchEntry> cache) {
    // 优先用 matches 缓存里的真实 id;缓存没有(如刚被清)就按 u9 → 9 兜底
    final userId =
        cache[widget.peerId]?.userId ?? int.tryParse(widget.peerId.replaceFirst('u', ''));
    if (userId == null) return;
    context.push('/users/$userId');
  }

  @override
  Widget build(BuildContext context) {
    final messages = ref.watch(chatProvider(widget.peerId));
    final cache = ref.watch(matchCacheProvider).value ?? const {};
    return Scaffold(
      appBar: AppBar(
        title: InkWell(
          key: const Key('chat.title'),
          onTap: () => _openProfile(context, cache),
          child: Text(displayNameFor(cache, widget.peerId)),
        ),
      ),
      body: Column(
        children: [
          Expanded(
            child: messages.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (error, _) => Center(child: Text('$error')),
              data: (items) => items.isEmpty
                  ? const Center(child: Text('打个招呼吧', style: TextStyle(color: Colors.black45)))
                  : ListView.builder(
                      key: const Key('chat.list'),
                      reverse: true, // 新消息在底部,进来就停在最新一条
                      padding: const EdgeInsets.symmetric(vertical: 12),
                      itemCount: items.length,
                      itemBuilder: (context, index) {
                        final message = items[items.length - 1 - index];
                        return MessageBubble(
                          message: message,
                          onRetry: () =>
                              ref.read(chatProvider(widget.peerId).notifier).retry(message),
                        );
                      },
                    ),
            ),
          ),
          _InputBar(controller: _input, sending: _sending, onSend: _send),
        ],
      ),
    );
  }
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
