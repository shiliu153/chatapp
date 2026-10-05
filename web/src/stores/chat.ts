import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { http } from '@/api/http'
import { parseApiError } from '@/api/error'
import { sessionEvents } from '@/api/session-events'
import { getImClient } from '@/im/client'
import { SYSTEM_NOTICE_PEER_ID } from '@/im/map'
import type { ChatMessage, ImConversation } from '@/im/types'

export type ChatStatus = 'idle' | 'connecting' | 'ready' | 'reconnecting' | 'error'

/** 按时间排序 + 去重(同 msgId 以新的为准,保证本地乐观消息被服务端版本替换)。 */
function mergeMessages(oldList: ChatMessage[], incoming: ChatMessage[]): ChatMessage[] {
  const byId = new Map<string, ChatMessage>()
  for (const message of [...oldList, ...incoming]) byId.set(message.msgId, message)
  return [...byId.values()].sort((a, b) => a.timestamp - b.timestamp)
}

export const useChatStore = defineStore('chat', () => {
  // 客户端只取一次:整个应用共用一个 IM 实例
  const client = getImClient()

  const conversations = ref<ImConversation[]>([])
  const messages = ref<Record<string, ChatMessage[]>>({})
  const status = ref<ChatStatus>('idle')
  const error = ref('')
  /** 发送失败/待发送的图片文件,供「重发」用 */
  const pendingFiles = new Map<string, File>()

  const unreadTotal = computed(() =>
    conversations.value.reduce((sum, item) => sum + item.unreadCount, 0),
  )

  function sortConversations(): void {
    conversations.value = [...conversations.value].sort((a, b) => {
      // 系统通知永远置顶(spec §8)
      if (a.peerId === SYSTEM_NOTICE_PEER_ID) return -1
      if (b.peerId === SYSTEM_NOTICE_PEER_ID) return 1
      return (b.lastMessage?.timestamp ?? 0) - (a.lastMessage?.timestamp ?? 0)
    })
  }

  function upsertConversation(message: ChatMessage): void {
    const existing = conversations.value.find((item) => item.peerId === message.peerId)
    if (existing) {
      existing.lastMessage = message
      if (!message.isSelf) existing.unreadCount += 1
    } else {
      conversations.value = [
        ...conversations.value,
        {
          peerId: message.peerId,
          unreadCount: message.isSelf ? 0 : 1,
          showName: message.peerId === SYSTEM_NOTICE_PEER_ID ? '系统通知' : message.peerId,
          faceUrl: null,
          lastMessage: message,
        },
      ]
    }
    sortConversations()
  }

  function appendMessage(peerId: string, message: ChatMessage): void {
    const list = messages.value[peerId] ?? []
    messages.value = { ...messages.value, [peerId]: mergeMessages(list, [message]) }
  }

  function messagesOf(peerId: string): ChatMessage[] {
    return messages.value[peerId] ?? []
  }

  function setLocalUnread(peerId: string, count: number): void {
    const target = conversations.value.find((item) => item.peerId === peerId)
    if (target) target.unreadCount = count
  }

  client.onEvent((event) => {
    if (event.type === 'newMessage') {
      appendMessage(event.message.peerId, event.message)
      upsertConversation(event.message)
      return
    }
    if (event.type === 'conversationsChanged') {
      void loadConversations().catch(() => {})
      return
    }
    if (event.type === 'ready') {
      status.value = 'ready'
      return
    }
    if (event.type === 'kickedOffline') {
      // ⚠️ 分流:同端第二个标签页被顶时**绝不能清凭证** —— localStorage 是共享的,
      //    清掉会把所有标签页一起登出(spec §5.3)。
      if (event.reason === 'multiAccount') {
        status.value = 'reconnecting'
        void reconnect()
        return
      }
      sessionEvents.emitKickedOffline()
    }
  })

  /** 取 userSig → 登录 IM。403(重封禁)不重试,交给路由守卫处理。 */
  async function doConnect(): Promise<void> {
    error.value = ''
    try {
      const { data } = await http.post('/im/user_sig')
      const payload = data as { user_sig: string; sdkappid: string | number; im_user_id: string }
      client.init(Number(payload.sdkappid))
      await client.login(payload.im_user_id, payload.user_sig)
      status.value = 'ready'
    } catch (e) {
      error.value = parseApiError(e).message
      status.value = 'error'
    }
  }

  async function connect(): Promise<void> {
    if (status.value === 'connecting' || status.value === 'ready') return
    status.value = 'connecting'
    await doConnect()
  }

  /** 同端多实例被顶后的重连(状态值不同,UI 上显示「重连中」而不是「连接中」)。 */
  async function reconnect(): Promise<void> {
    status.value = 'reconnecting'
    await doConnect()
  }

  async function loadConversations(): Promise<void> {
    conversations.value = await client.fetchConversations()
    sortConversations()
  }

  async function loadHistory(peerId: string): Promise<ChatMessage[]> {
    const history = await client.fetchHistory(peerId)
    const merged = mergeMessages(messagesOf(peerId), history)
    messages.value = { ...messages.value, [peerId]: merged }
    return merged
  }

  async function openConversation(peerId: string): Promise<ChatMessage[]> {
    const list = await loadHistory(peerId)
    await client.markConversationRead(peerId)
    setLocalUnread(peerId, 0)
    return list
  }

  async function sendText(peerId: string, text: string): Promise<ChatMessage> {
    const message = await client.sendText(peerId, text)
    appendMessage(peerId, message)
    upsertConversation({ ...message, isSelf: true })
    return message
  }

  async function sendImage(peerId: string, file: File): Promise<ChatMessage> {
    const message = await client.sendImage(peerId, file)
    pendingFiles.set(message.msgId, file)
    appendMessage(peerId, message)
    upsertConversation({ ...message, isSelf: true })
    return message
  }

  /** 重发失败的消息:文本直接重发,图片用缓存的 File 重发。 */
  async function resend(message: ChatMessage): Promise<void> {
    const list = messagesOf(message.peerId).filter((item) => item.msgId !== message.msgId)
    messages.value = { ...messages.value, [message.peerId]: list }
    if (message.kind === 'image') {
      const file = pendingFiles.get(message.msgId)
      if (!file) return
      pendingFiles.delete(message.msgId)
      await sendImage(message.peerId, file)
      return
    }
    await sendText(message.peerId, message.text)
  }

  async function deleteMessage(message: ChatMessage): Promise<void> {
    messages.value = {
      ...messages.value,
      [message.peerId]: messagesOf(message.peerId).filter((item) => item.msgId !== message.msgId),
    }
    pendingFiles.delete(message.msgId)
    await client.deleteMessage(message.msgId)
  }

  async function deleteConversation(peerId: string): Promise<void> {
    await client.deleteConversation(peerId)
    conversations.value = conversations.value.filter((item) => item.peerId !== peerId)
    const rest = { ...messages.value }
    delete rest[peerId]
    messages.value = rest
  }

  async function close(): Promise<void> {
    await client.logout().catch(() => {})
    conversations.value = []
    messages.value = {}
    status.value = 'idle'
  }

  return {
    conversations,
    messages,
    status,
    error,
    unreadTotal,
    connect,
    reconnect,
    loadConversations,
    loadHistory,
    openConversation,
    sendText,
    sendImage,
    resend,
    deleteMessage,
    deleteConversation,
    messagesOf,
    close,
  }
})
