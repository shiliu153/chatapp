/**
 * IM 领域类型。业务层只认这里的类型,**腾讯 SDK 的类型不向外泄漏**。
 *
 * `Tim*` 系列是「结构化最小类型」:只描述我们真正调用到的字段,
 * 避免直接依赖 `@tencentcloud/chat` 的 `.d.ts`(其模块声明风格与当前 TS 配置打架)。
 */

export enum ChatMessageKind {
  text = 'text',
  matchNotice = 'matchNotice',
  banNotice = 'banNotice',
  image = 'image',
  other = 'other',
}

export interface ChatMessage {
  msgId: string
  /** 对端 IM id,如 'u9' */
  peerId: string
  isSelf: boolean
  /** 毫秒(SDK 给的是秒,映射时已 ×1000) */
  timestamp: number
  kind: ChatMessageKind
  text: string
  /** 发送者昵称(SDK 消息自带,新会话首次收到消息时靠它显示名字) */
  senderName: string
  senderAvatar: string | null
  isPending: boolean
  isFailed: boolean
  /** 缩略图 */
  imageUrl: string | null
  /** 原图 */
  imageLargeUrl: string | null
}

export interface ImConversation {
  peerId: string
  unreadCount: number
  showName: string
  faceUrl: string | null
  lastMessage: ChatMessage | null
}

export type KickReason = 'multiDevice' | 'multiAccount' | 'sigExpired' | 'restApi'

export type ImEvent =
  | { type: 'newMessage'; message: ChatMessage }
  | { type: 'conversationsChanged' }
  | { type: 'kickedOffline'; reason: KickReason }
  | { type: 'ready' }

export interface ImClient {
  onEvent(listener: (event: ImEvent) => void): void
  init(sdkAppId: number): void
  login(userId: string, userSig: string): Promise<void>
  logout(): Promise<void>
  fetchConversations(): Promise<ImConversation[]>
  fetchHistory(peerId: string, count?: number): Promise<ChatMessage[]>
  sendText(peerId: string, text: string): Promise<ChatMessage>
  sendImage(peerId: string, file: File): Promise<ChatMessage>
  deleteMessage(msgId: string): Promise<void>
  markConversationRead(peerId: string): Promise<void>
  deleteConversation(peerId: string): Promise<void>
}

/** 实测于 spike(计划三执行记录):imageInfoArray 每项的实际形状。 */
export interface TimImageInfo {
  /** 1=原图 / 2=缩略 / 3=大图 —— **权威字段** */
  sizeType?: number
  /** 0/1/2,**不可靠**(实测 type=1 那条 URL 为空),仅作兼容回退 */
  type?: number
  /** https 地址 */
  imageUrl?: string
  /** http 地址 */
  url?: string
  size?: number
  width?: number
  height?: number
}

export interface TimMessageLike {
  ID: string
  type: string
  payload?: {
    text?: string
    data?: string
    imageInfoArray?: TimImageInfo[]
  } | null
  flow?: string
  from?: string
  to?: string
  /** 秒 */
  time?: number
  status?: string
  conversationID?: string
  nick?: string
  avatar?: string
  cloudCustomData?: string
}

export interface TimConversationLike {
  conversationID: string
  type?: string
  unreadCount?: number
  userProfile?: { userID?: string; nick?: string; avatar?: string } | null
  lastMessage?: TimMessageLike | null
  remark?: string
  isPinned?: boolean
}

/** SDK 实例的最小结构化类型(便于测试注入假实现)。 */
export interface TimMessageOptions {
  to: string
  conversationType: string
  payload: Record<string, unknown>
}

export interface TimChatLike {
  login(options: { userID: string; userSig: string }): Promise<unknown>
  logout(): Promise<void>
  isReady(): boolean
  on(eventName: string, handler: (event: { data: unknown; name?: string }) => void): void
  off(eventName: string, handler: (...args: never[]) => void): void
  registerPlugin?(options: Record<string, unknown>): void
  createTextMessage(options: TimMessageOptions): TimMessageLike
  createImageMessage(options: TimMessageOptions): TimMessageLike
  sendMessage(message: TimMessageLike): Promise<unknown>
  deleteMessage(messages: TimMessageLike[]): Promise<unknown>
  getMessageList(options: {
    conversationID: string
    nextReqMessageID?: string
    count?: number
  }): Promise<{ data: { messageList: TimMessageLike[]; nextReqMessageID?: string } }>
  setMessageRead(options: { conversationID: string }): Promise<unknown>
  getConversationList(): Promise<{ data: { conversationList: TimConversationLike[] } }>
  getUserProfile?(options: {
    userIDList: string[]
  }): Promise<{ data?: { userID?: string; nick?: string; avatar?: string }[] }>
  deleteConversation(
    options: string | { conversationIDList: string[]; clearHistoryMessage?: boolean },
  ): Promise<unknown>
}

/** 事件名(默认取 SDK 常量,测试可注入假名)。 */
export interface ImEventNames {
  messageReceived: string
  conversationListUpdated: string
  kickedOut: string
  ready: string
}
