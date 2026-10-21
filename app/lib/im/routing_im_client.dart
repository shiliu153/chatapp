import 'dart:async';

import 'im_bootstrap.dart';
import 'im_client.dart';
import 'self_im_client.dart';
import 'tencent_im_client.dart';

/// 按引导包选择腾讯/自建实现;业务层只依赖 ImClient。
class RoutingImClient extends ImClient {
  final _events = StreamController<ImEvent>.broadcast();
  ImClient? _active;
  StreamSubscription<ImEvent>? _sub;

  @override
  Stream<ImEvent> get events => _events.stream;

  @override
  ImCapabilities get capabilities =>
      _active?.capabilities ?? const ImCapabilities(image: false);

  @override
  Future<void> init(ImBootstrap bootstrap) async {
    final next = bootstrap.backend == ImBackend.self
        ? SelfImClient()
        : TencentImClient();
    await next.init(bootstrap);
    await _sub?.cancel();
    _sub = next.events.listen(_events.add);
    _active = next;
  }

  @override
  Future<void> login({required String userId, required String userSig}) =>
      _active!.login(userId: userId, userSig: userSig);

  @override
  Future<void> logout() => _active?.logout() ?? Future.value();

  @override
  Future<List<ImConversation>> fetchConversations() =>
      _active!.fetchConversations();

  @override
  Future<List<ChatMessage>> fetchHistory(String peerId, {int count = 50}) =>
      _active!.fetchHistory(peerId, count: count);

  @override
  Future<ChatMessage> sendText({required String peerId, required String text,
      String? clientMsgId}) =>
      _active!.sendText(peerId: peerId, text: text, clientMsgId: clientMsgId);

  @override
  Future<ChatMessage> sendImage({required String peerId, required String imagePath}) =>
      _active!.sendImage(peerId: peerId, imagePath: imagePath);

  @override
  Future<void> deleteMessage(ChatMessage message) => _active!.deleteMessage(message);

  @override
  Future<void> revokeMessage(String msgId) => _active!.revokeMessage(msgId);

  @override
  Future<void> markConversationRead(String peerId) =>
      _active!.markConversationRead(peerId);

  @override
  Future<void> deleteConversation(String peerId) =>
      _active!.deleteConversation(peerId);
}
