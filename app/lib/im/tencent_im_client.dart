import 'dart:async';
import 'dart:convert';

import 'package:tencent_cloud_chat_sdk/enum/V2TimAdvancedMsgListener.dart';
import 'package:tencent_cloud_chat_sdk/enum/V2TimConversationListener.dart';
import 'package:tencent_cloud_chat_sdk/enum/V2TimSDKListener.dart';
import 'package:tencent_cloud_chat_sdk/enum/log_level_enum.dart';
import 'package:tencent_cloud_chat_sdk/enum/message_elem_type.dart';
import 'package:tencent_cloud_chat_sdk/models/v2_tim_conversation.dart';
import 'package:tencent_cloud_chat_sdk/models/v2_tim_message.dart'
    if (dart.library.html) 'package:tencent_cloud_chat_sdk/web/compatible_models/v2_tim_message.dart';
import 'package:tencent_cloud_chat_sdk/tencent_im_sdk_plugin.dart';

import 'im_client.dart';

/// SDK 消息对象 → 领域模型。纯函数,单测直接构造 SDK 对象就能测。
ChatMessage chatMessageFromSdk(V2TimMessage message) {
  final isSelf = message.isSelf ?? false;
  final kind = _kindOf(message);
  return ChatMessage(
    msgId: message.msgID ?? '',
    // 单聊消息:自己发的消息 userID 是接收者,对方发的是 sender
    peerId: (isSelf ? message.userID : message.sender) ?? '',
    isSelf: isSelf,
    timestamp: (message.timestamp ?? 0) * 1000,
    kind: kind,
    text: switch (kind) {
      ChatMessageKind.text => message.textElem?.text ?? '',
      ChatMessageKind.matchNotice => message.customElem?.desc ?? '',
      ChatMessageKind.banNotice => message.customElem?.desc ?? '',
      ChatMessageKind.other => '',
    },
  );
}

ChatMessageKind _kindOf(V2TimMessage message) {
  if (message.elemType == MessageElemType.V2TIM_ELEM_TYPE_TEXT) {
    return ChatMessageKind.text;
  }
  if (message.elemType == MessageElemType.V2TIM_ELEM_TYPE_CUSTOM) {
    final type = _customType(message.customElem?.data);
    if (type == 'match_notice') return ChatMessageKind.matchNotice;
    if (type == 'ban_notice' || type == 'ban_lifted') {
      return ChatMessageKind.banNotice;
    }
  }
  return ChatMessageKind.other;
}

String? _customType(String? data) {
  if (data == null || data.isEmpty) return null;
  try {
    final decoded = jsonDecode(data);
    return decoded is Map ? decoded['type'] as String? : null;
  } catch (_) {
    return null;
  }
}

ImConversation conversationFromSdk(V2TimConversation conversation) => ImConversation(
      peerId: conversation.userID ?? '',
      unreadCount: conversation.unreadCount ?? 0,
      showName: conversation.showName,
      faceUrl: conversation.faceUrl,
      lastMessage:
          conversation.lastMessage == null ? null : chatMessageFromSdk(conversation.lastMessage!),
    );

class TencentImClient implements ImClient {
  final _events = StreamController<ImEvent>.broadcast();
  bool _initialized = false;

  @override
  Stream<ImEvent> get events => _events.stream;

  @override
  Future<void> init({required int sdkAppId}) async {
    if (_initialized) return;
    final manager = TencentImSDKPlugin.v2TIMManager;
    final result = await manager.initSDK(
      sdkAppID: sdkAppId,
      loglevel: LogLevelEnum.V2TIM_LOG_INFO,
      listener: V2TimSDKListener(
        onUserSigExpired: () => _events.add(const ImSigExpired()),
        onKickedOffline: () => _events.add(const ImKickedOffline()),
      ),
    );
    _check(result.code, result.desc);
    _initialized = true;

    manager.getMessageManager().addAdvancedMsgListener(
          listener: V2TimAdvancedMsgListener(
            onRecvNewMessage: (message) => _events.add(ImNewMessage(chatMessageFromSdk(message))),
          ),
        );
    manager.getConversationManager().addConversationListener(
          listener: V2TimConversationListener(
            onNewConversation: (_) => _events.add(const ImConversationsChanged()),
            onConversationChanged: (_) => _events.add(const ImConversationsChanged()),
          ),
        );
  }

  @override
  Future<void> login({required String userId, required String userSig}) async {
    final result = await TencentImSDKPlugin.v2TIMManager.login(userID: userId, userSig: userSig);
    _check(result.code, result.desc);
  }

  @override
  Future<void> logout() async {
    // 没登录就登出会报错,但这种「已经是想要的终态」不该炸上层流程
    await TencentImSDKPlugin.v2TIMManager.logout();
  }

  @override
  Future<List<ImConversation>> fetchConversations() async {
    final result =
        await TencentImSDKPlugin.v2TIMManager.getConversationManager().getConversationList(
              nextSeq: '0',
              count: 100,
            );
    _check(result.code, result.desc);
    final list = result.data?.conversationList ?? const <V2TimConversation>[];
    return list.map(conversationFromSdk).where((item) => item.peerId.isNotEmpty).toList();
  }

  @override
  Future<List<ChatMessage>> fetchHistory(String peerId, {int count = 50}) async {
    final result = await TencentImSDKPlugin.v2TIMManager
        .getMessageManager()
        .getC2CHistoryMessageList(userID: peerId, count: count);
    _check(result.code, result.desc);
    final list = result.data ?? const <V2TimMessage>[];
    // SDK 给的是新 → 旧,界面要旧 → 新
    return list.map(chatMessageFromSdk).toList().reversed.toList();
  }

  @override
  Future<ChatMessage> sendText({required String peerId, required String text}) async {
    final manager = TencentImSDKPlugin.v2TIMManager.getMessageManager();
    final created = await manager.createTextMessage(text: text);
    _check(created.code, created.desc);

    final sent = await manager.sendMessage(
      // web 分支只认 id(不转 message 对象),两个都传保持两端一致
      // ignore: deprecated_member_use
      id: created.data!.id,
      message: created.data!.messageInfo,
      receiver: peerId,
      groupID: '', // 单聊固定空串
    );
    _check(sent.code, sent.desc);
    return chatMessageFromSdk(sent.data!);
  }

  @override
  Future<void> markConversationRead(String peerId) async {
    final manager = TencentImSDKPlugin.v2TIMManager.getConversationManager();
    final conversationID = 'c2c_$peerId';
    final fetched = await manager.getConversation(conversationID: conversationID);
    final last = fetched.data?.lastMessage;
    final result = await manager.cleanConversationUnreadMessageCount(
      conversationID: conversationID,
      cleanTimestamp: last?.timestamp ?? DateTime.now().millisecondsSinceEpoch ~/ 1000,
      cleanSequence: int.tryParse(last?.seq ?? '') ?? 0,
    );
    _check(result.code, result.desc);
  }

  @override
  Future<void> deleteConversation(String peerId) async {
    final result = await TencentImSDKPlugin.v2TIMManager
        .getConversationManager()
        .deleteConversation(conversationID: 'c2c_$peerId');
    _check(result.code, result.desc);
  }
}

void _check(int code, String message) {
  if (code != 0) throw ImException(code, message);
}
