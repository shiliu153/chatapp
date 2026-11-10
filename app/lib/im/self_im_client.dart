import 'dart:async';
import 'dart:convert';

import 'im_bootstrap.dart';
import 'im_client.dart';
import 'self_image_uploader.dart';
import 'self_transport.dart';
import 'self_voice_uploader.dart';

class _PendingSend {
  _PendingSend(this.peerId, this.completer,
      {this.text = '', this.image, this.voice, this.stickerId});
  final String peerId;
  final String text;
  final ChatImageUpload? image;
  final ChatVoiceUpload? voice;

  /// 贴纸 id(批次 J):ack 回来时用它把乐观消息还原成 sticker。
  final String? stickerId;
  final Completer<ChatMessage> completer;
}

class SelfImClient extends ImClient {
  SelfImClient({SelfTransport Function()? transportFactory, SelfHttpClient? httpClient,
      SelfImageUploader? imageUploader, SelfVoiceUploader? voiceUploader})
      : _newTransport = transportFactory ?? (() => WebSocketTransport()),
        _http = httpClient,
        _uploader = imageUploader,
        _voiceUpload = voiceUploader;

  final SelfTransport Function() _newTransport;
  SelfHttpClient? _http;
  final SelfImageUploader? _uploader;
  final SelfVoiceUploader? _voiceUpload;
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
  ImCapabilities get capabilities => const ImCapabilities(
        image: true,
        search: true,
        voice: true,
        readReceipt: true,
      );

  @override
  Future<void> init(ImBootstrap bootstrap) async {
    _bootstrap = bootstrap;
    _http ??= DioSelfHttpClient(bootstrap.httpUrl, bootstrap.token);
  }

  @override
  Future<void> login({required String userId, required String token}) async {
    _stopped = false;
    _lastToken = token;
    _attempt = 0;
    await _connect(token);
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
          if (!(_auth?.isCompleted ?? true)) {
            _auth!.completeError(const ImException(40101, 'IM 登录已过期'));
          }
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
      case 'read':
        // 对端读到哪(已读回执)。服务端主动推,不要求 ack。
        _events.add(ImPeerRead(
          peerId: '${data['peer'] ?? ''}',
          seq: (data['seq'] as num?)?.toInt() ?? 0,
        ));
      case 'self_read':
        // **我**在另一台设备上读到哪(多端在线 K-3)。服务端主动推,不要求 ack。
        // 别和上面的 read 混:那个是「对端读我」,这个只清我这边的未读。
        _events.add(ImSelfRead(
          peerId: '${data['peer'] ?? ''}',
          seq: (data['seq'] as num?)?.toInt() ?? 0,
        ));
      case 'conversation_deleted':
        // **我**在另一台设备上删了与 peer 的会话(多端在线 K-3)。只发给本人的其他端。
        _events.add(ImConversationDeleted('${data['peer'] ?? ''}'));
      case 'typing':
        // 对端正在输入(批次 L-1)。可丢信号:没有 id、不用 ack、服务端不补发。
        _events.add(ImTyping(peerId: '${data['peer'] ?? ''}'));
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
    final image = pending.image;
    final voice = pending.voice;
    final stickerId = pending.stickerId;
    pending.completer.complete(ChatMessage(
      msgId: '${data['msg_id'] ?? ''}',
      peerId: pending.peerId,
      isSelf: true,
      timestamp: (data['ts'] as num?)?.toInt() ?? DateTime.now().millisecondsSinceEpoch,
      kind: stickerId != null
          ? ChatMessageKind.sticker
          : (voice != null
              ? ChatMessageKind.voice
              : (image == null ? ChatMessageKind.text : ChatMessageKind.image)),
      text: pending.text,
      imageUrl: image?.thumbUrl,
      imageLargeUrl: image?.url,
      voiceUrl: voice?.url,
      voiceDurationMs: voice?.durationMs ?? 0,
      stickerId: stickerId,
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
      String? clientMsgId, int? refMsgId}) async {
    final id = clientMsgId ?? 'local-${DateTime.now().microsecondsSinceEpoch}';
    final completer = Completer<ChatMessage>();
    _pendingSends[id] = _PendingSend(peerId, completer, text: text);
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
          // 引用(批次 L-2):**只上行 id**,被引用内容由服务端回库查后自己生成快照。
          'ref_msg_id': ?refMsgId,
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
    final refMsgId = message.ref?.msgId;
    if (message.kind == ChatMessageKind.image && message.localPath != null) {
      return sendImage(peerId: message.peerId, imagePath: message.localPath!,
          refMsgId: refMsgId);
    }
    return sendText(peerId: message.peerId, text: message.text,
        clientMsgId: message.msgId, refMsgId: refMsgId);
  }

  @override
  Future<ChatMessage> sendImage({required String peerId, required String imagePath,
      int? refMsgId}) async {
    final uploader = _uploader;
    if (uploader == null) {
      throw const ImException(42202, '当前聊天服务暂不支持图片');
    }
    // 先上传到 Django 拿 URL,再发 WS 帧:顺序不能反,帧里要带服务端校验过的地址
    final image = await uploader.upload(imagePath);
    final id = 'local-${DateTime.now().microsecondsSinceEpoch}';
    final completer = Completer<ChatMessage>();
    _pendingSends[id] = _PendingSend(peerId, completer, image: image);
    for (var attempt = 0; attempt < 3; attempt++) {
      _transport?.send(jsonEncode({
        'v': 1,
        'type': 'send',
        'id': id,
        'data': {
          'client_msg_id': id,
          'to': peerId,
          'kind': 'image',
          'image': image.toPayload(),
          'ref_msg_id': ?refMsgId,
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
  Future<ChatMessage> sendVoice({required String peerId, required String localPath,
      required int durationMs, int? refMsgId}) async {
    final uploader = _voiceUpload;
    if (uploader == null) {
      throw const ImException(42202, '当前聊天服务暂不支持语音');
    }
    // 先上传(Django 会统一转 m4a 并校验时长),再发 WS 帧
    final voice = await uploader.upload(localPath, durationMs);
    final id = 'local-${DateTime.now().microsecondsSinceEpoch}';
    final completer = Completer<ChatMessage>();
    _pendingSends[id] = _PendingSend(peerId, completer, voice: voice);
    for (var attempt = 0; attempt < 3; attempt++) {
      _transport?.send(jsonEncode({
        'v': 1,
        'type': 'send',
        'id': id,
        'data': {
          'client_msg_id': id,
          'to': peerId,
          'kind': 'voice',
          'voice': voice.toPayload(),
          'ref_msg_id': ?refMsgId,
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
  Future<ChatMessage> sendSticker({required String peerId,
      required String stickerId, int? refMsgId}) async {
    // 贴纸复用 kind=2 custom(批次 J):载荷只有 type/id,资源在客户端本地。
    // 服务端会校验 id 形状,不合法回 42201。
    final id = 'local-${DateTime.now().microsecondsSinceEpoch}';
    final completer = Completer<ChatMessage>();
    _pendingSends[id] = _PendingSend(peerId, completer, stickerId: stickerId);
    for (var attempt = 0; attempt < 3; attempt++) {
      _transport?.send(jsonEncode({
        'v': 1,
        'type': 'send',
        'id': id,
        'data': {
          'client_msg_id': id,
          'to': peerId,
          'kind': 'custom',
          'custom': {'type': 'sticker', 'id': stickerId},
          'ref_msg_id': ?refMsgId,
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
        // 已读回执的**离线补拉**入口:断线期间对方读过什么,重连后靠这个字段算。
        peerReadSeq: (item['peer_read_seq'] as num?)?.toInt() ?? 0,
        // 批次 N:置顶 / 免打扰。老 imserver 没有这两个字段 → 一律按 false 兜底,
        // 所以这里必须容忍 null(不能写 `as bool`)。
        pinned: item['pinned'] == true,
        muted: item['muted'] == true,
      );
    }).toList();
  }

  @override
  Future<List<ChatMessage>> fetchHistory(String peerId, {int count = 50, int? beforeSeq}) async {
    final data = await _http!.get('/messages', {
      'peer': peerId,
      'limit': '$count',
      if (beforeSeq != null && beforeSeq > 0) 'before_seq': '$beforeSeq',
    });
    final items = (data['items'] as List? ?? const []).cast<Map<String, dynamic>>();
    return items.map(_messageFromJson).toList();
  }

  @override
  Future<ImSearchResult> searchMessages(String keyword, {int limit = 20, String? beforeId}) async {
    final data = await _http!.get('/search', {
      'q': keyword,
      'limit': '$limit',
      if (beforeId != null && beforeId.isNotEmpty) 'before_id': beforeId,
    });
    final items = (data['items'] as List? ?? const []).cast<Map<String, dynamic>>();
    return ImSearchResult(
      items: items.map((item) {
        final peer = (item['peer'] as Map?)?.cast<String, dynamic>() ?? const {};
        return ImSearchHit(
          msgId: '${item['msg_id'] ?? ''}',
          seq: (item['seq'] as num?)?.toInt() ?? 0,
          peerId: peer['id'] as String? ?? '',
          text: item['text'] as String? ?? '',
          timestamp: (item['ts'] as num?)?.toInt() ?? 0,
          peerName: peer['nickname'] as String?,
          peerAvatar: peer['avatar'] as String?,
        );
      }).toList(),
      hasMore: data['has_more'] == true,
    );
  }

  @override
  Future<void> sendTyping(String peerId) async {
    // 上行 `typing`(批次 L-1):**没有 id、不等 ack**。服务端超限 / 未配对时静默
    // 丢弃,所以这里不登记 _pendingAcks —— 登记了就会永远等不到回执。
    _transport?.send(jsonEncode({
      'v': 1,
      'type': 'typing',
      'data': {'to': peerId},
    }));
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
  Future<void> deleteMessages(List<String> msgIds) async {
    // 单方删除走 HTTP 写接口(批次 T-1/T-2):`POST /messages/delete` 回
    // `{"deleted": n}`。本端**不读这个 n** —— 它就是「本次新隐藏了几条」,
    // 幂等重删时是 0,拿来判断成功与否会把「早就删过」误当失败。
    // 失败(ApiException:401/42201/42901)直接抛给调用方,让页面提示并保留选中。
    if (msgIds.isEmpty) return;
    await _http!.post('/messages/delete', {'ids': msgIds});
  }

  @override
  Future<ImConversationFlags> setConversationFlags(String peerId,
      {bool? pinned, bool? muted}) async {
    // 只上行要改的那一项:另一项缺省 = 不改(服务端不会把它当成 false)。
    final data = await _http!.post('/conversations/flags', {
      'peer': peerId,
      'pinned': ?pinned,
      'muted': ?muted,
    });
    return ImConversationFlags.fromJson(data);
  }

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
    final image = (json['image'] as Map?)?.cast<String, dynamic>() ?? const {};
    final voice = (json['voice'] as Map?)?.cast<String, dynamic>() ?? const {};
    // 引用(批次 L-2):**没有引用时服务端根本不下发这个键**,所以这里必须容忍 null。
    final refJson = (json['ref'] as Map?)?.cast<String, dynamic>();
    final customType = custom['type'] as String? ?? '';
    final messageKind = switch (kind) {
      'custom' when customType == 'match_notice' => ChatMessageKind.matchNotice,
      // 贴纸(批次 J):`{type:"sticker", id:"sticker_NN"}`,资源在本地
      'custom' when customType == 'sticker' => ChatMessageKind.sticker,
      'custom' when customType.isNotEmpty => ChatMessageKind.banNotice,
      'custom' => ChatMessageKind.other,
      'image' => ChatMessageKind.image,
      'voice' => ChatMessageKind.voice,
      _ => ChatMessageKind.text,
    };
    return ChatMessage(
      msgId: '${json['msg_id'] ?? ''}',
      seq: (json['seq'] as num?)?.toInt() ?? 0,
      peerId: isSelf ? to : from,
      isSelf: isSelf,
      timestamp: (json['ts'] as num?)?.toInt() ?? 0,
      kind: messageKind,
      text: kind == 'custom'
          ? (custom['desc'] as String? ?? '')
          : (json['text'] as String? ?? ''),
      imageUrl: image['thumb_url'] as String?,
      imageLargeUrl: image['url'] as String?,
      voiceUrl: voice['url'] as String?,
      voiceDurationMs: (voice['duration_ms'] as num?)?.toInt() ?? 0,
      stickerId: messageKind == ChatMessageKind.sticker
          ? (custom['id'] as String? ?? '')
          : null,
      isRevoked: json['revoked'] == true,
      ref: refJson == null ? null : QuoteRef.fromJson(refJson),
    );
  }
}
