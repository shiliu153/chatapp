import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../im/im_client.dart';
import '../../im/im_manager.dart';

/// 单个会话的消息流:历史 + 实时,外加乐观发送。
class ChatController extends AsyncNotifier<List<ChatMessage>> {
  ChatController(this.peerId);

  final String peerId;

  @override
  Future<List<ChatMessage>> build() async {
    final status = ref.watch(imStatusProvider);
    if (status is! ImLoggedIn) return const [];
    final client = ref.read(imClientProvider);
    final sub = client.events.listen((event) {
      if (event is ImNewMessage && event.message.peerId == peerId) {
        _append(event.message);
        _markRead(client); // 正看着这个会话,来了就算已读
      }
    });
    ref.onDispose(sub.cancel);
    _markRead(client);
    return client.fetchHistory(peerId);
  }

  /// 清未读是尽力而为:失败只影响角标,不该炸聊天页。
  void _markRead(ImClient client) {
    unawaited(client.markConversationRead(peerId).catchError((Object _) {}));
  }

  void _append(ChatMessage message) {
    final current = state.value ?? const <ChatMessage>[];
    if (current.any((item) => item.msgId == message.msgId)) return;
    state = AsyncValue.data([...current, message]);
  }

  Future<void> send(String text) async {
    final client = ref.read(imClientProvider);
    final pending = ChatMessage(
      msgId: 'local-${DateTime.now().microsecondsSinceEpoch}',
      peerId: peerId,
      isSelf: true,
      timestamp: DateTime.now().millisecondsSinceEpoch,
      kind: ChatMessageKind.text,
      text: text,
      isPending: true,
    );
    _append(pending);
    try {
      final sent = await client.sendText(peerId: peerId, text: text);
      final current = state.value ?? const <ChatMessage>[];
      state =
          AsyncValue.data([...current.where((item) => item.msgId != pending.msgId), sent]);
    } catch (_) {
      final current = state.value ?? const <ChatMessage>[];
      state = AsyncValue.data(current.where((item) => item.msgId != pending.msgId).toList());
      rethrow;
    }
  }
}

final chatProvider = AsyncNotifierProvider.family<ChatController, List<ChatMessage>, String>(
  ChatController.new,
  // 页面自己有错误态,关掉 Riverpod 3 的自动重试,行为更可预期
  retry: (retryCount, error) => null,
);
