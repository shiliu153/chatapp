/// IM 领域模型与客户端接口。
///
/// 真实实现只有自建一套(`self_im_client.dart`);腾讯分支已于 2026-11-08 删除。
library;

import 'im_bootstrap.dart';

enum ChatMessageKind { text, matchNotice, banNotice, image, voice, sticker, other }

/// 「系统通知」固定 IM 账号(与后端 im/client.py::SYSTEM_NOTICE_IDENTIFIER 是跨栈契约)。
const systemNoticePeerId = 'system_notice';

/// IM id → 账号 id:'u' + user_id(与后端 `User.im_user_id` 是跨栈契约)。
/// 在线状态等公开信息靠它解析,**不依赖配对缓存**;解析不出来(如系统通知)返回 null。
int? userIdFromImId(String imUserId) {
  if (!imUserId.startsWith('u')) return null;
  return int.tryParse(imUserId.substring(1));
}

/// 账号在另一台设备登录(被 imserver 踢下线)时给用户的提示。
const kickedOfflineMessage = '账号已在其他设备登录,请重新登录';

/// 引用快照(批次 L-2):被引用消息的**服务端摘要**。
///
/// 为什么客户端不自己拼:让客户端传快照等于允许任何人伪造「对方说过 X」。
/// 上行只发 `ref_msg_id`,这里的内容全部由服务端回库查后生成。
class QuoteRef {
  const QuoteRef({
    required this.msgId,
    required this.from,
    required this.kind,
    required this.text,
    required this.revoked,
  });

  /// 被引用消息的 id(数字;下行 `ref.msg_id`)。
  final int msgId;

  /// 被引用消息的发送者 IM id(如 `u9`),用来判断引用块该署谁的名。
  final String from;

  /// `text` / `image` / `voice` / `custom`(贴纸)。
  final String kind;

  /// 摘要:文本取前 120 字,图片/语音/贴纸是 `[图片]` / `[语音]` / `[贴纸]`;
  /// 已撤回时为空串。
  final String text;

  /// 被引用消息已撤回:引用块只显示「消息已撤回」,不显示原文。
  final bool revoked;

  /// 引用块里的摘要文案。
  String get displayText {
    if (revoked) return '消息已撤回';
    return text.isEmpty ? '[消息]' : text;
  }

  /// 从下行 `ref` 对象解析。
  ///
  /// Args:
  ///   json: 下行帧 / 历史接口里的 `ref` 对象。
  ///
  /// Returns:
  ///   引用快照模型。
  factory QuoteRef.fromJson(Map<String, dynamic> json) => QuoteRef(
        msgId: (json['msg_id'] as num?)?.toInt() ?? 0,
        from: json['from'] as String? ?? '',
        kind: json['kind'] as String? ?? 'text',
        text: json['text'] as String? ?? '',
        revoked: json['revoked'] == true,
      );
}

/// 我在输入框里选中的引用目标(批次 L-2):只活在当前会话,发送后即清空。
class QuoteTarget {
  const QuoteTarget({required this.msgId, required this.from, required this.text});

  /// 被引用消息 id(上行 `ref_msg_id`)。
  final int msgId;

  /// 被引用消息的发送者 IM id(引用条上署名用)。
  final String from;

  /// 本地摘要(引用条上展示);**上行不发送它**,服务端会自己生成快照。
  final String text;
}

class ChatMessage {
  const ChatMessage({
    required this.msgId,
    required this.peerId,
    required this.isSelf,
    required this.timestamp,
    required this.kind,
    this.seq = 0,
    this.text = '',
    this.isPending = false,
    this.isFailed = false,
    this.localPath,
    this.imageUrl,
    this.imageLargeUrl,
    this.voiceUrl,
    this.voiceDurationMs = 0,
    this.stickerId,
    this.isRevoked = false,
    this.ref,
  });

  final String msgId;

  /// 会话内序号(由 imserver 解析)。回溯翻页要用。
  final int seq;

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

  /// 语音消息的远程地址(播放用)。
  final String? voiceUrl;

  /// 语音时长(毫秒),气泡宽度与秒数展示用。
  final int voiceDurationMs;

  /// 贴纸 id(如 `sticker_01`)。只有 [ChatMessageKind.sticker] 有值;
  /// 资源在客户端本地(`assets/stickers/<id>.png`),消息里只传 id。
  final String? stickerId;

  /// 已被撤回(自己撤回或对方撤回):界面渲染成居中灰字,不再显示内容。
  final bool isRevoked;

  /// 引用快照(批次 L-2):这条消息引用的是哪条、摘要是什么。
  ///
  /// 为 null = 没有引用。**上行只发 `ref_msg_id`**,这里的快照一律由服务端生成。
  final QuoteRef? ref;

  ChatMessage copyWith({bool? isPending, bool? isFailed, String? imageUrl, bool? isRevoked,
      String? voiceUrl, int? voiceDurationMs, String? stickerId, QuoteRef? ref}) =>
      ChatMessage(
        msgId: msgId,
        seq: seq,
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
        voiceUrl: voiceUrl ?? this.voiceUrl,
        voiceDurationMs: voiceDurationMs ?? this.voiceDurationMs,
        stickerId: stickerId ?? this.stickerId,
        isRevoked: isRevoked ?? this.isRevoked,
        ref: ref ?? this.ref,
      );
}

class ImConversation {
  const ImConversation({
    required this.peerId,
    required this.unreadCount,
    this.showName,
    this.faceUrl,
    this.lastMessage,
    this.peerReadSeq = 0,
  });

  final String peerId;
  final int unreadCount;

  /// IM 侧的名字/头像:昵称已由后端同步(改昵称 → portrait_set),展示优先本地 matches 缓存。
  final String? showName;
  final String? faceUrl;
  final ChatMessage? lastMessage;

  /// **对端**读到哪(0 = 从没读过)。`seq <= peerReadSeq` 的我方消息算已读。
  /// 与 `unreadCount`(我没读的条数)是两条独立链路,别混。
  final int peerReadSeq;

  /// 只换未读条数,其余字段原样保留(跨端已读同步 K-3 用)。
  ///
  /// Args:
  ///   unreadCount: 新的未读条数;省略则保持原值。
  ///
  /// Returns:
  ///   新的 [ImConversation] 实例(模型不可变,不就地改)。
  ImConversation copyWith({int? unreadCount}) => ImConversation(
        peerId: peerId,
        unreadCount: unreadCount ?? this.unreadCount,
        showName: showName,
        faceUrl: faceUrl,
        lastMessage: lastMessage,
        peerReadSeq: peerReadSeq,
      );
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

/// 消息被撤回(自己撤回或对方撤回都走这里)。
class ImMessageRevoked extends ImEvent {
  const ImMessageRevoked(this.msgId);
  final String msgId;
}

/// 对端读到了 `seq`(已读回执)。**只增不减**:收到更小的值直接忽略。
class ImPeerRead extends ImEvent {
  const ImPeerRead({required this.peerId, required this.seq});
  final String peerId;
  final int seq;
}

/// **我**在另一台设备上把与 [peerId] 的会话读到了 [seq](多端在线 K-3)。
///
/// 与 [ImPeerRead] 的区别是视角:[ImPeerRead] 是「**对端**读到 seq」,用来把我方气泡
/// 标成「已读」;这个是「**我自己**在另一台设备上读到 seq」,收帧端只把自己这边的
/// 未读清零,**绝不能**拿去推进「对端读到哪」——那会变成假已读。
class ImSelfRead extends ImEvent {
  const ImSelfRead({required this.peerId, required this.seq});
  final String peerId;
  final int seq;
}

/// **我**在另一台设备上删除了与 [peerId] 的会话(多端在线 K-3)。
///
/// 只发给我自己的其他端:删会话是单方行为,对方不会收到这个事件。
class ImConversationDeleted extends ImEvent {
  const ImConversationDeleted(this.peerId);
  final String peerId;
}

/// 对端 [peerId] 正在输入(批次 L-1)。
///
/// **可丢信号**:服务端不落库、不补拉、超限静默丢弃,所以收不到是常态。
/// 客户端只该把它当成「最近 5 秒对方在打字」的瞬时提示,不能拿它推断任何
/// 持久状态(比如「对方在不在」——那是在线状态的事)。
class ImTyping extends ImEvent {
  const ImTyping({required this.peerId});
  final String peerId;
}

class ImSigExpired extends ImEvent {
  const ImSigExpired();
}

class ImKickedOffline extends ImEvent {
  const ImKickedOffline();
}

/// IM 调用返回非零错误码时抛;code 是 imserver 的业务码(如 40101 登录过期)。
class ImException implements Exception {
  const ImException(this.code, this.message);

  final int code;
  final String message;

  @override
  String toString() => 'ImException($code, $message)';
}

class ImCapabilities {
  const ImCapabilities({
    required this.image,
    this.search = false,
    this.voice = false,
    this.readReceipt = false,
  });
  final bool image;

  /// 是否支持聊天记录搜索(当前自建实现支持)。
  final bool search;

  /// 是否支持语音消息(当前自建实现支持)。
  final bool voice;

  /// 是否支持已读回执(自建实现支持;没有「对方读到哪」时不要显示假状态)。
  final bool readReceipt;
}

/// 一条搜索命中(只可能是文本消息)。
class ImSearchHit {
  const ImSearchHit({
    required this.msgId,
    required this.seq,
    required this.peerId,
    required this.text,
    required this.timestamp,
    this.peerName,
    this.peerAvatar,
  });

  final String msgId;

  /// 会话内序号(回溯翻页用)。
  final int seq;

  /// 对端 IM id,如 'u9'。
  final String peerId;
  final String text;

  /// 毫秒时间戳。
  final int timestamp;
  final String? peerName;
  final String? peerAvatar;
}

/// 一页搜索结果。
class ImSearchResult {
  const ImSearchResult({required this.items, required this.hasMore});
  final List<ImSearchHit> items;
  final bool hasMore;
}

abstract class ImClient {
  /// 消息/会话/登录态事件流,ImManager 与聊天控制器都订阅它。
  Stream<ImEvent> get events;

  /// 当前后端支持的能力(自建暂不支持图片)。
  ImCapabilities get capabilities;

  /// 初始化 SDK/连接参数;重复调用要幂等。
  Future<void> init(ImBootstrap bootstrap);

  Future<void> login({required String userId, required String token});

  Future<void> logout();

  /// 全部会话,按最近消息时间倒序。
  Future<List<ImConversation>> fetchConversations();

  /// 单聊历史消息,按时间正序(旧 → 新);[beforeSeq] 用于往前翻页。
  Future<List<ChatMessage>> fetchHistory(String peerId, {int count = 50, int? beforeSeq});

  /// 搜索聊天记录(不支持时抛 [ImException] 42202)。
  Future<ImSearchResult> searchMessages(String keyword, {int limit = 20, String? beforeId}) =>
      throw const ImException(42202, '当前聊天服务暂不支持搜索');

  /// 发送文本。
  ///
  /// Args:
  ///   peerId: 对端 IM id。
  ///   text: 正文。
  ///   clientMsgId: 幂等 id(重发时复用同一条)。
  ///   refMsgId: 引用回复时被引用消息的 id(批次 L-2)。**只传 id**,
  ///     被引用内容由服务端回库查并生成快照 —— 客户端传内容没有入口。
  Future<ChatMessage> sendText({required String peerId, required String text,
      String? clientMsgId, int? refMsgId});

  Future<ChatMessage> sendImage({required String peerId, required String imagePath,
      int? refMsgId});

  /// 发送语音(不支持时抛 [ImException] 42202)。
  Future<ChatMessage> sendVoice({required String peerId, required String localPath,
      required int durationMs, int? refMsgId}) =>
      throw const ImException(42202, '当前聊天服务暂不支持语音');

  /// 发送贴纸(不支持时抛 [ImException] 42202)。
  ///
  /// 贴纸复用 imserver 的 `kind=2 custom`(批次 J),载荷只有
  /// `{"type":"sticker","id":<id>}`;资源本身在客户端本地,消息里不传图。
  Future<ChatMessage> sendSticker({required String peerId, required String stickerId,
          int? refMsgId}) =>
      throw const ImException(42202, '当前聊天服务暂不支持贴纸');

  /// 删除本地消息(对方不受影响);本地未发出的消息可直接忽略此调用。
  Future<void> deleteMessage(ChatMessage message);

  /// 撤回已发送消息(时限 2 分钟,超时抛 [ImException])。
  Future<void> revokeMessage(String msgId);

  /// 该 SDK 版本无原生重发:等价于用原内容重新发送(引用关系一并带回去)。
  Future<ChatMessage> resend(ChatMessage message) {
    final refMsgId = message.ref?.msgId;
    if (message.kind == ChatMessageKind.image && message.localPath != null) {
      return sendImage(peerId: message.peerId, imagePath: message.localPath!,
          refMsgId: refMsgId);
    }
    if (message.kind == ChatMessageKind.voice && message.localPath != null) {
      return sendVoice(peerId: message.peerId, localPath: message.localPath!,
          durationMs: message.voiceDurationMs, refMsgId: refMsgId);
    }
    if (message.kind == ChatMessageKind.sticker && message.stickerId != null) {
      return sendSticker(peerId: message.peerId, stickerId: message.stickerId!,
          refMsgId: refMsgId);
    }
    return sendText(peerId: message.peerId, text: message.text, refMsgId: refMsgId);
  }

  Future<void> markConversationRead(String peerId);

  /// 告诉服务端「我在跟 [peerId] 聊天,正在输入」(批次 L-1)。
  ///
  /// 只发一次**信号**,不产生消息:服务端不落库、不 ack,超限或未配对时**静默丢弃**。
  /// 因此这里**不抛异常、不返回结果** —— 调用方(聊天控制器)按 3 秒节流调用即可,
  /// 失败与否都不该影响用户正在打的字。
  Future<void> sendTyping(String peerId);

  /// 删除本机会话(拉黑后清理用;对方设备上的会话不受影响)。
  Future<void> deleteConversation(String peerId);
}
