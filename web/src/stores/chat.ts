import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { http } from '@/api/http'
import { parseApiError } from '@/api/error'
import { sessionEvents } from '@/api/session-events'
import { getImClient } from '@/im/client'
import { SYSTEM_NOTICE_PEER_ID } from '@/im/map'
import type {
  ChatMessage,
  ImBootstrap,
  ImCapabilities,
  ImConversation,
  ImSearchResult,
} from '@/im/types'

export type ChatStatus = 'idle' | 'connecting' | 'ready' | 'reconnecting' | 'inactive' | 'error'

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
  /**
   * 当前 IM 客户端能力(图片/搜索入口按它显示)。
   *
   * 必须是响应式状态:`client.capabilities` 只是普通 getter,`getImClient()`
   * 在 init 之前拿到的是「未连接」的兜底值,直接读它会把入口永久藏起来
   * (2026-10-26 排查发现:Web 聊天页图片入口因此一直不显示)。
   */
  const capabilities = ref<ImCapabilities>({ image: false, search: false, voice: false })
  /** 发送失败/待发送的图片文件,供「重发」用 */
  const pendingFiles = new Map<string, File>()
  /** 发送失败/待发送的语音,供「重发」用 */
  const pendingVoices = new Map<string, { blob: Blob; durationMs: number }>()
  /** 进行中的连接(并发调用复用它) */
  let inFlight: Promise<void> | null = null

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
          // 新会话首次收到消息时,名字/头像就用消息自带的(SDK 已带上发送者资料)
          showName:
            message.peerId === SYSTEM_NOTICE_PEER_ID
              ? '系统通知'
              : message.senderName || message.peerId,
          faceUrl: message.senderAvatar,
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
    if (event.type === 'messageRevoked') {
      markRevoked(event.msgId)
      return
    }
    if (event.type === 'ready') {
      status.value = 'ready'
      return
    }
    if (event.type === 'kickedOffline') {
      // ⚠️ 分流一:被同端的另一个标签页顶掉。
      //    绝不能清凭证(localStorage 共享,清掉会把所有标签页一起登出,
      //    违反 spec §5.3 / T9.4 的验收);也**不能自动重连** ——
      //    两个标签页会自动互相踢,实测 10 秒内打了 27 次 user_sig 并被 IM 限流。
      //    正确做法:置为 inactive,等用户显式接管(reconnect)。
      if (event.reason === 'multiAccount') {
        status.value = 'inactive'
        return
      }
      // 分流二:真的被别的设备顶掉 → 全屏提示 + 清凭证
      sessionEvents.emitKickedOffline()
    }
  })

  /** 取 userSig → 登录 IM。403(重封禁)不重试,交给路由守卫处理。 */
  async function doConnect(): Promise<void> {
    error.value = ''
    try {
      const { data } = await http.post('/im/user_sig')
      const raw = data as {
        backend?: 'tencent' | 'self'
        sdkappid?: string | number
        im_user_id: string
        token?: string
        user_sig?: string
      }
      // Web 永远走同源:忽略后端返回的绝对地址(可能是 App 用的 10.0.2.2)
      const wsUrl = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/im/ws`
      const httpUrl = new URL('/im/api', location.origin).toString()
      const bootstrap: ImBootstrap = {
        backend: raw.backend === 'self' ? 'self' : 'tencent',
        sdkAppId: Number(raw.sdkappid ?? 0),
        token: raw.token ?? '',
        wsUrl,
        httpUrl,
        imUserId: raw.im_user_id,
      }
      await client.init(bootstrap)
      await client.login(raw.im_user_id, raw.token || raw.user_sig || '')
      // 连上之后才拿得到真实能力位(init 前 RoutingImClient 还没有 active)
      capabilities.value = { ...client.capabilities }
      status.value = 'ready'
    } catch (e) {
      error.value = parseApiError(e).message
      status.value = 'error'
    }
  }

  async function connect(): Promise<void> {
    if (status.value === 'ready') return
    // 已在连/重连中:复用同一个 Promise,避免并发建两个实例
    if (inFlight) return inFlight
    status.value = status.value === 'reconnecting' ? 'reconnecting' : 'connecting'
    inFlight = doConnect().finally(() => {
      inFlight = null
    })
    return inFlight
  }

  /**
   * 所有 IM 操作前都要先确保已连接 —— 否则会在 `init()` 之前就用 SDKAppID=0
   * 建出实例,之后所有调用都返回 `No SDKAppID`(真机踩到过)。
   */
  async function ensureConnected(): Promise<void> {
    await connect()
  }

  /** 被同端顶掉后由用户显式接管(见 multiAccount 分流注释)。 */
  async function reconnect(): Promise<void> {
    status.value = 'reconnecting'
    await doConnect()
  }

  async function loadConversations(): Promise<void> {
    await ensureConnected()
    const fresh = await client.fetchConversations()
    // ⚠️ 服务端对新会话返回的摘要可能是**残缺**的(实测:lastMessage 只有 payload.text,
    //    from/time/nick 全空;userProfile 也空)。整体替换会把本地已经知道的名字、
    //    头像与完整摘要冲掉,所以按 peerId 合并、只认服务端更完整的字段。
    const previous = new Map(conversations.value.map((item) => [item.peerId, item]))
    conversations.value = fresh.map((item) => {
      const old = previous.get(item.peerId)
      if (!old) return item
      const serverMessage = item.lastMessage
      const serverSummaryComplete = Boolean(serverMessage && serverMessage.timestamp > 0)
      return {
        ...item,
        showName: item.showName || old.showName,
        faceUrl: item.faceUrl ?? old.faceUrl,
        lastMessage: serverSummaryComplete ? serverMessage : old.lastMessage,
        unreadCount: item.unreadCount,
      }
    })
    sortConversations()
  }

  async function loadHistory(peerId: string): Promise<ChatMessage[]> {
    await ensureConnected()
    const history = await client.fetchHistory(peerId)
    const merged = mergeMessages(messagesOf(peerId), history)
    messages.value = { ...messages.value, [peerId]: merged }
    return merged
  }

  /** 往前翻历史,直到找到 untilMsgId(最多 5 页)。搜索定位用。 */
  async function loadOlder(peerId: string, untilMsgId: string, maxPages = 5): Promise<void> {
    await ensureConnected()
    let list = messagesOf(peerId)
    for (let page = 0; page < maxPages; page++) {
      if (list.some((item) => item.msgId === untilMsgId)) return
      const oldestSeq = list[0]?.seq ?? 0
      if (oldestSeq <= 1) return
      const older = await client.fetchHistory(peerId, 50, oldestSeq)
      if (!older.length) return
      list = mergeMessages(list, older)
      messages.value = { ...messages.value, [peerId]: list }
      if (older.length < 50) return
    }
  }

  /** 搜索聊天记录(仅自建后端;入口由 capabilities.search 控制)。 */
  async function searchMessages(
    keyword: string,
    limit = 20,
    beforeId?: string,
  ): Promise<ImSearchResult> {
    await ensureConnected()
    return client.searchMessages(keyword, limit, beforeId)
  }

  async function openConversation(peerId: string): Promise<ChatMessage[]> {
    const list = await loadHistory(peerId)
    await client.markConversationRead(peerId)
    setLocalUnread(peerId, 0)
    return list
  }

  async function sendText(peerId: string, text: string): Promise<ChatMessage> {
    await ensureConnected()
    const message = await client.sendText(peerId, text)
    appendMessage(peerId, message)
    upsertConversation({ ...message, isSelf: true })
    return message
  }

  async function sendImage(peerId: string, file: File): Promise<ChatMessage> {
    await ensureConnected()
    const message = await client.sendImage(peerId, file)
    pendingFiles.set(message.msgId, file)
    appendMessage(peerId, message)
    upsertConversation({ ...message, isSelf: true })
    return message
  }

  async function sendVoice(peerId: string, blob: Blob, durationMs: number): Promise<ChatMessage> {
    await ensureConnected()
    const message = await client.sendVoice(peerId, blob, durationMs)
    pendingVoices.set(message.msgId, { blob, durationMs })
    appendMessage(peerId, message)
    upsertConversation({ ...message, isSelf: true })
    return message
  }

  /** 重发失败的消息:文本直接重发,图片/语音用缓存的本地内容重发。 */
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
    if (message.kind === 'voice') {
      const voice = pendingVoices.get(message.msgId)
      if (!voice) return
      pendingVoices.delete(message.msgId)
      await sendVoice(message.peerId, voice.blob, voice.durationMs)
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
    await ensureConnected()
    await client.deleteMessage(message.msgId)
  }

  /** 撤回成功/收到撤回事件:把对应消息标成已撤回(气泡变居中灰字)。 */
  function markRevoked(msgId: string): void {
    const next = { ...messages.value }
    for (const [peerId, list] of Object.entries(next)) {
      if (list.some((item) => item.msgId === msgId)) {
        next[peerId] = list.map((item) =>
          item.msgId === msgId ? { ...item, isRevoked: true } : item,
        )
      }
    }
    messages.value = next
  }

  async function revokeMessage(message: ChatMessage): Promise<void> {
    await ensureConnected()
    await client.revokeMessage(message.msgId)
    markRevoked(message.msgId)
  }

  async function deleteConversation(peerId: string): Promise<void> {    await ensureConnected()
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
    capabilities.value = { image: false, search: false, voice: false }
    status.value = 'idle'
  }

  return {
    conversations,
    messages,
    status,
    error,
    capabilities,
    unreadTotal,
    connect,
    reconnect,
    loadConversations,
    loadHistory,
    loadOlder,
    searchMessages,
    openConversation,
    sendText,
    sendImage,
    sendVoice,
    resend,
    deleteMessage,
    revokeMessage,
    deleteConversation,
    messagesOf,
    close,
  }
})
