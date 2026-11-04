// 跨栈协议 fixture 契约测试(backlog E-2)。
//
// 用 App 的**真实解析路径**吃 `imserver/tests/fixtures/ws/*.json`:
// 下行帧断言产出的事件/消息模型,上行帧断言客户端实际发出的 JSON 与 fixture 一致。
// 服务端改了帧格式(或只改了 fixture)时这里会红,不再依赖人工手测。
// 契约与改法见 `imserver/tests/fixtures/ws/README.md`。
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/im/im_bootstrap.dart';
import 'package:chatapp_app/im/im_client.dart';
import 'package:chatapp_app/im/self_image_uploader.dart';
import 'package:chatapp_app/im/self_im_client.dart';
import 'package:chatapp_app/im/self_transport.dart';
import 'package:chatapp_app/im/self_voice_uploader.dart';

/// 假传输:只记录客户端发出的帧,并把测试注入的帧喂给客户端。
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
  Future<void> close() async {
    if (!_frames.isClosed) await _frames.close();
  }

  /// 模拟服务端下发一帧。
  void emit(String frame) {
    if (!_frames.isClosed) _frames.add(frame);
  }
}

/// 假图片上传器:返回与 fixture 完全一致的图片元数据。
class FakeImageUploader implements SelfImageUploader {
  @override
  Future<ChatImageUpload> upload(String localPath) async => const ChatImageUpload(
        id: 1,
        url: 'http://cdn/media/chat/a.jpg',
        thumbUrl: 'http://cdn/media/chat/a_thumb.jpg',
        width: 1080,
        height: 1440,
        size: 345678,
      );
}

/// 假语音上传器:返回与 fixture 完全一致的语音元数据。
class FakeVoiceUploader implements SelfVoiceUploader {
  @override
  Future<ChatVoiceUpload> upload(String localPath, int durationMs) async =>
      const ChatVoiceUpload(
        id: 2,
        url: 'http://cdn/media/chat/v.m4a',
        durationMs: 3200,
        size: 12345,
      );
}

const bootstrap = ImBootstrap(
  token: 'tok',
  wsUrl: 'ws://test/im/ws',
  httpUrl: 'http://test/im/api',
  imUserId: 'u9',
);

/// 读取仓库里共享的协议 fixture。
///
/// Args:
///   name: 文件名(`server_to_client.json` / `client_to_server.json`)。
///
/// Returns:
///   解析后的 JSON 文档。
Map<String, dynamic> loadFixture(String name) {
  final file = File('../imserver/tests/fixtures/ws/$name');
  expect(
    file.existsSync(),
    isTrue,
    reason: '找不到协议 fixture:${file.absolute.path}(测试工作目录应是 app/)',
  );
  return jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
}

/// 按名字取 fixture 里的一帧。
///
/// Args:
///   document: 整个 fixture 文件。
///   name: 帧名。
///
/// Returns:
///   帧对象。
Map<String, dynamic> frameOf(Map<String, dynamic> document, String name) {
  for (final item in document['frames'] as List) {
    final entry = item as Map<String, dynamic>;
    if (entry['name'] == name) {
      return entry['frame'] as Map<String, dynamic>;
    }
  }
  fail('fixture 里没有帧:$name');
}

/// 把客户端实际发出的帧与 fixture 逐字段比对。
///
/// 客户端会生成动态 id(`local-…` / `read-…`),比对前把 id 与 `client_msg_id`
/// 归一化成 fixture 里的值;其余字段必须完全一致。
///
/// Args:
///   actual: 客户端实际发出的帧(已 JSON 解码)。
///   fixture: 契约里的期望帧。
void expectFrameMatches(Map<String, dynamic> actual, Map<String, dynamic> fixture) {
  final normalized = jsonDecode(jsonEncode(actual)) as Map<String, dynamic>;
  normalized['id'] = fixture['id'];
  final data = normalized['data'] as Map<String, dynamic>;
  if (data.containsKey('client_msg_id')) {
    data['client_msg_id'] = (fixture['data'] as Map<String, dynamic>)['client_msg_id'];
  }
  expect(normalized, fixture);
}

/// 登录并返回已就绪的客户端与传输。
///
/// Args:
///   uploader: 是否注入假图片/语音上传器(发媒体帧的用例需要)。
///
/// Returns:
///   (客户端, 假传输)。
Future<(SelfImClient, FakeTransport)> loginClient({bool uploader = false}) async {
  final transport = FakeTransport();
  final client = SelfImClient(
    transportFactory: () => transport,
    imageUploader: uploader ? FakeImageUploader() : null,
    voiceUploader: uploader ? FakeVoiceUploader() : null,
  );
  await client.init(bootstrap);
  final login = client.login(userId: 'u9', token: 'tok');
  await pumpEventQueue();
  transport.emit(jsonEncode(frameOf(loadFixture('server_to_client.json'), 'auth_ok')));
  await login;
  await pumpEventQueue();
  return (client, transport);
}

void main() {
  test('下行 fixture:消息与事件模型符合契约', () async {
    final server = loadFixture('server_to_client.json');
    final (client, transport) = await loginClient();
    final events = <ImEvent>[];
    final sub = client.events.listen(events.add);

    // 文本消息
    transport.emit(jsonEncode(frameOf(server, 'message_text')));
    await pumpEventQueue();
    final text = events.whereType<ImNewMessage>().single.message;
    expect(text.msgId, '900124');
    expect(text.seq, 42);
    expect(text.text, '你好');
    expect(text.peerId, 'u2');
    expect(text.isSelf, isFalse);
    expect(text.timestamp, 1720000000000);
    expect(text.kind, ChatMessageKind.text);
    expect(text.isRevoked, isFalse);

    // 图片消息:thumb_url 给缩略图,url 给大图
    events.clear();
    transport.emit(jsonEncode(frameOf(server, 'message_image')));
    await pumpEventQueue();
    final image = events.whereType<ImNewMessage>().single.message;
    expect(image.kind, ChatMessageKind.image);
    expect(image.imageUrl, 'http://cdn/media/chat/a_thumb.jpg');
    expect(image.imageLargeUrl, 'http://cdn/media/chat/a.jpg');

    // 语音消息
    events.clear();
    transport.emit(jsonEncode(frameOf(server, 'message_voice')));
    await pumpEventQueue();
    final voice = events.whereType<ImNewMessage>().single.message;
    expect(voice.kind, ChatMessageKind.voice);
    expect(voice.voiceUrl, 'http://cdn/media/chat/v.m4a');
    expect(voice.voiceDurationMs, 3200);

    // 下行已读回执
    events.clear();
    transport.emit(jsonEncode(frameOf(server, 'read_down')));
    await pumpEventQueue();
    final read = events.whereType<ImPeerRead>().single;
    expect(read.peerId, 'u2');
    expect(read.seq, 42);

    // 撤回广播
    events.clear();
    transport.emit(jsonEncode(frameOf(server, 'revoked')));
    await pumpEventQueue();
    expect(events.whereType<ImMessageRevoked>().single.msgId, '900124');

    // pong 与普通错误不产生业务事件
    events.clear();
    transport.emit(jsonEncode(frameOf(server, 'pong')));
    transport.emit(jsonEncode(frameOf(server, 'error_42201')));
    await pumpEventQueue();
    expect(events, isEmpty);

    await sub.cancel();
  });

  test('终止类下行帧:error 40101 → 令牌过期,kicked → 被顶下线', () async {
    final server = loadFixture('server_to_client.json');

    final (expiredClient, expiredTransport) = await loginClient();
    final expiredEvents = <ImEvent>[];
    final expiredSub = expiredClient.events.listen(expiredEvents.add);
    expiredTransport.emit(jsonEncode(frameOf(server, 'error_40101')));
    await pumpEventQueue();
    expect(expiredEvents.whereType<ImSigExpired>(), hasLength(1));
    await expiredSub.cancel();

    final (kickedClient, kickedTransport) = await loginClient();
    final kickedEvents = <ImEvent>[];
    final kickedSub = kickedClient.events.listen(kickedEvents.add);
    kickedTransport.emit(jsonEncode(frameOf(server, 'kicked')));
    await pumpEventQueue();
    expect(kickedEvents.whereType<ImKickedOffline>(), hasLength(1));
    await kickedSub.cancel();
  });

  test('上行 fixture:客户端发出的帧与契约一致', () async {
    final server = loadFixture('server_to_client.json');
    final clientToServer = loadFixture('client_to_server.json');
    final (client, transport) = await loginClient(uploader: true);

    // auth:登录首帧(动态部分是 token,换成测试令牌后逐字段比对)
    final auth = jsonDecode(transport.sent.first) as Map<String, dynamic>;
    final expectedAuth = jsonDecode(jsonEncode(frameOf(clientToServer, 'auth')))
        as Map<String, dynamic>;
    expectedAuth['data']['token'] = 'tok';
    expect(auth, expectedAuth);

    // send_text:发出去后服务端回 ack_send
    final sending = client.sendText(peerId: 'u2', text: '你好');
    await pumpEventQueue();
    final sendText = jsonDecode(transport.sent.last) as Map<String, dynamic>;
    expectFrameMatches(sendText, frameOf(clientToServer, 'send_text'));
    final ack = jsonDecode(jsonEncode(frameOf(server, 'ack_send'))) as Map<String, dynamic>;
    ack['id'] = sendText['id'];
    transport.emit(jsonEncode(ack));
    final message = await sending;
    expect(message.msgId, '900124');
    expect(message.text, '你好');
    expect(message.timestamp, 1720000000000);

    // send_image
    final sendingImage = client.sendImage(peerId: 'u2', imagePath: '/tmp/a.jpg');
    await pumpEventQueue();
    final sendImage = jsonDecode(transport.sent.last) as Map<String, dynamic>;
    expectFrameMatches(sendImage, frameOf(clientToServer, 'send_image'));
    final imageAck = jsonDecode(jsonEncode(frameOf(server, 'ack_send')))
        as Map<String, dynamic>;
    imageAck['id'] = sendImage['id'];
    transport.emit(jsonEncode(imageAck));
    await sendingImage;

    // send_voice
    final sendingVoice =
        client.sendVoice(peerId: 'u2', localPath: '/tmp/v.m4a', durationMs: 3200);
    await pumpEventQueue();
    final sendVoice = jsonDecode(transport.sent.last) as Map<String, dynamic>;
    expectFrameMatches(sendVoice, frameOf(clientToServer, 'send_voice'));
    final voiceAck = jsonDecode(jsonEncode(frameOf(server, 'ack_send')))
        as Map<String, dynamic>;
    voiceAck['id'] = sendVoice['id'];
    transport.emit(jsonEncode(voiceAck));
    await sendingVoice;

    // read
    await client.markConversationRead('u2');
    expectFrameMatches(
      jsonDecode(transport.sent.last) as Map<String, dynamic>,
      frameOf(clientToServer, 'read'),
    );

    // revoke:等 ack_ok 才返回
    final revoking = client.revokeMessage('900123');
    await pumpEventQueue();
    final revoke = jsonDecode(transport.sent.last) as Map<String, dynamic>;
    expectFrameMatches(revoke, frameOf(clientToServer, 'revoke'));
    final revokeAck = jsonDecode(jsonEncode(frameOf(server, 'ack_ok')))
        as Map<String, dynamic>;
    revokeAck['id'] = revoke['id'];
    transport.emit(jsonEncode(revokeAck));
    await revoking;

    // conversation_delete
    await client.deleteConversation('u2');
    expectFrameMatches(
      jsonDecode(transport.sent.last) as Map<String, dynamic>,
      frameOf(clientToServer, 'conversation_delete'),
    );
  });
}
