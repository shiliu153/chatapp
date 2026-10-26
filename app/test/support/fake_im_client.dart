import 'dart:async';

import 'package:chatapp_app/im/im_bootstrap.dart';
import 'package:chatapp_app/im/im_client.dart';

/// 测试用假 IM 客户端:不碰原生插件,行为可编排,调用有流水可断言。
class FakeImClient extends ImClient {
  final _events = StreamController<ImEvent>.broadcast();

  /// 调用流水,如 'init:1600161711' / 'login:u3' / 'send:u9:你好'。
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

  /// 置上则只让**下一次** login 抛错,之后恢复正常(测 6206 重试)。
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

  @override
  ImCapabilities get capabilities =>
      ImCapabilities(image: imageCapability, search: searchCapability);

  @override
  Future<void> init(ImBootstrap bootstrap) async {
    if (_initialized) return; // 接口约定 init 幂等,和真实实现保持一致
    _initialized = true;
    log.add('init:${bootstrap.sdkAppId}');
  }

  @override
  Future<void> login({required String userId, required String userSig}) async {
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
      String? clientMsgId}) async {
    log.add('send:$peerId:$text');
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
  Future<ChatMessage> sendImage({required String peerId, required String imagePath}) async {
    log.add('sendImage:$peerId:$imagePath');
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
  Future<void> deleteMessage(ChatMessage message) async => log.add('delete:${message.msgId}');

  @override
  Future<void> revokeMessage(String msgId) async {
    log.add('revoke:$msgId');
    if (revokeError != null) throw revokeError!;
  }

  @override
  Future<void> markConversationRead(String peerId) async => log.add('read:$peerId');

  @override
  Future<void> deleteConversation(String peerId) async {
    log.add('deleteConversation:$peerId');
    conversations = conversations.where((item) => item.peerId != peerId).toList();
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

  void dispose() => _events.close();
}
