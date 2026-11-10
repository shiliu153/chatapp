/**
 * IM 领域类型。业务层只认这里的类型,传输实现(自建 imserver 的 WS/HTTP 帧)
 * 不外泄成公共 API。
 *
 * 腾讯云 IM 分支已于 2026-11-08 删除(backlog D-4):`Tim*` 系列结构类型、
 * 事件名映射与 `backend/sdkAppId` 字段一并移除。
 */

export enum ChatMessageKind {
  text = 'text',
  matchNotice = 'matchNotice',
  banNotice = 'banNotice',
  image = 'image',
  voice = 'voice',
  /** 贴纸(批次 J):消息里只有 id,图片资源在客户端本地 `public/stickers/` */
  sticker = 'sticker',
  other = 'other',
}

/** 「系统通知」固定 IM 账号(与后端 `im/client.py::SYSTEM_NOTICE_IDENTIFIER` 是跨栈契约)。 */
export const SYSTEM_NOTICE_PEER_ID = 'system_notice'

/**
 * 引用快照(批次 L-2):被引用消息的**服务端摘要**。
 *
 * 为什么客户端不自己拼:让客户端传快照等于允许任何人伪造「对方说过 X」。
 * 上行只发 `ref_msg_id`,这里的内容全部由服务端回库查后生成。
 */
export interface QuoteRef {
  /** 被引用消息的 id(数字;下行 `ref.msg_id`) */
  msgId: number
  /** 被引用消息的发送者 IM id(如 `u9`),用来判断引用块该署谁的名 */
  from: string
  /** `text` / `image` / `voice` / `custom`(贴纸) */
  kind: string
  /** 摘要:文本前 120 字,图片/语音/贴纸是 `[图片]` / `[语音]` / `[贴纸]`;已撤回时为空串 */
  text: string
  /** 被引用消息已撤回:引用块只显示「消息已撤回」,不显示原文 */
  revoked: boolean
}

/** 我在输入框里选中的引用目标(批次 L-2):只活在当前会话,发送后即清空。 */
export interface QuoteTarget {
  /** 被引用消息 id(上行 `ref_msg_id`) */
  msgId: number
  /** 被引用消息的发送者 IM id(引用条上署名用) */
  from: string
  /** 本地摘要(引用条上展示);**上行不发送它**,服务端会自己生成快照 */
  text: string
}

export interface ChatMessage {
  msgId: string
  /** 对端 IM id,如 'u9' */
  peerId: string
  isSelf: boolean
  /** 会话内序号,回溯翻页用 */
  seq: number
  /** 毫秒 */
  timestamp: number
  kind: ChatMessageKind
  text: string
  /** 发送者昵称(消息自带,新会话首次收到消息时靠它显示名字) */
  senderName: string
  senderAvatar: string | null
  isPending: boolean
  isFailed: boolean
  /** 缩略图 */
  imageUrl: string | null
  /** 原图 */
  imageLargeUrl: string | null
  /** 语音地址(播放用) */
  voiceUrl?: string | null
  /** 语音时长(毫秒),气泡宽度与秒数展示用 */
  voiceDurationMs?: number
  /** 贴纸 id(如 `sticker_01`),只有 kind=sticker 有值 */
  stickerId?: string | null
  /** 已撤回:渲染成居中灰字,不再显示内容 */
  isRevoked: boolean
  /**
   * 引用快照(批次 L-2):这条消息引用的是哪条、摘要是什么。
   *
   * 没有引用时**服务端根本不下发 `ref` 键**,所以这里是可选的。
   */
  ref?: QuoteRef | null
}

export interface ImConversation {
  peerId: string
  unreadCount: number
  showName: string
  faceUrl: string | null
  lastMessage: ChatMessage | null
  /** **对端**读到哪(0 = 从没读过)。`seq <= peerReadSeq` 的我方消息算已读。 */
  peerReadSeq: number
  /**
   * 置顶(批次 N,服务端 `im_conversation_state.pinned_at > 0` 的布尔投影)。
   *
   * 服务端**已经按「置顶组在前、组内按置顶时间倒序」排好**,客户端照顺序渲染即可 ——
   * 自己再排一次只会和服务端顺序打架(而且 `pinned_at` 根本不下发,排不出来)。
   */
  pinned: boolean
  /**
   * 免打扰(批次 N)。**语义只在客户端**:会话行显示静音图标,未读只显示灰点
   * 不显示数字 —— 服务端不改 `unread` 统计,本项目也没有可抑制的离线推送通道。
   */
  muted: boolean
}

/** 会话偏好的写入参数(批次 N):**没传的那一项 = 不改**,与传 `false` 不同。 */
export interface ImConversationFlags {
  pinned?: boolean
  muted?: boolean
}

/** 会话偏好的回读结果(服务端回的是实库真值,不是请求参数的回显)。 */
export interface ImConversationFlagsResult {
  pinned: boolean
  muted: boolean
}

export type KickReason = 'multiDevice' | 'multiAccount' | 'sigExpired' | 'restApi'

export interface ImBootstrap {
  token: string
  wsUrl: string
  httpUrl: string
  imUserId: string
}

export interface ImCapabilities {
  image: boolean
  /** 是否支持聊天记录搜索(不支持时入口隐藏) */
  search: boolean
  /** 是否支持语音消息(不支持时入口隐藏) */
  voice: boolean
  /**
   * 是否支持已读回执。
   * 没有「对方读到哪」就不会有真已读,宁可不显示,也不要显示一个永远「未读」的假状态。
   */
  readReceipt: boolean
}

/** 一条搜索命中(只可能是文本消息)。 */
export interface ImSearchHit {
  msgId: string
  seq: number
  peerId: string
  peerName: string
  peerAvatar: string | null
  text: string
  timestamp: number
}

/** 一页搜索结果。 */
export interface ImSearchResult {
  items: ImSearchHit[]
  hasMore: boolean
}

export type ImEvent =
  | { type: 'newMessage'; message: ChatMessage }
  | { type: 'conversationsChanged' }
  | { type: 'messageRevoked'; msgId: string }
  /** 对端读到了 `seq`(已读回执)。**只增不减**:收到更小的值直接忽略。 */
  | { type: 'peerRead'; peerId: string; seq: number }
  /**
   * **我**在另一台设备上把与 `peerId` 的会话读到了 `seq`(多端在线 K-3)。
   *
   * 与 `peerRead` 的视角正好相反:`peerRead` 是「**对端**读我」(用来把我方气泡标已读),
   * 这个是「**我自己**在别处读了」—— 只清自己这边的未读,**绝不能**推进 `peerReadSeq`,
   * 否则就是假已读。
   */
  | { type: 'selfRead'; peerId: string; seq: number }
  /** **我**在另一台设备上删除了与 `peerId` 的会话(K-3)。只发给本人的其他端,对方收不到。 */
  | { type: 'conversationDeleted'; peerId: string }
  /**
   * 对端 `peerId` 正在输入(批次 L-1)。
   *
   * **可丢信号**:服务端不落库、不补拉、超限静默丢弃,收不到是常态。
   * 只当作「最近 5 秒对方在打字」的瞬时提示,别拿它推断任何持久状态。
   */
  | { type: 'typing'; peerId: string }
  | { type: 'kickedOffline'; reason: KickReason }
  /**
   * 连接断了(服务端 75s 空闲踢出、网络中断等),**不是**被顶号。
   * 与 `kickedOffline` 必须分开:被顶号绝不能自动重连(同端多标签会互相踢成风暴),
   * 断线则必须自动退避重连并补拉(否则静默丢消息)。
   */
  | { type: 'disconnected'; code?: number; reason?: string }
  | { type: 'ready' }

export interface ImClient {
  onEvent(listener: (event: ImEvent) => void): void
  capabilities: ImCapabilities
  init(bootstrap: ImBootstrap): void | Promise<void>
  login(userId: string, token: string): Promise<void>
  logout(): Promise<void>
  fetchConversations(): Promise<ImConversation[]>
  fetchHistory(peerId: string, count?: number, beforeSeq?: number): Promise<ChatMessage[]>
  /** 搜索聊天记录(不支持时抛错) */
  searchMessages(keyword: string, limit?: number, beforeId?: string): Promise<ImSearchResult>
  /**
   * 发送文本。
   *
   * `refMsgId` 是引用回复时被引用消息的 id(批次 L-2)。**只传 id**:
   * 被引用内容由服务端回库查并生成快照,客户端没有传内容的入口。
   */
  sendText(peerId: string, text: string, refMsgId?: number): Promise<ChatMessage>
  sendImage(peerId: string, file: File, refMsgId?: number): Promise<ChatMessage>
  /** 发送语音(不支持时抛错) */
  sendVoice(peerId: string, blob: Blob, durationMs: number, refMsgId?: number):
    Promise<ChatMessage>
  /** 发送贴纸(不支持时抛错):消息里只带 id,资源在客户端本地 */
  sendSticker(peerId: string, stickerId: string, refMsgId?: number): Promise<ChatMessage>
  /** 删一条聊天记录。菜单里的「删除」用它;实现按批量接口走,别各写一份。 */
  deleteMessage(msgId: string): Promise<void>
  /**
   * 批量删除聊天记录(批次 T):**单方删除** —— 只删我这一侧的副本。
   *
   * 消息本体不动、不通知对端、对端历史里还在、不可恢复。它和「撤回」不是一回事:
   * 撤回是 2 分钟内对**双方**生效,删除只删自己这边。
   *
   * 走 imserver 的 HTTP `POST /im/api/messages/delete`(**不是 WS 帧**:低频写操作,
   * 加一个帧要三端 fixture 同改,见 `docs/ops/imserver.md` §21)。
   * 服务端上限 **50 条/次**(超过 → `400` + `42201`),拆批是调用方的事。
   *
   * Args:
   *   ids: 消息 id 列表(服务端接受字符串或整数,这里统一传字符串)。
   *
   * Returns:
   *   本次**新**隐藏的条数(幂等:同一批删第二次返回 0)。
   */
  deleteMessages(ids: string[]): Promise<number>
  revokeMessage(msgId: string): Promise<void>
  markConversationRead(peerId: string): Promise<void>
  /**
   * 告诉服务端「我在跟 `peerId` 聊天,正在输入」(批次 L-1)。
   *
   * 只发一次信号,不产生消息:服务端不落库、不 ack,超限或未配对时静默丢弃。
   * 因此这里不抛错 —— 调用方(聊天 store)按 3 秒节流调用即可。
   */
  sendTyping(peerId: string): Promise<void>
  deleteConversation(peerId: string): Promise<void>
  /**
   * 改会话的两个个人偏好(批次 N):置顶 / 免打扰。
   *
   * 走 imserver 的 HTTP `POST /im/api/conversations/flags`(**不是 WS 帧**:低频写操作,
   * 加帧要三端 fixture 同改)。只传要改的那一项 —— 缺省 = 这一项不改。
   * 返回服务端**回读实库**后的真值,调用方照它刷新本地状态,不要自己猜。
   *
   * 失败时抛 `ApiError`(`code` 是 imserver 的业务码):`40401` = 会话不存在,
   * `42901` = 操作过于频繁。
   */
  setConversationFlags(
    peerId: string,
    flags: ImConversationFlags,
  ): Promise<ImConversationFlagsResult>
}
