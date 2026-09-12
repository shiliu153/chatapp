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

  Future<void> send(String text) => _sendOut(ChatMessage(
        msgId: 'local-${DateTime.now().microsecondsSinceEpoch}',
        peerId: peerId,
        isSelf: true,
        timestamp: DateTime.now().millisecondsSinceEpoch,
        kind: ChatMessageKind.text,
        text: text,
        isPending: true,
      ));

  Future<void> sendImage(String imagePath) => _sendOut(ChatMessage(
        msgId: 'local-${DateTime.now().microsecondsSinceEpoch}',
        peerId: peerId,
        isSelf: true,
        timestamp: DateTime.now().millisecondsSinceEpoch,
        kind: ChatMessageKind.image,
        localPath: imagePath,
        isPending: true,
      ));

  /// 失败不抛异常、消息保留 isFailed;重发复用同一条(msgId 不变,靠 upsert 就地替换)。
  Future<void> _sendOut(ChatMessage pendingMessage) async {
    _upsert(pendingMessage);
    final client = ref.read(imClientProvider);
    try {
      final sent = await client.resend(pendingMessage);
      _replace(pendingMessage.msgId, sent);
    } catch (_) {
      _replace(pendingMessage.msgId, pendingMessage.copyWith(isPending: false, isFailed: true));
    }
  }

  Future<void> retry(ChatMessage message) =>
      _sendOut(message.copyWith(isPending: true, isFailed: false));

  /// 删除本地消息:本地未发出的直接移出列表;已发出的尽力删 SDK 本地库。
  Future<void> deleteLocal(ChatMessage message) async {
    if (!message.msgId.startsWith('local-')) {
      try {
        await ref.read(imClientProvider).deleteMessage(message);
      } catch (_) {}
    }
    final current = state.value ?? const <ChatMessage>[];
    state = AsyncValue.data(current.where((item) => item.msgId != message.msgId).toList());
  }

  void _upsert(ChatMessage message) {
    final current = state.value ?? const <ChatMessage>[];
    if (current.any((item) => item.msgId == message.msgId)) {
      _replace(message.msgId, message);
    } else {
      _append(message);
    }
  }

  void _replace(String msgId, ChatMessage next) {
    final current = state.value ?? const <ChatMessage>[];
    state = AsyncValue.data(
        [for (final item in current) if (item.msgId == msgId) next else item]);
  }
}

final chatProvider = AsyncNotifierProvider.family<ChatController, List<ChatMessage>, String>(
  ChatController.new,
  // 页面自己有错误态,关掉 Riverpod 3 的自动重试,行为更可预期
  retry: (retryCount, error) => null,
);
