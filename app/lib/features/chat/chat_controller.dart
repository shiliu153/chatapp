import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../im/im_client.dart';
import '../../im/im_manager.dart';

/// 单个会话的消息流:历史 + 实时,外加乐观发送。
class ChatController extends AsyncNotifier<List<ChatMessage>> {
  ChatController(this.peerId);

  final String peerId;

  /// 上一次发出「正在输入」的冷却定时器(客户端 3 秒节流用)。
  ///
  /// 为什么客户端还要节流:服务端有令牌桶(1 次 / 2 秒)兜底,但每敲一个字就发一帧
  /// 纯属浪费流量与连接;3 秒一次足够让对方看到提示。两层都要有 —— 客户端可被改,
  /// 服务端那层才是防伪造的那层。
  Timer? _typingCooldown;

  /// 客户端节流窗口:3 秒内最多发一次。
  static const typingThrottle = Duration(seconds: 3);

  @override
  Future<List<ChatMessage>> build() async {
    final status = ref.watch(imStatusProvider);
    if (status is! ImLoggedIn) return const [];
    final client = ref.read(imClientProvider);
    final sub = client.events.listen((event) {
      if (event is ImNewMessage && event.message.peerId == peerId) {
        _append(event.message);
        _markRead(client); // 正看着这个会话,来了就算已读
      } else if (event is ImMessageRevoked) {
        _markRevoked(event.msgId);
      } else if (event is ImPeerRead && event.peerId == peerId) {
        // 对端读到 seq:我方 seq <= N 的气泡改显示「已读」
        ref.read(chatPeerReadSeqProvider(peerId).notifier).advance(event.seq);
      } else if (event is ImTyping && event.peerId == peerId) {
        // 对端正在输入:顶栏提示,5 秒内没有新帧自动消失
        ref.read(chatPeerTypingProvider(peerId).notifier).ping();
      }
    });
    ref.onDispose(sub.cancel);
    ref.onDispose(() => _typingCooldown?.cancel());
    _markRead(client);
    unawaited(_seedPeerReadSeq(client));
    return client.fetchHistory(peerId);
  }

  /// 离开聊天页时调用(批次 L-1):清掉「对方正在输入…」并取消 3 秒节流定时器。
  ///
  /// 为什么不让 autoDispose 兜底:provider 回收是异步的,退出瞬间仍可能留着上一个人
  /// 的提示;定时器也要当场取消,否则页面关掉后它还会回调。
  void leaveChat() {
    _typingCooldown?.cancel();
    _typingCooldown = null;
    ref.read(chatPeerTypingProvider(peerId).notifier).clear();
  }

  /// 输入框有变化时调用(批次 L-1):按 3 秒节流发一次 `typing`。
  ///
  /// Args:
  ///   text: 输入框当前内容。**空串不发** —— 清空输入框意味着「不打了」,
  ///     这时再发一帧只会让对端多显示 5 秒「正在输入」。
  void notifyTyping(String text) {
    if (text.isEmpty) return;
    if (_typingCooldown != null) return; // 冷却中:3 秒内只发一次
    _typingCooldown = Timer(typingThrottle, () => _typingCooldown = null);
    // 可丢信号:失败(没连上 / 服务端静默丢弃)都不该冒泡到界面
    unawaited(ref.read(imClientProvider).sendTyping(peerId).catchError((Object _) {}));
  }

  /// 补拉「对端读到哪」。
  ///
  /// 为什么需要:断线期间对方读过什么,那时下行 `read` 帧根本没送到,所以打开会话时
  /// 必须问一次会话列表(`peer_read_seq` 是唯一事实来源)。失败静默 —— 最坏只是不显示
  /// 「已读」,不该影响聊天本身。
  Future<void> _seedPeerReadSeq(ImClient client) async {
    try {
      final conversations = await client.fetchConversations();
      for (final conversation in conversations) {
        if (conversation.peerId != peerId) continue;
        ref.read(chatPeerReadSeqProvider(peerId).notifier).advance(conversation.peerReadSeq);
      }
    } catch (_) {}
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

  Future<void> sendVoice(String path, int durationMs) => _sendOut(ChatMessage(
        msgId: 'local-${DateTime.now().microsecondsSinceEpoch}',
        peerId: peerId,
        isSelf: true,
        timestamp: DateTime.now().millisecondsSinceEpoch,
        kind: ChatMessageKind.voice,
        localPath: path,
        voiceDurationMs: durationMs,
        isPending: true,
      ));

  /// 发贴纸(批次 J):消息里只带 id,图片资源在客户端本地。
  Future<void> sendSticker(String stickerId) => _sendOut(ChatMessage(
        msgId: 'local-${DateTime.now().microsecondsSinceEpoch}',
        peerId: peerId,
        isSelf: true,
        timestamp: DateTime.now().millisecondsSinceEpoch,
        kind: ChatMessageKind.sticker,
        stickerId: stickerId,
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

  /// 往前翻历史,直到找到 [untilMsgId](或翻到顶 / 到页数上限)。搜索定位用。
  Future<void> loadOlder({required String untilMsgId, int maxPages = 5}) async {
    var current = state.value ?? const <ChatMessage>[];
    if (current.isEmpty) return;
    final client = ref.read(imClientProvider);
    for (var page = 0; page < maxPages; page++) {
      if (current.any((item) => item.msgId == untilMsgId)) return;
      final oldestSeq = current.first.seq;
      if (oldestSeq <= 1) return;
      final older = await client.fetchHistory(peerId, count: 50, beforeSeq: oldestSeq);
      if (older.isEmpty) return;
      final known = {for (final item in current) item.msgId};
      current = [...older.where((item) => !known.contains(item.msgId)), ...current];
      state = AsyncValue.data(current);
      if (older.length < 50) return;
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

  /// 撤回:成功才置灰;失败让异常冒到页面提示,不改本地状态。
  Future<void> revoke(ChatMessage message) async {
    await ref.read(imClientProvider).revokeMessage(message.msgId);
    _markRevoked(message.msgId);
  }

  void _markRevoked(String msgId) {
    final current = state.value ?? const <ChatMessage>[];
    if (!current.any((item) => item.msgId == msgId)) return;
    state = AsyncValue.data(
        [for (final item in current) if (item.msgId == msgId) item.copyWith(isRevoked: true) else item]);
  }

  void _upsert(ChatMessage message) {    final current = state.value ?? const <ChatMessage>[];
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

final chatProvider =
    AsyncNotifierProvider.autoDispose.family<ChatController, List<ChatMessage>, String>(
  ChatController.new,
  // 页面自己有错误态,关掉 Riverpod 3 的自动重试,行为更可预期
  retry: (retryCount, error) => null,
  // autoDispose 不能丢:离开聊天页后订阅必须取消,否则新消息仍被自动已读,列表红点永远不出现
);

/// 对端在这个会话里读到哪(已读回执)。
///
/// **只增不减**:下行 `read` 帧可能乱序/重复到达,收到更小的 N 必须忽略,否则会出现
/// 「已读」跳回「未读」。autoDispose:离开聊天页即丢,下次打开由 [ChatController]
/// 用会话列表的 `peer_read_seq` 重新补拉。
class ChatPeerReadSeq extends Notifier<int> {
  ChatPeerReadSeq(this.peerId);

  final String peerId;

  @override
  int build() => 0;

  /// 前进到 [seq];返回值表示是否真的变了(没变就不触发重建)。
  bool advance(int seq) {
    if (seq <= state) return false;
    state = seq;
    return true;
  }
}

final chatPeerReadSeqProvider =
    NotifierProvider.autoDispose.family<ChatPeerReadSeq, int, String>(
  ChatPeerReadSeq.new,
);

/// 对端是否正在输入(批次 L-1)。
///
/// 语义是「**最近 5 秒内**收到过对端的 `typing` 帧」,不是持久状态:typing 是可丢信号,
/// 服务端不落库、不补发、超限静默丢弃,所以这里必须自己过期 —— 否则对端打完字停手
/// 之后,「正在输入…」会一直挂着。
///
/// autoDispose:离开聊天页即丢,下次进来一定是干净的 false(不能残留上一次的提示);
/// `ref.onDispose` 取消定时器,否则页面关掉后定时器还会 setState after dispose。
class ChatPeerTyping extends Notifier<bool> {
  ChatPeerTyping(this.peerId);

  final String peerId;

  /// 收帧后多久自动置假(与设计文档 §3.3 一致)。
  static const expiry = Duration(seconds: 5);

  Timer? _expiryTimer;

  @override
  bool build() {
    ref.onDispose(() {
      _expiryTimer?.cancel();
      _expiryTimer = null;
    });
    return false;
  }

  /// 收到一帧 `typing`:置真并把过期时间往后推 5 秒。
  void ping() {
    _expiryTimer?.cancel();
    if (!state) state = true;
    _expiryTimer = Timer(expiry, () {
      _expiryTimer = null;
      state = false;
    });
  }

  /// 立即清零(离开聊天页 / 切会话时用)。
  void clear() {
    _expiryTimer?.cancel();
    _expiryTimer = null;
    if (state) state = false;
  }
}

final chatPeerTypingProvider =
    NotifierProvider.autoDispose.family<ChatPeerTyping, bool, String>(
  ChatPeerTyping.new,
);
