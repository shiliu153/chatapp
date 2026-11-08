/**
 * 引用规则(批次 L-2):哪些消息能引用、引用条与引用块上显示什么。
 *
 * 客户端先判一次只是为了「不该出现的入口就不出现」;**真正的边界在服务端**:
 * `ref_msg_id` 必须属于同一会话、不能是系统灰条,引用内容一律由服务端回库查后生成快照。
 */
import { ChatMessageKind } from '@/im/types'
import type { ChatMessage } from '@/im/types'

/**
 * 这条消息能不能被引用。
 *
 * 排除项与 App 端一致:系统灰条(match_notice / ban_notice)没有内容可引用;
 * 已撤回的没有内容(服务端也会拒);发送中 / 失败的还没有服务端 id。
 *
 * @param message 待判断的消息
 * @returns 文本 / 图片 / 语音 / 贴纸,且未撤回、已落库的消息为 true
 */
export function canQuote(message: ChatMessage): boolean {
  if (message.isRevoked || message.isPending || message.isFailed) return false
  if (
    message.kind !== ChatMessageKind.text &&
    message.kind !== ChatMessageKind.image &&
    message.kind !== ChatMessageKind.voice &&
    message.kind !== ChatMessageKind.sticker
  ) {
    return false
  }
  // 本地乐观消息的 id 是 `local-…`,服务端不认识;必须等拿到真实 id 才能引用
  return /^\d+$/.test(message.msgId)
}

/**
 * 引用条 / 引用块上给这条消息用的摘要文案。
 *
 * 只用于**本地**展示(引用条,以及刚发出的乐观气泡);对端看到的内容来自服务端快照,
 * 两边口径保持一致(见 imserver 的 `build_ref_snapshot`)。
 *
 * @param message 被引用的消息
 * @returns 文本取正文;图片 / 语音 / 贴纸分别是 `[图片]` / `[语音]` / `[贴纸]`
 */
export function quoteSummaryOf(message: ChatMessage): string {
  switch (message.kind) {
    case ChatMessageKind.image:
      return '[图片]'
    case ChatMessageKind.voice:
      return '[语音]'
    case ChatMessageKind.sticker:
      return '[贴纸]'
    case ChatMessageKind.text:
      return message.text
    default:
      return '[消息]'
  }
}
