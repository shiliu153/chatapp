import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/im/im_bootstrap.dart';
import 'package:chatapp_app/im/self_im_client.dart';
import 'package:chatapp_app/im/self_transport.dart';

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
    expect(client.capabilities.image, isFalse);
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
}
