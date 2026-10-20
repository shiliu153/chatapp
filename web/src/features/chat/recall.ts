import { ChatMessageKind } from '@/im/types'
import type { ChatMessage } from '@/im/types'

/** 撤回窗口:与腾讯控制台默认的 2 分钟一致。 */
export const RECALL_WINDOW_MS = 2 * 60 * 1000

/**
 * 这条消息当前能否撤回。
 *
 * @param message 待判断的消息
 * @param now 参照时间戳(毫秒,测试注入)
 */
export function canRecall(message: ChatMessage, now: number = Date.now()): boolean {
  if (!message.isSelf || message.isRevoked) return false
  if (message.isPending || message.isFailed) return false
  if (message.kind !== ChatMessageKind.text && message.kind !== ChatMessageKind.image) return false
  const age = now - message.timestamp
  return age >= 0 && age <= RECALL_WINDOW_MS
}
