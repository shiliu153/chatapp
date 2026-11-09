/**
 * 会话行上的三段展示文案(名字 / 摘要 / 时间)。
 *
 * 抽成纯函数而不是留在模板里,是因为消息页的「最近联系人」横滑条与会话行
 * 用的是同一套口径 —— 两处各写一遍迟早会走样(改一个忘一个)。
 */
import { ChatMessageKind, type ChatMessage, type ImConversation } from '@/im/types'

/** 服务端资料还没补全时,名字先落到 peerId,不要留空行。 */
export function conversationNameOf(conversation: ImConversation): string {
  return conversation.showName || conversation.peerId
}

/** 最后一条消息的一句话摘要(图片/语音/贴纸不算正文)。 */
export function conversationSummaryOf(message: ChatMessage | null): string {
  if (!message) return '打个招呼吧'
  if (message.isFailed) return '发送失败'
  if (message.kind === ChatMessageKind.image) return '[图片]'
  if (message.kind === ChatMessageKind.voice) return '[语音]'
  if (message.kind === ChatMessageKind.sticker) return '[贴纸]'
  return message.text || '[消息]'
}

/**
 * 会话行的时刻:今天给 `HH:MM`,昨天给「昨天」,更早给 `M-D`。
 *
 * Args:
 *   conversation: 会话(只读最后一条消息的时间)。
 *   now: 「现在」,默认取系统时间;测试传固定值以免跨零点抖动。
 *
 * Returns:
 *   展示用字符串;没有最后一条消息时是空串。
 */
export function conversationTimeOf(conversation: ImConversation, now: Date = new Date()): string {
  const timestamp = conversation.lastMessage?.timestamp
  if (!timestamp) return ''
  const date = new Date(timestamp)
  if (
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  ) {
    return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
  }
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (
    date.getFullYear() === yesterday.getFullYear() &&
    date.getMonth() === yesterday.getMonth() &&
    date.getDate() === yesterday.getDate()
  ) {
    return '昨天'
  }
  return `${date.getMonth() + 1}-${date.getDate()}`
}
