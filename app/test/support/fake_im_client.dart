import 'dart:async';

import 'package:chatapp_app/im/im_client.dart';

/// 测试用假 IM 客户端:不碰原生插件,行为可编排,调用有流水可断言。
class FakeImClient implements ImClient {
  final _events = StreamController<ImEvent>.broadcast();

  /// 调用流水,如 'init:1600161711' / 'login:u3' / 'send:u9:你好'。
  final List<String> log = [];

  List<ImConversation> conversations = [];
  Map<String, List<ChatMessage>> history = {};

  /// 置上就让 login / sendText 抛这个错(测失败分支)。
  Object? loginError;
  Object? sendError;

  int _seq = 0;
  bool _initialized = false;

  @override
  Stream<ImEvent> get events => _events.stream;

  @override
  Future<void> init({required int sdkAppId}) async {
    if (_initialized) return; // 接口约定 init 幂等,和真实实现保持一致
    _initialized = true;
    log.add('init:$sdkAppId');
  }

  @override
  Future<void> login({required String userId, required String userSig}) async {
    log.add('login:$userId');
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
  Future<List<ChatMessage>> fetchHistory(String peerId, {int count = 50}) async {
    log.add('fetchHistory:$peerId');
    return history[peerId] ?? const [];
  }

  @override
  Future<ChatMessage> sendText({required String peerId, required String text}) async {
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
  Future<void> markConversationRead(String peerId) async => log.add('read:$peerId');

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

  void dispose() => _events.close();
}
