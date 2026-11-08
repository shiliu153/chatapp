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
}

export interface ImConversation {
  peerId: string
  unreadCount: number
  showName: string
  faceUrl: string | null
  lastMessage: ChatMessage | null
  /** **对端**读到哪(0 = 从没读过)。`seq <= peerReadSeq` 的我方消息算已读。 */
  peerReadSeq: number
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
  sendText(peerId: string, text: string): Promise<ChatMessage>
  sendImage(peerId: string, file: File): Promise<ChatMessage>
  /** 发送语音(不支持时抛错) */
  sendVoice(peerId: string, blob: Blob, durationMs: number): Promise<ChatMessage>
  /** 发送贴纸(不支持时抛错):消息里只带 id,资源在客户端本地 */
  sendSticker(peerId: string, stickerId: string): Promise<ChatMessage>
  deleteMessage(msgId: string): Promise<void>
  revokeMessage(msgId: string): Promise<void>
  markConversationRead(peerId: string): Promise<void>
  deleteConversation(peerId: string): Promise<void>
}
