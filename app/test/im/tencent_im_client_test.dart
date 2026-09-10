import 'package:flutter_test/flutter_test.dart';

import 'package:tencent_cloud_chat_sdk/enum/conversation_type.dart';
import 'package:tencent_cloud_chat_sdk/models/v2_tim_message.dart';
import 'package:tencent_cloud_chat_sdk/native_im/adapter/tim_c_enum.dart';
import 'package:chatapp_app/im/im_client.dart';
import 'package:chatapp_app/im/tencent_im_client.dart';

// 直接用 SDK 的 fromJson 造消息对象:它是纯 Dart 实现,不碰 native 库
// (默认构造函数会调 TIMManager.getServerTime,在 flutter test 里跑不了)。
V2TimMessage sdkMessage({
  String id = 'm1',
  required bool isSelf,
  String sender = 'u9',
  String peer = 'u3',
  int timestampSeconds = 1700000000,
  required Map<String, dynamic> elem,
}) =>
    V2TimMessage.fromJson({
      'message_conv_type': ConversationType.V2TIM_C2C,
      'message_conv_id': peer, // C2C 时 SDK 把它填进 userID
      'message_sender': sender,
      'message_is_from_self': isSelf,
      'message_server_time': timestampSeconds,
      'message_msg_id': id,
      // fromJson 直接赋给非空 int 字段,少一个就 Throw
      'message_risk_type_identified': 0,
      'message_elem_array': [elem],
    });

Map<String, dynamic> textElem(String text) =>
    {'elem_type': CElemType.ElemText, 'text_elem_content': text};

Map<String, dynamic> customElem(String data, {String desc = ''}) => {
      'elem_type': CElemType.ElemCustom,
      'custom_elem_data': data,
      'custom_elem_desc': desc,
    };

void main() {
  test('对方发的文本:peerId 取 sender,timestamp 秒转毫秒', () {
    final message = chatMessageFromSdk(sdkMessage(
      isSelf: false,
      peer: 'u3',
      elem: textElem('你好'),
    ));

    expect(message.kind, ChatMessageKind.text);
    expect(message.peerId, 'u9');
    expect(message.isSelf, isFalse);
    expect(message.text, '你好');
    expect(message.timestamp, 1700000000000);
  });

  test('自己发的文本:peerId 取接收者(userID)', () {
    final message = chatMessageFromSdk(sdkMessage(
      isSelf: true,
      peer: 'u3',
      elem: textElem('你好'),
    ));

    expect(message.peerId, 'u3');
    expect(message.isSelf, isTrue);
  });

  test('match_notice 自定义消息 → 灰条,文案取 Desc', () {
    final message = chatMessageFromSdk(sdkMessage(
      isSelf: false,
      elem: customElem('{"type":"match_notice"}', desc: '你们已互相喜欢,开始聊天吧'),
    ));

    expect(message.kind, ChatMessageKind.matchNotice);
    expect(message.text, '你们已互相喜欢,开始聊天吧');
  });

  test('其他自定义消息 → other(不渲染成灰条)', () {
    final message = chatMessageFromSdk(sdkMessage(
      isSelf: false,
      elem: customElem('{"type":"gift"}'),
    ));

    expect(message.kind, ChatMessageKind.other);
  });
}
