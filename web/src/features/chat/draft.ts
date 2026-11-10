/**
 * 会话草稿(批次 T):按对端存 `localStorage`,键固定 `chat_draft:{peerId}`。
 *
 * 为什么走 localStorage 而不是 Pinia:草稿要求**跨刷新、跨标签页**还在(打了一半
 * 关掉浏览器,回来还得在),Pinia 里的状态一刷新就没了。为什么还要一份内存镜像:
 * `localStorage` 不是响应式的,会话列表的「[草稿] 」前缀必须有个可被 Vue 追踪的
 * 信号才会重渲染 —— 所以写入同时更新镜像,读取则「镜像优先、未命中再懒读存储」。
 *
 * 空(或纯空白)文本一律等于**没有草稿**:不清 key 的话,会话列表会挂着一行
 * 「[草稿] 」却点进去什么都没有。
 */
import { ref } from 'vue'

const PREFIX = 'chat_draft:'

/**
 * 内存镜像:`localStorage` 的响应式替身。
 *
 * 只放**本会话写过**的键(读不写回)—— 读时写回会让组件的 computed 在求值过程中
 * 改状态,触发递归重算。
 */
const mirror = ref<Record<string, string>>({})

/** 存储键名(`chat_draft:{peerId}`);单列出来是为了测试与清理能引同一处。 */
export function draftKey(peerId: string): string {
  return `${PREFIX}${peerId}`
}

/** 读 `localStorage`;隐私模式 / 配额满 / 被禁用时一律当「没有草稿」,不能把聊天页搞崩。 */
function readStored(peerId: string): string {
  try {
    return localStorage.getItem(draftKey(peerId)) ?? ''
  } catch {
    return ''
  }
}

/**
 * 读一条草稿(没有时是空串)。
 *
 * 镜像里有(哪怕是空串)就用镜像 —— 空串代表「本次会话里刚清过」,
 * 此时不该再去存储里捞旧值。
 */
export function readDraft(peerId: string): string {
  const local = mirror.value[peerId]
  if (local !== undefined) return local
  return peerId ? readStored(peerId) : ''
}

/** 这个会话有没有草稿(会话列表据此加「[草稿] 」前缀)。 */
export function hasDraft(peerId: string): boolean {
  return readDraft(peerId).trim() !== ''
}

/**
 * 写一条草稿;内容为空(或纯空白)等价于**删掉**。
 *
 * Args:
 *   peerId: 会话对端的 IM id,如 `u9`。
 *   text: 输入框当前的原文(不清洗、不 trim —— 用户打的前导空格也是他的内容)。
 */
export function saveDraft(peerId: string, text: string): void {
  if (!peerId) return
  if (!text.trim()) {
    clearDraft(peerId)
    return
  }
  try {
    localStorage.setItem(draftKey(peerId), text)
  } catch {
    // 隐私模式 / 配额满:草稿存不下就不存,绝不让它影响发消息
  }
  mirror.value = { ...mirror.value, [peerId]: text }
}

/** 删掉一条草稿(发送成功 / 输入框清空 / 会话被删除时调)。 */
export function clearDraft(peerId: string): void {
  if (!peerId) return
  try {
    localStorage.removeItem(draftKey(peerId))
  } catch {
    // 同 saveDraft:清不掉也没有正确性后果
  }
  if (!(peerId in mirror.value)) return
  const rest = { ...mirror.value }
  delete rest[peerId]
  mirror.value = rest
}

/**
 * 清空整个草稿镜像(测试隔离用;也用于「退出登录」这类整体重置)。
 *
 * 生产路径不必担心 `localStorage` 里残留:退出登录后重新登录,读到的是同一个人的
 * 草稿,本来就是想要的语义(草稿跟着浏览器,不跟会话列表)。
 */
export function resetDrafts(): void {
  mirror.value = {}
}
