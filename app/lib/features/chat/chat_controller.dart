import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../im/im_client.dart';
import '../../im/im_manager.dart';
import 'conversations_controller.dart';

/// 单个会话的消息流:历史 + 实时,外加乐观发送。
class ChatController extends AsyncNotifier<List<ChatMessage>> {
  ChatController(this.peerId);

  final String peerId;

  /// 一次批量删除的上限,与 imserver `POST /im/api/messages/delete` 的契约一致
  /// (`ids` ≤ 50,超了回 400 + 42201)。页面按它限制勾选条数,而不是让用户勾满
  /// 一屏再收到一个错误。
  static const maxDeleteBatch = 50;

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
    // 引用条也不能跨会话残留:离开页面就等于「不引用了」。
    ref.read(chatQuoteTargetProvider(peerId).notifier).clear();
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

  Future<void> send(String text) {
    // 引用(批次 L-2):上行只带 id;这里给乐观气泡挂一份**本地**快照,
    // 好让「发送中」的气泡也显示引用块。真正的快照由服务端生成,
    // 下次拉历史时会被服务端的版本替换。
    final quote = ref.read(chatQuoteTargetProvider(peerId));
    return _sendOut(ChatMessage(
      msgId: 'local-${DateTime.now().microsecondsSinceEpoch}',
      peerId: peerId,
      isSelf: true,
      timestamp: DateTime.now().millisecondsSinceEpoch,
      kind: ChatMessageKind.text,
      text: text,
      isPending: true,
      ref: _localRef(quote),
    ));
  }

  Future<void> sendImage(String imagePath) => _sendOut(ChatMessage(
        msgId: 'local-${DateTime.now().microsecondsSinceEpoch}',
        peerId: peerId,
        isSelf: true,
        timestamp: DateTime.now().millisecondsSinceEpoch,
        kind: ChatMessageKind.image,
        localPath: imagePath,
        isPending: true,
        ref: _localRef(ref.read(chatQuoteTargetProvider(peerId))),
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
        ref: _localRef(ref.read(chatQuoteTargetProvider(peerId))),
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
        ref: _localRef(ref.read(chatQuoteTargetProvider(peerId))),
      ));

  /// 把「我选中的引用目标」变成一份本地快照(只用于乐观上屏)。
  ///
  /// Args:
  ///   target: 当前会话的引用目标;为空表示这条消息不带引用。
  ///
  /// Returns:
  ///   给待发送气泡用的 [QuoteRef];没有引用时返回 null。
  QuoteRef? _localRef(QuoteTarget? target) => target == null
      ? null
      : QuoteRef(
          msgId: target.msgId,
          from: target.from,
          kind: 'text',
          text: target.text,
          revoked: false,
        );

  /// 失败不抛异常、消息保留 isFailed;重发复用同一条(msgId 不变,靠 upsert 就地替换)。
  Future<void> _sendOut(ChatMessage pendingMessage) async {
    _upsert(pendingMessage);
    final client = ref.read(imClientProvider);
    try {
      final sent = await client.resend(pendingMessage);
      // 上行只发了 `ref_msg_id`,回执里自然没有快照:把本地那份留在气泡上,
      // 否则「发送中」的引用块会在发送成功的一瞬间消失。
      _replace(pendingMessage.msgId, sent.copyWith(ref: pendingMessage.ref));
      // 发出去就清掉引用条:下一条消息默认不带引用。
      ref.read(chatQuoteTargetProvider(peerId).notifier).clear();
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

  /// 批量删除(批次 T-2,多选删除):**单方删除**,对方仍可见。
  ///
  /// 两步分开、顺序不能反:
  /// 1. 先把「服务端认得的」id 一次性发给 imserver(`local-` 开头的本地乐观消息
  ///    不在服务端,混进去会整批 42201,所以挡在外面、本地直接移除);
  /// 2. 服务端删成功后才动本地列表 —— 失败时**一条都不移除**并让异常冒到页面,
  ///    页面保留用户的选择,这就是「删失败不要丢掉我选的」。
  ///
  /// 成功后顺手刷新会话列表:列表摘要里的 `last_message` 与未读数都由服务端算,
  /// 不刷新就会出现「删了但列表还显示那条」的假象。
  ///
  /// Args:
  ///   msgIds: 要删的消息 id(可含 `local-` 乐观消息)。
  ///
  /// Throws:
  ///   [ImException]:imserver 拒绝(42201 / 42901)或 HTTP 侧 [ApiException]。
  Future<void> deleteMessages(Iterable<String> msgIds) async {
    final ids = msgIds.toSet().toList();
    if (ids.isEmpty) return;
    final remote = ids.where((id) => !id.startsWith('local-')).toList();
    if (remote.isNotEmpty) {
      // 不 catch:失败必须让调用方知道(多选删除要保留选中并 toast)。
      await ref.read(imClientProvider).deleteMessages(remote);
    }
    final gone = ids.toSet();
    final current = state.value ?? const <ChatMessage>[];
    state = AsyncValue.data(current.where((item) => !gone.contains(item.msgId)).toList());
    unawaited(ref.read(conversationsProvider.notifier).reload().catchError((Object _) {}));
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

/// 当前会话的引用目标(批次 L-2):长按消息选「引用」后置上,发送成功或关掉引用条即清空。
///
/// 为什么单独一个 provider 而不是塞进 [ChatController]:引用条是**输入区**的状态,
/// 它要跟着输入框一起重建,却与消息列表的生命周期无关;放一起会让「打字」和
/// 「加载历史」互相触发重建。autoDispose + 按会话 family:离开页面 / 切会话即丢,
/// 不会把上一段对话的引用带到下一段。
class ChatQuoteTarget extends Notifier<QuoteTarget?> {
  ChatQuoteTarget(this.peerId);

  final String peerId;

  @override
  QuoteTarget? build() => null;

  /// 设为新的引用目标。
  ///
  /// Args:
  ///   target: 被引用的那条消息。
  void set(QuoteTarget target) => state = target;

  /// 取消引用(发送成功 / 点关闭按钮 / 离开页面)。
  void clear() {
    if (state != null) state = null;
  }
}

final chatQuoteTargetProvider =
    NotifierProvider.autoDispose.family<ChatQuoteTarget, QuoteTarget?, String>(
  ChatQuoteTarget.new,
);
