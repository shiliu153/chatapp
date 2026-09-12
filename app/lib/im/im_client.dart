/// IM 领域模型与客户端接口。
///
/// 真实实现在 tencent_im_client.dart(全项目唯一 import 腾讯 SDK 的文件);
/// 测试用 test/support/fake_im_client.dart —— 原生插件在 flutter test 里跑不起来。
enum ChatMessageKind { text, matchNotice, banNotice, image, other }

/// 「系统通知」固定 IM 账号(与后端 im/client.py::SYSTEM_NOTICE_IDENTIFIER 是跨栈契约)。
const systemNoticePeerId = 'system_notice';

class ChatMessage {
  const ChatMessage({
    required this.msgId,
    required this.peerId,
    required this.isSelf,
    required this.timestamp,
    required this.kind,
    this.text = '',
    this.isPending = false,
    this.isFailed = false,
    this.localPath,
    this.imageUrl,
    this.imageLargeUrl,
  });

  final String msgId;

  /// 对端的 IM id,如 'u9'。
  final String peerId;
  final bool isSelf;

  /// 毫秒时间戳(SDK 是秒,映射时转过)。
  final int timestamp;
  final ChatMessageKind kind;
  final String text;

  /// 本地先上屏、服务器回执还没回来。
  final bool isPending;

  /// 发送失败(可点重发)。
  final bool isFailed;

  /// 图片消息的本机文件(发送中先上屏;接收方通常为 null)。
  final String? localPath;

  /// 远程缩略图(气泡里展示用)。
  final String? imageUrl;

  /// 远程原图(全屏查看用)。
  final String? imageLargeUrl;

  ChatMessage copyWith({bool? isPending, bool? isFailed, String? imageUrl}) => ChatMessage(
        msgId: msgId,
        peerId: peerId,
        isSelf: isSelf,
        timestamp: timestamp,
        kind: kind,
        text: text,
        isPending: isPending ?? this.isPending,
        isFailed: isFailed ?? this.isFailed,
        localPath: localPath,
        imageUrl: imageUrl ?? this.imageUrl,
        imageLargeUrl: imageLargeUrl,
      );
}

class ImConversation {
  const ImConversation({
    required this.peerId,
    required this.unreadCount,
    this.showName,
    this.faceUrl,
    this.lastMessage,
  });

  final String peerId;
  final int unreadCount;

  /// IM 侧的名字/头像:昵称已由后端同步(改昵称 → portrait_set),展示优先本地 matches 缓存。
  final String? showName;
  final String? faceUrl;
  final ChatMessage? lastMessage;
}

sealed class ImEvent {
  const ImEvent();
}

class ImNewMessage extends ImEvent {
  const ImNewMessage(this.message);
  final ChatMessage message;
}

/// 会话列表有变化(新会话/新消息/已读/删除)。
class ImConversationsChanged extends ImEvent {
  const ImConversationsChanged();
}

class ImSigExpired extends ImEvent {
  const ImSigExpired();
}

class ImKickedOffline extends ImEvent {
  const ImKickedOffline();
}

/// IM 调用返回非零错误码时抛;code 是腾讯错误码。
class ImException implements Exception {
  const ImException(this.code, this.message);

  final int code;
  final String message;

  @override
  String toString() => 'ImException($code, $message)';
}

abstract class ImClient {
  /// 消息/会话/登录态事件流,ImManager 与聊天控制器都订阅它。
  Stream<ImEvent> get events;

  /// 初始化 SDK;重复调用要幂等。
  Future<void> init({required int sdkAppId});

  Future<void> login({required String userId, required String userSig});

  Future<void> logout();

  /// 全部会话,按最近消息时间倒序。
  Future<List<ImConversation>> fetchConversations();

  /// 单聊历史消息,按时间正序(旧 → 新)。
  Future<List<ChatMessage>> fetchHistory(String peerId, {int count = 50});

  Future<ChatMessage> sendText({required String peerId, required String text});

  Future<ChatMessage> sendImage({required String peerId, required String imagePath});

  /// 删除本地消息(对方不受影响);本地未发出的消息可直接忽略此调用。
  Future<void> deleteMessage(ChatMessage message);

  /// 该 SDK 版本无原生重发:等价于用原内容重新发送。
  Future<ChatMessage> resend(ChatMessage message) {
    if (message.kind == ChatMessageKind.image && message.localPath != null) {
      return sendImage(peerId: message.peerId, imagePath: message.localPath!);
    }
    return sendText(peerId: message.peerId, text: message.text);
  }

  Future<void> markConversationRead(String peerId);

  /// 删除本机会话(拉黑后清理用;对方设备上的会话不受影响)。
  Future<void> deleteConversation(String peerId);
}
