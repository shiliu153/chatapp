/**
 * 多选删除(批次 T)的「这条能不能勾」判定。
 *
 * 单独抽成纯函数:菜单里的「多选」入口、气泡的勾选圈、底部操作条的条数统计
 * 必须同口径 —— 三处各写一遍,迟早出现「菜单能进、气泡却勾不上」。
 */
import { ChatMessageKind, type ChatMessage } from '@/im/types'

/**
 * 这条消息能不能进多选。
 *
 * - **发送中**(`isPending`):还没落库,服务端没有这一行,删了也没意义;
 * - **已撤回**:内容已经没了,留着那行灰字也不碍事(撤回本身就是对双方生效的删除);
 * - **系统灰条**(配对/封禁通知):不是气泡、没有勾选位,也不属于用户内容。
 *
 * 发送失败(`isFailed`)的**可以**勾:它是本地占位,删除只在本地摘掉,不上行
 * (见 `stores/chat.ts::deleteMessages`)。
 *
 * Args:
 *   message: 会话里的一条消息。
 *
 * Returns:
 *   true 表示可以勾选删除。
 */
export function canSelectMessage(message: ChatMessage): boolean {
  if (message.isPending) return false
  if (message.isRevoked) return false
  if (
    message.kind === ChatMessageKind.matchNotice ||
    message.kind === ChatMessageKind.banNotice
  ) {
    return false
  }
  return true
}
