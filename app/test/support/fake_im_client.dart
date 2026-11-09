import 'dart:async';

import 'package:chatapp_app/im/im_bootstrap.dart';
import 'package:chatapp_app/im/im_client.dart';

/// 测试用假 IM 客户端:不碰原生插件,行为可编排,调用有流水可断言。
class FakeImClient extends ImClient {
  final _events = StreamController<ImEvent>.broadcast();

  /// 调用流水,如 'init:u3' / 'login:u3' / 'send:u9:你好'。
  final List<String> log = [];

  List<ImConversation> conversations = [];
  Map<String, List<ChatMessage>> history = {};

  /// 置上就让 login / sendText 抛这个错(测失败分支)。
  Object? loginError;
  Object? sendError;

  /// 置上就让 fetchHistory 抛这个错(测聊天页错误态)。
  Object? historyError;

  /// 置上就让 revokeMessage 抛这个错(测失败提示)。
  Object? revokeError;

  /// 置上则 fetchHistory 挂起直到 complete(测加载骨架)。
  Completer<void>? historyGate;

  /// 置上则只让**下一次** login 抛错,之后恢复正常(测 40101 重试)。
  Object? loginErrorOnce;

  /// 搜索命中(测搜索页用;默认按关键词 contains 过滤)。
  List<ImSearchHit> searchHits = [];

  /// 完全接管 searchMessages 的返回(分页/错误分支用)。
  ImSearchResult Function(String keyword, int limit, String? beforeId)? searchHandler;

  /// 置上就让 searchMessages 抛这个错。
  Object? searchError;

  /// 自建后端下置 false,用来测搜索入口隐藏。
  bool searchCapability = true;

  /// 更早的历史页:peerId → (beforeSeq → 一页消息),测回溯翻页。
  Map<String, Map<int, List<ChatMessage>>> olderHistory = {};

  int _seq = 0;
  bool _initialized = false;

  @override
  Stream<ImEvent> get events => _events.stream;

  /// 自建后端下置 false,用来测图片入口隐藏。
  bool imageCapability = true;

  /// 自建后端下置 false,用来测语音入口隐藏。
  bool voiceCapability = true;

  /// 置 false 用来测「不支持已读回执时不显示已读」。
  bool readReceiptCapability = true;

  @override
  ImCapabilities get capabilities => ImCapabilities(
        image: imageCapability,
        search: searchCapability,
        voice: voiceCapability,
        readReceipt: readReceiptCapability,
      );

  @override
  Future<void> init(ImBootstrap bootstrap) async {
    if (_initialized) return; // 接口约定 init 幂等,和真实实现保持一致
    _initialized = true;
    log.add('init:${bootstrap.imUserId}');
  }

  @override
  Future<void> login({required String userId, required String token}) async {
    log.add('login:$userId');
    if (loginErrorOnce != null) {
      final error = loginErrorOnce!;
      loginErrorOnce = null;
      throw error;
    }
    if (loginError != null) throw loginError!;
  }

  @override
  Future<void> logout() async => log.add('logout');

  @override
  Future<List<ImConversation>> fetchConversations() async {
    log.add('fetchConversations');
    return conversations;
  }

  @override
  Future<List<ChatMessage>> fetchHistory(String peerId, {int count = 50, int? beforeSeq}) async {
    log.add('fetchHistory:$peerId');
    if (historyError != null) throw historyError!;
    final gate = historyGate;
    if (gate != null) await gate.future;
    if (beforeSeq != null) return olderHistory[peerId]?[beforeSeq] ?? const [];
    return history[peerId] ?? const [];
  }

  @override
  Future<ImSearchResult> searchMessages(String keyword,
      {int limit = 20, String? beforeId}) async {
    log.add('search:$keyword');
    if (searchError != null) throw searchError!;
    final handler = searchHandler;
    if (handler != null) return handler(keyword, limit, beforeId);
    final items = searchHits.where((hit) => hit.text.contains(keyword)).toList();
    return ImSearchResult(items: items.take(limit).toList(), hasMore: items.length > limit);
  }

  @override
  Future<ChatMessage> sendText({required String peerId, required String text,
      String? clientMsgId, int? refMsgId}) async {
    // 引用(批次 L-2):上行只带 id,流水里记下来好断言「发出去时带没带引用」。
    log.add(refMsgId == null ? 'send:$peerId:$text' : 'send:$peerId:$text:ref=$refMsgId');
    if (sendError != null) throw sendError!;
    return ChatMessage(
      msgId: 'sent-${++_seq}',
      peerId: peerId,
      isSelf: true,
      timestamp: DateTime.now().millisecondsSinceEpoch,
      kind: ChatMessageKind.text,
      text: text,
    );
  }

  @override
  Future<ChatMessage> sendImage({required String peerId, required String imagePath,
      int? refMsgId}) async {
    log.add(refMsgId == null
        ? 'sendImage:$peerId:$imagePath'
        : 'sendImage:$peerId:$imagePath:ref=$refMsgId');
    if (sendError != null) throw sendError!;
    return ChatMessage(
      msgId: 'sent-${++_seq}',
      peerId: peerId,
      isSelf: true,
      timestamp: DateTime.now().millisecondsSinceEpoch,
      kind: ChatMessageKind.image,
      localPath: imagePath,
    );
  }

  @override
  Future<ChatMessage> sendVoice({required String peerId, required String localPath,
      required int durationMs, int? refMsgId}) async {
    log.add(refMsgId == null
        ? 'sendVoice:$peerId:$localPath:$durationMs'
        : 'sendVoice:$peerId:$localPath:$durationMs:ref=$refMsgId');
    if (sendError != null) throw sendError!;
    return ChatMessage(
      msgId: 'sent-${++_seq}',
      peerId: peerId,
      isSelf: true,
      timestamp: DateTime.now().millisecondsSinceEpoch,
      kind: ChatMessageKind.voice,
      localPath: localPath,
      voiceUrl: 'http://cdn/v.m4a',
      voiceDurationMs: durationMs,
    );
  }

  @override
  Future<ChatMessage> sendSticker({required String peerId, required String stickerId,
      int? refMsgId}) async {
    log.add(refMsgId == null
        ? 'sendSticker:$peerId:$stickerId'
        : 'sendSticker:$peerId:$stickerId:ref=$refMsgId');
    if (sendError != null) throw sendError!;
    return ChatMessage(
      msgId: 'sent-${++_seq}',
      peerId: peerId,
      isSelf: true,
      timestamp: DateTime.now().millisecondsSinceEpoch,
      kind: ChatMessageKind.sticker,
      stickerId: stickerId,
    );
  }

  @override
  Future<void> deleteMessage(ChatMessage message) async => log.add('delete:${message.msgId}');

  @override
  Future<void> revokeMessage(String msgId) async {
    log.add('revoke:$msgId');
    if (revokeError != null) throw revokeError!;
  }

  @override
  Future<void> markConversationRead(String peerId) async => log.add('read:$peerId');

  @override
  Future<void> sendTyping(String peerId) async => log.add('typing:$peerId');

  @override
  Future<void> deleteConversation(String peerId) async {
    log.add('deleteConversation:$peerId');
    conversations = conversations.where((item) => item.peerId != peerId).toList();
  }

  /// 置上就让 setConversationFlags 抛这个错(测 40401 / 42901 / 失败保留原状态)。
  Object? flagsError;

  @override
  Future<ImConversationFlags> setConversationFlags(String peerId,
      {bool? pinned, bool? muted}) async {
    // 流水里把「只传了哪一项」记清楚:没传的那项必须是 null,不能被当成 false 上行。
    log.add('setFlags:$peerId:pinned=${pinned ?? '-'}:muted=${muted ?? '-'}');
    if (flagsError != null) throw flagsError!;
    var pinnedNow = false;
    var mutedNow = false;
    conversations = conversations.map((item) {
      if (item.peerId != peerId) return item;
      pinnedNow = pinned ?? item.pinned;
      mutedNow = muted ?? item.muted;
      return item.copyWith(pinned: pinnedNow, muted: mutedNow);
    }).toList();
    if (pinned != null) _restackAfterPin(peerId);
    return ImConversationFlags(pinned: pinnedNow, muted: mutedNow);
  }

  /// 近似服务端的置顶排序(`pinned_at` 倒序在前,其余按最近消息):
  /// 刚置顶的排到最前,取消置顶的排到置顶组之后。真实顺序以服务端为准,
  /// 客户端一个字段都不自己排(imserver.md §19.6)。
  void _restackAfterPin(String peerId) {
    final index = conversations.indexWhere((item) => item.peerId == peerId);
    if (index < 0) return;
    final self = conversations[index];
    final pinnedOthers = conversations
        .where((item) => item.peerId != peerId && item.pinned)
        .toList();
    final rest = conversations
        .where((item) => item.peerId != peerId && !item.pinned)
        .toList();
    conversations =
        self.pinned ? [self, ...pinnedOthers, ...rest] : [...pinnedOthers, self, ...rest];
  }

  /// 模拟服务器推事件。
  void emit(ImEvent event) => _events.add(event);

  /// 模拟收到一条来自 peer 的文本,返回推出去的消息。
  ChatMessage emitIncoming(String peerId, String text) {
    final message = ChatMessage(
      msgId: 'in-${++_seq}',
      peerId: peerId,
      isSelf: false,
      timestamp: DateTime.now().millisecondsSinceEpoch,
      kind: ChatMessageKind.text,
      text: text,
    );
    emit(ImNewMessage(message));
    return message;
  }

  /// 模拟「消息被撤回」事件。
  void emitRevoked(String msgId) => emit(ImMessageRevoked(msgId));

  /// 模拟「对端读到 seq」的下行 read 帧。
  void emitPeerRead(String peerId, int seq) => emit(ImPeerRead(peerId: peerId, seq: seq));

  /// 模拟「**我**在另一台设备上读到 seq」的 `self_read` 帧(多端在线 K-3)。
  void emitSelfRead(String peerId, int seq) => emit(ImSelfRead(peerId: peerId, seq: seq));

  /// 模拟「**我**在另一台设备上删了会话」的 `conversation_deleted` 帧(多端在线 K-3)。
  void emitConversationDeleted(String peerId) => emit(ImConversationDeleted(peerId));

  /// 模拟对端正在输入的 `typing` 下行帧(批次 L-1)。
  void emitTyping(String peerId) => emit(ImTyping(peerId: peerId));

  void dispose() => _events.close();
}
