/**
 * 腾讯云 IM(浏览器端 SDK)对象 → 领域模型。
 *
 * ⚠️ 与 App 的关键差异:Flutter 插件把内容平铺成 message.textElem / imageElem / customElem,
 * 而 Web SDK 统一放在 message.payload 里 —— 所以 App 的 chatMessageFromSdk **不能**复用。
 *
 * 字段位置以 2026-10-05 的 spike 实测为准(见计划三「执行记录」Task 6.1 清单)。
 */
import {
  ChatMessageKind,
  type ChatMessage,
  type ImConversation,
  type TimConversationLike,
  type TimImageInfo,
  type TimMessageLike,
} from './types'

export const SYSTEM_NOTICE_PEER_ID = 'system_notice'

/**
 * 配对灰条的兜底文案。
 * 后端发的自定义消息里只有 `{type:'match_notice'}`,**没有 text** ——
 * App 同样用固定文案兜底(见 app/lib/features/chat/widgets/message_bubble.dart 的 noticeFallback)。
 */
export const MATCH_NOTICE_FALLBACK = '你们已互相喜欢,开始聊天吧'

/** 除 match_notice 之外的系统灰条类型(与后端 im/client.py 的 type 取值一一对应)。 */
const NOTICE_TYPES = ['ban_notice', 'ban_lifted', 'report_handled', 'post_commented']

function decodeCustomData(payload: unknown): Record<string, unknown> | null {
  const data = (payload as { data?: unknown } | null)?.data
  if (typeof data !== 'string' || data.length === 0) return null
  try {
    const decoded: unknown = JSON.parse(data)
    return decoded && typeof decoded === 'object' ? (decoded as Record<string, unknown>) : null
  } catch {
    return null
  }
}

function customTypeOf(payload: unknown): string | null {
  const type = decodeCustomData(payload)?.type
  return typeof type === 'string' ? type : null
}

function customTextOf(payload: unknown): string {
  const text = decodeCustomData(payload)?.text
  return typeof text === 'string' ? text : ''
}

/**
 * 取图片 URL。**权威字段是 `sizeType`(1=原图 / 2=缩略 / 3=大图)** ——
 * spike 实测:收到方向的 `type` 是 0/1/2 且不可靠(type=1 那条 URL 反而是空的),
 * 而 `sizeType` 稳定;URL 有两个字段(`imageUrl` 是 https、`url` 是 http),空的要跳过。
 * `type` 只作为兼容回退(给不带 sizeType 的旧数据/单测夹具用)。
 */
function pickImageUrl(payload: unknown, wanted: 1 | 2 | 3): string | null {
  const list = (payload as { imageInfoArray?: TimImageInfo[] } | null)?.imageInfoArray ?? []
  const urlOf = (item: TimImageInfo): string =>
    (typeof item.imageUrl === 'string' && item.imageUrl) ||
    (typeof item.url === 'string' && item.url) ||
    ''
  const rankOf = (item: TimImageInfo): number =>
    typeof item.sizeType === 'number'
      ? item.sizeType
      : typeof item.type === 'number'
        ? item.type
        : -1

  const hit =
    list.find((item) => rankOf(item) === wanted && urlOf(item)) ??
    list.find((item) => item.type === wanted && urlOf(item))
  return hit ? urlOf(hit) : null
}

function kindOf(message: TimMessageLike): ChatMessageKind {
  if (message.type === 'TIMTextElem') return ChatMessageKind.text
  if (message.type === 'TIMImageElem') return ChatMessageKind.image
  if (message.type === 'TIMCustomElem') {
    const type = customTypeOf(message.payload)
    if (type === 'match_notice') return ChatMessageKind.matchNotice
    if (type && NOTICE_TYPES.includes(type)) return ChatMessageKind.banNotice
  }
  return ChatMessageKind.other
}

function textOf(message: TimMessageLike, kind: ChatMessageKind): string {
  if (kind === ChatMessageKind.text) {
    const text = (message.payload as { text?: unknown } | null)?.text
    return typeof text === 'string' ? text : ''
  }
  if (kind === ChatMessageKind.matchNotice) {
    // 后端只发 {type:'match_notice'},正文靠本地兜底(与 App 一致)
    return customTextOf(message.payload) || MATCH_NOTICE_FALLBACK
  }
  if (kind === ChatMessageKind.banNotice) {
    return customTextOf(message.payload)
  }
  return ''
}

export function chatMessageFromTim(message: TimMessageLike): ChatMessage {
  const isSelf = message.flow === 'out'
  const peerId = (isSelf ? message.to : message.from) ?? ''
  const kind = kindOf(message)
  const isImage = kind === ChatMessageKind.image

  return {
    msgId: message.ID,
    peerId,
    isSelf,
    timestamp: (message.time ?? 0) * 1000, // SDK 给的是秒
    kind,
    text: textOf(message, kind),
    senderName: message.nick ?? '',
    senderAvatar: message.avatar ?? null,
    isPending: message.status === 'unSend' || message.status === 'sending',
    isFailed: message.status === 'fail',
    // 列表用小图、点开用大图;缺哪张就退回另一张,避免空图
    imageUrl: isImage ? (pickImageUrl(message.payload, 2) ?? pickImageUrl(message.payload, 1)) : null,
    imageLargeUrl: isImage
      ? (pickImageUrl(message.payload, 1) ?? pickImageUrl(message.payload, 3))
      : null,
    isRevoked: false,
  }
}

export function conversationFromTim(conversation: TimConversationLike): ImConversation | null {
  // 只处理单聊:C2C${userID}(system_notice 也是单聊账号)
  if (!conversation.conversationID.startsWith('C2C')) return null
  const peerId = conversation.conversationID.slice(3)
  if (!peerId) return null
  return {
    peerId,
    unreadCount: conversation.unreadCount ?? 0,
    // 对端昵称优先取 userProfile;新建会话的 userProfile 可能还没填,
    // 此时退回 lastMessage.nick —— 实测 C2C 会话里它就是对方的昵称。
    // 两边都没有时返回空串:**由 store 决定兜底**(合并时才能保住本地已知的名字)。
    showName:
      conversation.userProfile?.nick ||
      conversation.lastMessage?.nick ||
      (peerId === SYSTEM_NOTICE_PEER_ID ? '系统通知' : ''),
    faceUrl: conversation.userProfile?.avatar || conversation.lastMessage?.avatar || null,
    lastMessage: conversation.lastMessage ? chatMessageFromTim(conversation.lastMessage) : null,
  }
}
