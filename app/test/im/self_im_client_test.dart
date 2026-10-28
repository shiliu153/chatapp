import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/im/im_bootstrap.dart';
import 'package:chatapp_app/im/im_client.dart';
import 'package:chatapp_app/im/self_image_uploader.dart';
import 'package:chatapp_app/im/self_im_client.dart';
import 'package:chatapp_app/im/self_transport.dart';
import 'package:chatapp_app/im/self_voice_uploader.dart';

class FakeTransport implements SelfTransport {
  final _frames = StreamController<String>.broadcast();
  final sent = <String>[];
  bool connected = false;

  @override
  Stream<String> get frames => _frames.stream;

  @override
  Future<void> connect(Uri uri) async => connected = true;

  @override
  void send(String frame) => sent.add(frame);

  @override
  Future<void> close() async => _frames.close();

  void emit(String frame) => _frames.add(frame);
}

class FakeHttpClient implements SelfHttpClient {
  @override
  Future<Map<String, dynamic>> get(String path, Map<String, String> query) async {
    if (path == '/messages') {
      return {
        'items': [
          {
            'msg_id': '1',
            'seq': 1,
            'from': 'u2',
            'to': 'u9',
            'kind': 'text',
            'text': 'a',
            'ts': 10,
            'revoked': false,
          }
        ],
      };
    }
    return {
      'items': [
        {
          'peer': {'id': 'u2', 'nickname': '小九', 'avatar': ''},
          'unread': 2,
          'last_seq': 1,
          'updated_at': 10,
          'last_message': {
            'msg_id': '1',
            'seq': 1,
            'from': 'u2',
            'to': 'u9',
            'kind': 'text',
            'text': 'a',
            'ts': 10,
            'revoked': false,
          },
        }
      ],
    };
  }
}

const bootstrap = ImBootstrap(
  backend: ImBackend.self,
  token: 'tok',
  wsUrl: 'ws://test/im/ws',
  httpUrl: 'http://test/im/api',
  imUserId: 'u9',
);

void main() {
  test('login sends auth and completes on auth_ok', () async {
    final transport = FakeTransport();
    final client = SelfImClient(transportFactory: () => transport);
    await client.init(bootstrap);

    final login = client.login(userId: 'u9', userSig: 'tok');
    await pumpEventQueue();
    expect(transport.connected, isTrue);
    expect(transport.sent.single, contains('"type":"auth"'));

    transport.emit('{"v":1,"type":"auth_ok","data":{"uid":9}}');
    await login;
    expect(client.capabilities.image, isTrue);
  });

  test('sendText completes on ack', () async {
    final transport = FakeTransport();
    final client = SelfImClient(transportFactory: () => transport);
    await client.init(bootstrap);
    final login = client.login(userId: 'u9', userSig: 'tok');
    await pumpEventQueue();
    transport.emit('{"v":1,"type":"auth_ok","data":{"uid":9}}');
    await login;

    final future = client.sendText(peerId: 'u2', text: 'hi');
    await pumpEventQueue();
    final frame = jsonDecode(transport.sent.last) as Map<String, dynamic>;
    transport.emit(jsonEncode({
      'v': 1,
      'type': 'ack',
      'id': frame['id'],
      'data': {'msg_id': '100', 'seq': 1, 'ts': 1},
    }));
    final message = await future;
    expect(message.msgId, '100');
    expect(message.text, 'hi');
  });

  test('fetchHistory maps ascending items', () async {
    final transport = FakeTransport();
    final client = SelfImClient(
      transportFactory: () => transport,
      httpClient: FakeHttpClient(),
    );
    await client.init(bootstrap);
    final login = client.login(userId: 'u9', userSig: 'tok');
    await pumpEventQueue();
    transport.emit('{"v":1,"type":"auth_ok","data":{"uid":9}}');
    await login;

    final items = await client.fetchHistory('u2');
    expect(items.single.text, 'a');
    expect(items.single.isSelf, isFalse);
  });

  test('sendImage uploads then sends an image frame and resolves on ack', () async {
    final transport = FakeTransport();
    final uploader = FakeUploader();
    final client = SelfImClient(
        transportFactory: () => transport, imageUploader: uploader);
    await client.init(bootstrap);
    final login = client.login(userId: 'u9', userSig: 'tok');
    await pumpEventQueue();
    transport.emit(jsonEncode({
      'v': 1, 'type': 'auth_ok', 'data': {'uid': 9, 'heartbeat_sec': 25},
    }));
    await login;

    final pending = client.sendImage(peerId: 'u2', imagePath: '/tmp/a.jpg');
    await pumpEventQueue();
    expect(uploader.uploaded, ['/tmp/a.jpg']);
    final frame = jsonDecode(transport.sent.last) as Map<String, dynamic>;
    expect(frame['type'], 'send');
    expect(frame['data']['kind'], 'image');
    expect(frame['data']['image']['thumb_url'], 'http://cdn/media/chat/a_thumb.jpg');

    transport.emit(jsonEncode({
      'v': 1, 'type': 'ack', 'id': frame['id'],
      'data': {'msg_id': '42', 'seq': 1, 'ts': 1700000000000},
    }));
    final sent = await pending;
    expect(sent.kind, ChatMessageKind.image);
    expect(sent.imageUrl, 'http://cdn/media/chat/a_thumb.jpg');
    expect(sent.imageLargeUrl, 'http://cdn/media/chat/a.jpg');
  });

  test('sendImage surfaces upload failure as ImException', () async {
    final transport = FakeTransport();
    final client = SelfImClient(
        transportFactory: () => transport,
        imageUploader: FakeUploader(failure: const ImException(400, '图片不能超过 5MB')));
    await client.init(bootstrap);
    final login = client.login(userId: 'u9', userSig: 'tok');
    await pumpEventQueue();
    transport.emit(jsonEncode({
      'v': 1, 'type': 'auth_ok', 'data': {'uid': 9, 'heartbeat_sec': 25},
    }));
    await login;

    await expectLater(
      client.sendImage(peerId: 'u2', imagePath: '/tmp/a.jpg'),
      throwsA(isA<ImException>()),
    );
    expect(transport.sent.where((raw) => raw.contains('"kind":"image"')), isEmpty);
  });

  test('parses incoming image message', () async {
    final transport = FakeTransport();
    final client = SelfImClient(transportFactory: () => transport);
    await client.init(bootstrap);
    final login = client.login(userId: 'u9', userSig: 'tok');
    await pumpEventQueue();
    transport.emit(jsonEncode({
      'v': 1, 'type': 'auth_ok', 'data': {'uid': 9, 'heartbeat_sec': 25},
    }));
    await login;

    final events = <ImEvent>[];
    client.events.listen(events.add);
    transport.emit(jsonEncode({
      'v': 1, 'type': 'message',
      'data': {
        'msg_id': '7', 'seq': 2, 'from': 'u2', 'to': 'u9', 'kind': 'image',
        'ts': 1700000000000, 'revoked': false,
        'image': {'url': 'http://cdn/media/chat/b.jpg',
                  'thumb_url': 'http://cdn/media/chat/b_thumb.jpg',
                  'width': 10, 'height': 20, 'size': 100},
      },
    }));
    await pumpEventQueue();
    final message = (events.first as ImNewMessage).message;
    expect(message.kind, ChatMessageKind.image);
    expect(message.imageUrl, 'http://cdn/media/chat/b_thumb.jpg');
    expect(message.imageLargeUrl, 'http://cdn/media/chat/b.jpg');
  });

  test('searchMessages 把关键词与游标带给 /search', () async {
    final http = RecordingHttpClient({
      'items': [
        {
          'msg_id': '42',
          'seq': 7,
          'from': 'u9',
          'to': 'u2',
          'ts': 1761465600000,
          'kind': 'text',
          'text': '晚上吃火锅吗',
          'peer': {'id': 'u2', 'nickname': '阿九', 'avatar': 'https://a/9.png'},
        },
      ],
      'has_more': true,
    });
    final client = SelfImClient(httpClient: http);
    await client.init(bootstrap);
    final login = client.login(userId: 'u9', userSig: 'tok');
    await pumpEventQueue();
    // 没有 transport 时 login 永远等不到 auth_ok,这里只验证 HTTP 行为,直接放弃等。
    unawaited(login.catchError((_) {}));

    final result = await client.searchMessages('火锅', limit: 10, beforeId: '99');
    expect(http.calls.single,
        '/search?q=${Uri.encodeComponent('火锅')}&limit=10&before_id=99');
    expect(result.items.single.text, '晚上吃火锅吗');
    expect(result.items.single.peerId, 'u2');
    expect(result.items.single.peerName, '阿九');
    expect(result.items.single.seq, 7);
    expect(result.hasMore, isTrue);
    expect(client.capabilities.search, isTrue);
  });

  test('fetchHistory 传 beforeSeq 时带上 before_seq', () async {
    final http = RecordingHttpClient({'items': []});
    final client = SelfImClient(httpClient: http);
    await client.init(bootstrap);
    await client.fetchHistory('u2', count: 50, beforeSeq: 12);
    expect(http.calls.single, '/messages?peer=u2&limit=50&before_seq=12');
  });

  test('sendVoice 上传后发 kind=voice 帧并在 ack 后返回语音消息', () async {
    final transport = FakeTransport();
    final uploader = FakeVoiceUploader();
    final client = SelfImClient(
        transportFactory: () => transport, voiceUploader: uploader);
    await client.init(bootstrap);
    final login = client.login(userId: 'u9', userSig: 'tok');
    await pumpEventQueue();
    transport.emit(jsonEncode({
      'v': 1, 'type': 'auth_ok', 'data': {'uid': 9, 'heartbeat_sec': 25},
    }));
    await login;

    final pending = client.sendVoice(
        peerId: 'u2', localPath: '/tmp/a.m4a', durationMs: 12500);
    await pumpEventQueue();
    expect(uploader.uploads.single, ('/tmp/a.m4a', 12500));
    final frame = jsonDecode(transport.sent.last) as Map<String, dynamic>;
    expect(frame['data']['kind'], 'voice');
    expect(frame['data']['voice']['url'], 'http://cdn/media/chat/voices/a.m4a');
    expect(frame['data']['voice']['duration_ms'], 12500);
    expect(client.capabilities.voice, isTrue);

    transport.emit(jsonEncode({
      'v': 1, 'type': 'ack', 'id': frame['id'],
      'data': {'msg_id': '77', 'seq': 3, 'ts': 1700000000000},
    }));
    final sent = await pending;
    expect(sent.kind, ChatMessageKind.voice);
    expect(sent.voiceUrl, 'http://cdn/media/chat/voices/a.m4a');
    expect(sent.voiceDurationMs, 12500);
  });

  test('sendVoice 没有上传器时抛 42202 且不发帧', () async {
    final transport = FakeTransport();
    final client = SelfImClient(transportFactory: () => transport);
    await client.init(bootstrap);
    final login = client.login(userId: 'u9', userSig: 'tok');
    await pumpEventQueue();
    transport.emit(jsonEncode({
      'v': 1, 'type': 'auth_ok', 'data': {'uid': 9, 'heartbeat_sec': 25},
    }));
    await login;

    await expectLater(
      client.sendVoice(peerId: 'u2', localPath: '/tmp/a.m4a', durationMs: 3000),
      throwsA(isA<ImException>()),
    );
    expect(transport.sent.where((raw) => raw.contains('"kind":"voice"')), isEmpty);
  });

  test('parses incoming voice message', () async {
    final transport = FakeTransport();
    final client = SelfImClient(transportFactory: () => transport);
    await client.init(bootstrap);
    final login = client.login(userId: 'u9', userSig: 'tok');
    await pumpEventQueue();
    transport.emit(jsonEncode({
      'v': 1, 'type': 'auth_ok', 'data': {'uid': 9, 'heartbeat_sec': 25},
    }));
    await login;

    final events = <ImEvent>[];
    client.events.listen(events.add);
    transport.emit(jsonEncode({
      'v': 1, 'type': 'message',
      'data': {
        'msg_id': '8', 'seq': 3, 'from': 'u2', 'to': 'u9', 'kind': 'voice',
        'ts': 1700000000000, 'revoked': false,
        'voice': {'url': 'http://cdn/media/chat/voices/b.m4a?e=1&s=2',
                  'duration_ms': 8000, 'size': 24000},
      },
    }));
    await pumpEventQueue();
    final message = (events.first as ImNewMessage).message;
    expect(message.kind, ChatMessageKind.voice);
    expect(message.voiceUrl, 'http://cdn/media/chat/voices/b.m4a?e=1&s=2');
    expect(message.voiceDurationMs, 8000);
  });
}

/// 记录调用并按路径返回固定响应的假 HTTP 客户端。
class RecordingHttpClient implements SelfHttpClient {
  RecordingHttpClient(this.response);
  final Map<String, dynamic> response;
  final List<String> calls = [];

  @override
  Future<Map<String, dynamic>> get(String path, Map<String, String> query) async {
    calls.add('$path?${Uri(queryParameters: query).query}');
    return response;
  }
}

class FakeUploader implements SelfImageUploader {
  FakeUploader({this.failure});
  final Object? failure;
  final uploaded = <String>[];

  @override
  Future<ChatImageUpload> upload(String localPath) async {
    uploaded.add(localPath);
    if (failure != null) throw failure!;
    return const ChatImageUpload(
      id: 1,
      url: 'http://cdn/media/chat/a.jpg',
      thumbUrl: 'http://cdn/media/chat/a_thumb.jpg',
      width: 1080,
      height: 1440,
      size: 345678,
    );
  }
}

class FakeVoiceUploader implements SelfVoiceUploader {
  FakeVoiceUploader({this.failure});
  final Object? failure;
  final uploads = <(String, int)>[];

  @override
  Future<ChatVoiceUpload> upload(String localPath, int durationMs) async {
    uploads.add((localPath, durationMs));
    if (failure != null) throw failure!;
    return const ChatVoiceUpload(
      id: 2,
      url: 'http://cdn/media/chat/voices/a.m4a',
      durationMs: 12500,
      size: 48000,
    );
  }
}
