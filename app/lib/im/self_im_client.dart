import 'dart:async';
import 'dart:convert';

import 'im_bootstrap.dart';
import 'im_client.dart';
import 'self_transport.dart';

class _PendingSend {
  _PendingSend(this.peerId, this.text, this.completer);
  final String peerId;
  final String text;
  final Completer<ChatMessage> completer;
}

class SelfImClient extends ImClient {
  SelfImClient({SelfTransport Function()? transportFactory, SelfHttpClient? httpClient})
      : _newTransport = transportFactory ?? (() => WebSocketTransport()),
        _http = httpClient;

  final SelfTransport Function() _newTransport;
  SelfHttpClient? _http;
  final _events = StreamController<ImEvent>.broadcast();
  final _pendingSends = <String, _PendingSend>{};
  final _pendingAcks = <String, Completer<void>>{};

  ImBootstrap? _bootstrap;
  SelfTransport? _transport;
  StreamSubscription<String>? _sub;
  Timer? _heartbeat;
  Timer? _reconnect;
  Completer<void>? _auth;
  String? _lastToken;
  bool _stopped = true;
  int _attempt = 0;

  @override
  Stream<ImEvent> get events => _events.stream;

  @override
  ImCapabilities get capabilities => const ImCapabilities(image: false);

  @override
  Future<void> init(ImBootstrap bootstrap) async {
    _bootstrap = bootstrap;
    _http ??= DioSelfHttpClient(bootstrap.httpUrl, bootstrap.token);
  }

  @override
  Future<void> login({required String userId, required String userSig}) async {
    _stopped = false;
    _lastToken = userSig;
    _attempt = 0;
    await _connect(userSig);
  }

  Future<void> _connect(String token) async {
    final bootstrap = _bootstrap!;
    await _sub?.cancel();
    final transport = _newTransport();
    _transport = transport;
    final auth = Completer<void>();
    _auth = auth;
    _sub = transport.frames.listen(
      (raw) => _onFrame(raw),
      onDone: _scheduleReconnect,
      onError: (_) => _scheduleReconnect(),
    );
    try {
      await transport.connect(Uri.parse(bootstrap.wsUrl));
      transport.send(jsonEncode({
        'v': 1,
        'type': 'auth',
        'data': {'token': token},
      }));
      await auth.future.timeout(const Duration(seconds: 5));
      _attempt = 0;
      _startHeartbeat();
    } catch (_) {
      await transport.close();
      if (!_stopped) _scheduleReconnect();
      rethrow;
    }
  }

  void _onFrame(String raw) {
    final frame = jsonDecode(raw);
    if (frame is! Map<String, dynamic>) return;
    final type = frame['type'] as String? ?? '';
    final data = frame['data'] is Map<String, dynamic>
        ? frame['data'] as Map<String, dynamic>
        : const <String, dynamic>{};

    switch (type) {
      case 'auth_ok':
        if (!(_auth?.isCompleted ?? true)) _auth!.complete();
      case 'kicked':
        _stopped = true;
        _events.add(const ImKickedOffline());
        unawaited(_transport?.close());
      case 'error':
        final code = data['code'] as int? ?? 0;
        if (code == 40101) {
          _stopped = true;
          _events.add(const ImSigExpired());
          unawaited(_transport?.close());
        } else {
          final error = ImException(code, data['message'] as String? ?? 'IM 错误');
          for (final pending in _pendingAcks.values) {
            if (!pending.isCompleted) pending.completeError(error);
          }
          _pendingAcks.clear();
        }
      case 'ack':
        _onAck(frame['id'] as String? ?? '', data);
      case 'message':
        final message = _messageFromJson(data);
        _events.add(ImNewMessage(message));
        _events.add(const ImConversationsChanged());
      case 'revoked':
        _events.add(ImMessageRevoked('${data['msg_id'] ?? ''}'));
      case 'pong':
        break;
    }
  }

  void _onAck(String id, Map<String, dynamic> data) {
    final ack = _pendingAcks.remove(id);
    if (ack != null && !ack.isCompleted) {
      ack.complete();
    }
    final pending = _pendingSends.remove(id);
    if (pending == null || pending.completer.isCompleted) return;
    pending.completer.complete(ChatMessage(
      msgId: '${data['msg_id'] ?? ''}',
      peerId: pending.peerId,
      isSelf: true,
      timestamp: (data['ts'] as num?)?.toInt() ?? DateTime.now().millisecondsSinceEpoch,
      kind: ChatMessageKind.text,
      text: pending.text,
    ));
  }

  void _startHeartbeat() {
    _heartbeat?.cancel();
    _heartbeat = Timer.periodic(const Duration(seconds: 25), (_) {
      _transport?.send(jsonEncode({'v': 1, 'type': 'ping', 'data': {}}));
    });
  }

  void _scheduleReconnect() {
    if (_stopped || _lastToken == null) return;
    _heartbeat?.cancel();
    _reconnect?.cancel();
    final delays = [1, 2, 4, 8, 16, 30];
    final seconds = delays[_attempt.clamp(0, delays.length - 1)];
    _attempt = (_attempt + 1).clamp(0, delays.length - 1);
    _reconnect = Timer(Duration(seconds: seconds), () {
      if (_stopped) return;
      unawaited(_connect(_lastToken!).catchError((_) {}));
    });
  }

  @override
  Future<void> logout() async {
    _stopped = true;
    _heartbeat?.cancel();
    _reconnect?.cancel();
    await _sub?.cancel();
    await _transport?.close();
    _transport = null;
  }

  @override
  Future<ChatMessage> sendText({required String peerId, required String text,
      String? clientMsgId}) async {
    final id = clientMsgId ?? 'local-${DateTime.now().microsecondsSinceEpoch}';
    final completer = Completer<ChatMessage>();
    _pendingSends[id] = _PendingSend(peerId, text, completer);
    for (var attempt = 0; attempt < 3; attempt++) {
      _transport?.send(jsonEncode({
        'v': 1,
        'type': 'send',
        'id': id,
        'data': {
          'client_msg_id': id,
          'to': peerId,
          'kind': 'text',
          'text': text,
        },
      }));
      try {
        return await completer.future.timeout(const Duration(seconds: 10));
      } on TimeoutException {
        if (attempt == 2) break;
      }
    }
    _pendingSends.remove(id);
    throw const ImException(50001, '发送失败,请重试');
  }

  @override
  Future<ChatMessage> resend(ChatMessage message) {
    if (message.kind == ChatMessageKind.image && message.localPath != null) {
      return sendImage(peerId: message.peerId, imagePath: message.localPath!);
    }
    return sendText(peerId: message.peerId, text: message.text,
        clientMsgId: message.msgId);
  }

  @override
  Future<ChatMessage> sendImage({required String peerId, required String imagePath}) {
    throw const ImException(42202, '当前聊天服务暂不支持图片');
  }

  @override
  Future<List<ImConversation>> fetchConversations() async {
    final data = await _http!.get('/conversations', {'limit': '100'});
    final items = (data['items'] as List? ?? const []).cast<Map<String, dynamic>>();
    return items.map((item) {
      final peer = (item['peer'] as Map?)?.cast<String, dynamic>() ?? const {};
      final last = item['last_message'];
      return ImConversation(
        peerId: peer['id'] as String? ?? '',
        unreadCount: (item['unread'] as num?)?.toInt() ?? 0,
        showName: peer['nickname'] as String?,
        faceUrl: peer['avatar'] as String?,
        lastMessage: last is Map<String, dynamic> ? _messageFromJson(last) : null,
      );
    }).toList();
  }

  @override
  Future<List<ChatMessage>> fetchHistory(String peerId, {int count = 50}) async {
    final data = await _http!.get('/messages', {
      'peer': peerId,
      'limit': '$count',
    });
    final items = (data['items'] as List? ?? const []).cast<Map<String, dynamic>>();
    return items.map(_messageFromJson).toList();
  }

  @override
  Future<void> markConversationRead(String peerId) async {
    _transport?.send(jsonEncode({
      'v': 1,
      'type': 'read',
      'id': 'read-${DateTime.now().microsecondsSinceEpoch}',
      'data': {'peer': peerId, 'seq': 0},
    }));
  }

  @override
  Future<void> revokeMessage(String msgId) async {
    final id = 'revoke-${DateTime.now().microsecondsSinceEpoch}';
    final completer = Completer<void>();
    _pendingAcks[id] = completer;
    _transport?.send(jsonEncode({
      'v': 1,
      'type': 'revoke',
      'id': id,
      'data': {'msg_id': msgId},
    }));
    try {
      await completer.future.timeout(const Duration(seconds: 5));
    } on TimeoutException {
      _pendingAcks.remove(id);
      throw const ImException(41001, '撤回失败');
    }
  }

  @override
  Future<void> deleteMessage(ChatMessage message) async {}

  @override
  Future<void> deleteConversation(String peerId) async {
    _transport?.send(jsonEncode({
      'v': 1,
      'type': 'conversation_delete',
      'id': 'delete-${DateTime.now().microsecondsSinceEpoch}',
      'data': {'peer': peerId},
    }));
  }

  ChatMessage _messageFromJson(Map<String, dynamic> json) {
    final from = json['from'] as String? ?? '';
    final to = json['to'] as String? ?? '';
    final isSelf = from == _bootstrap?.imUserId;
    final kind = json['kind'] as String? ?? 'text';
    final custom = (json['custom'] as Map?)?.cast<String, dynamic>() ?? const {};
    final customType = custom['type'] as String? ?? '';
    final messageKind = switch (kind) {
      'custom' when customType == 'match_notice' => ChatMessageKind.matchNotice,
      'custom' when customType.isNotEmpty => ChatMessageKind.banNotice,
      'custom' => ChatMessageKind.other,
      _ => ChatMessageKind.text,
    };
    return ChatMessage(
      msgId: '${json['msg_id'] ?? ''}',
      peerId: isSelf ? to : from,
      isSelf: isSelf,
      timestamp: (json['ts'] as num?)?.toInt() ?? 0,
      kind: messageKind,
      text: kind == 'custom'
          ? (custom['desc'] as String? ?? '')
          : (json['text'] as String? ?? ''),
      isRevoked: json['revoked'] == true,
    );
  }
}
