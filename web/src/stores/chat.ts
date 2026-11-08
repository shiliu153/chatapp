import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { http } from '@/api/http'
import { parseApiError } from '@/api/error'
import { sessionEvents } from '@/api/session-events'
import { getImClient } from '@/im/client'
import { ChatMessageKind, SYSTEM_NOTICE_PEER_ID } from '@/im/types'
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
  /** 上次连接失败是 403(封禁/账号异常):重连没有意义,交给路由守卫 */
  const banned = ref(false)
  /**
   * 当前 IM 客户端能力(图片/搜索入口按它显示)。
   *
   * 必须是响应式状态:`client.capabilities` 只是普通 getter,`getImClient()`
   * 在 init 之前拿到的是「未连接」的兜底值,直接读它会把入口永久藏起来
   * (2026-10-26 排查发现:Web 聊天页图片入口因此一直不显示)。
   */
  const capabilities = ref<ImCapabilities>({
    image: false,
    search: false,
    voice: false,
    readReceipt: false,
  })
  /** 发送失败/待发送的图片文件,供「重发」用(键含本地占位 id) */
  const pendingFiles = ref<Record<string, File>>({})
  /** 发送失败/待发送的语音,供「重发」用 */
  const pendingVoices = new Map<string, { blob: Blob; durationMs: number }>()
  /** 进行中的连接(并发调用复用它) */
  let inFlight: Promise<void> | null = null
  /** 当前正在看的会话(重连后补拉它的历史);由 openConversation 维护 */
  const activePeerId = ref<string | null>(null)
  /**
   * 对端在每个会话里读到哪(已读回执)。
   *
   * **只增不减**:下行 `read` 帧可能乱序/重复到达,收到更小的 N 必须忽略,
   * 否则会出现「已读」跳回「未读」。`seq <= peerReadSeq[peerId]` 的我方消息算已读。
   */
  const peerReadSeq = ref<Record<string, number>>({})
  /** 断线重连的退避定时器(同一时刻只排一个) */
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  /** 第几次退避,成功连上后清零 */
  let reconnectAttempt = 0
  /** 退避档位(秒),与 App 的 self_im_client.dart 一致 */
  const RECONNECT_DELAYS = [1, 2, 4, 8, 16, 30]

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
          // 新会话还没同步过已读位置;下一次 loadConversations 会带上真值
          peerReadSeq: peerReadSeq.value[message.peerId] ?? 0,
        },
      ]
    }
    sortConversations()
  }

  function appendMessage(peerId: string, message: ChatMessage): void {
    const list = messages.value[peerId] ?? []
    messages.value = { ...messages.value, [peerId]: mergeMessages(list, [message]) }
  }

  /** 就地替换一条消息(乐观占位 → 真实消息 / 失败态),不改变列表顺序。 */
  function replaceMessage(msgId: string, next: ChatMessage): void {
    const current = messages.value
    for (const [peerId, list] of Object.entries(current)) {
      if (!list.some((item) => item.msgId === msgId)) continue
      messages.value = {
        ...current,
        [peerId]: list.map((item) => (item.msgId === msgId ? next : item)),
      }
      return
    }
  }

  function messagesOf(peerId: string): ChatMessage[] {
    return messages.value[peerId] ?? []
  }

  function setLocalUnread(peerId: string, count: number): void {
    const target = conversations.value.find((item) => item.peerId === peerId)
    if (target) target.unreadCount = count
  }

  /** 推进「对端读到哪」;只增不减,没变大就什么都不做(避免无意义重渲染)。 */
  function advancePeerRead(peerId: string, seq: number): void {
    if (!peerId || seq <= (peerReadSeq.value[peerId] ?? 0)) return
    peerReadSeq.value = { ...peerReadSeq.value, [peerId]: seq }
  }

  /**
   * 跨端已读(多端在线 K-3):我在另一台设备上读完了这个会话。
   *
   * 只把**未读**清零 —— `peerReadSeq`(对端读我)一律不动,那是另一条链路,
   * 动了就是假已读。`seq` 只是服务端回读后的真实位置,这里用不到(未读由服务端算好)。
   */
  function clearUnread(peerId: string): void {
    if (!peerId) return
    setLocalUnread(peerId, 0)
  }

  /**
   * 跨端删除(多端在线 K-3):我在另一台设备上删了这个会话。
   *
   * 立刻从列表移除并丢掉本地消息缓存;正看着它就把 activePeerId 清掉,
   * 聊天页据此退回列表(`ChatPage.vue` 的 watch)。**对方不会收到这个事件** ——
   * 删除是单方行为。
   */
  function removeConversation(peerId: string): void {
    if (!peerId) return
    conversations.value = conversations.value.filter((item) => item.peerId !== peerId)
    if (peerId in messages.value) {
      const rest = { ...messages.value }
      delete rest[peerId]
      messages.value = rest
    }
    if (activePeerId.value === peerId) activePeerId.value = null
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
    if (event.type === 'peerRead') {
      advancePeerRead(event.peerId, event.seq)
      return
    }
    if (event.type === 'selfRead') {
      clearUnread(event.peerId)
      return
    }
    if (event.type === 'conversationDeleted') {
      removeConversation(event.peerId)
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
        cancelReconnect()
        status.value = 'inactive'
        return
      }
      // 分流二:真的被别的设备顶掉 → 全屏提示 + 清凭证
      cancelReconnect()
      sessionEvents.emitKickedOffline()
      return
    }
    if (event.type === 'disconnected') {
      // ⚠️ 分流三:连接断了(服务端 75s 空闲踢出、网络抖动、切后台)。
      //    与「被顶号」完全不同:这里**必须**自动退避重连,否则前端仍显示 ready,
      //    对方的新消息会静默丢失(2026-11-03 全栈审查 N-1)。
      //    已被顶掉(inactive)或已退出(idle)时不重连,避免和用户抢连接。
      if (status.value === 'inactive' || status.value === 'idle') return
      scheduleReconnect()
    }
  })

  /** 取 IM 凭证 → 登录 IM。403(重封禁)不重试,交给路由守卫处理。 */
  async function doConnect(): Promise<void> {
    error.value = ''
    banned.value = false
    try {
      const { data } = await http.post('/im/user_sig')
      const raw = data as {
        im_user_id: string
        token?: string
      }
      // Web 永远走同源:忽略后端返回的绝对地址(可能是 App 用的 10.0.2.2)
      const wsUrl = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/im/ws`
      const httpUrl = new URL('/im/api', location.origin).toString()
      const bootstrap: ImBootstrap = {
        token: raw.token ?? '',
        wsUrl,
        httpUrl,
        imUserId: raw.im_user_id,
      }
      await client.init(bootstrap)
      await client.login(raw.im_user_id, raw.token ?? '')
      // 连上之后才拿得到真实能力位(init 之前客户端还没握手)
      capabilities.value = { ...client.capabilities }
      reconnectAttempt = 0
      status.value = 'ready'
    } catch (e) {
      const apiError = parseApiError(e)
      error.value = apiError.message
      status.value = 'error'
      // 403(封禁/账号异常)重连多少次都一样,别退避重试
      banned.value = apiError.isBanned
    }
  }

  /** 断线退避重连:1/2/4/8/16/30 秒,同一时刻只排一个定时器。 */
  function scheduleReconnect(): void {
    status.value = 'reconnecting'
    if (reconnectTimer) return // 已经排上了,别叠加
    const seconds = RECONNECT_DELAYS[Math.min(reconnectAttempt, RECONNECT_DELAYS.length - 1)]
    reconnectAttempt += 1
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      void doReconnect()
    }, seconds * 1000)
  }

  /** 取消排期中的重连(退出登录、被顶号时用)。 */
  function cancelReconnect(): void {
    if (reconnectTimer) clearTimeout(reconnectTimer)
    reconnectTimer = null
  }

  /**
   * 读当前连接状态。
   *
   * 必须经函数读:`status.value` 是 Pinia 的 ref,TypeScript 会顺着同一函数里的赋值
   * 收窄它的字面量类型,直接比较 `=== 'ready'` 会被判成「永假」(TS2367)。
   */
  function currentStatus(): ChatStatus {
    return status.value
  }

  async function doReconnect(): Promise<void> {
    if (status.value === 'inactive' || status.value === 'idle') return
    if (status.value === 'ready') return
    await connect()
    if (currentStatus() === 'ready') {
      // 断线期间的消息服务端不会主动重放:必须补拉会话列表 + 当前会话历史
      await refetchAfterReconnect()
      return
    }
    if (banned.value) return // 403 不重试
    scheduleReconnect() // 网络还没好:继续退避
  }

  /** 重连成功后的补拉。失败只吞掉:下一轮断线还会再补。 */
  async function refetchAfterReconnect(): Promise<void> {
    await loadConversations().catch(() => {})
    const peerId = activePeerId.value
    if (peerId) await loadHistory(peerId).catch(() => {})
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
   * 所有 IM 操作前都要先确保已连接 —— 否则会在 `init()` 之前就用空凭证去连 WS,
   * 之后所有调用都会失败(真机踩到过)。
   */
  async function ensureConnected(): Promise<void> {
    await connect()
  }

  /** 被同端顶掉后由用户显式接管(见 multiAccount 分流注释)。 */
  async function reconnect(): Promise<void> {
    cancelReconnect()
    reconnectAttempt = 0
    status.value = 'reconnecting'
    await doConnect()
    if (currentStatus() === 'ready') await refetchAfterReconnect()
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
    // 记下来:断线重连后要补拉「当前正在看的会话」(见 refetchAfterReconnect)
    activePeerId.value = peerId
    const list = await loadHistory(peerId)
    await client.markConversationRead(peerId)
    setLocalUnread(peerId, 0)
    // 已读回执的**补拉**:断线期间对方读过什么,那时下行 read 帧根本没送到,
    // 只能打开会话时问一次会话列表(`peer_read_seq` 是唯一事实来源)。
    // 失败静默 —— 最坏只是不显示「已读」,不该让聊天页打不开。
    try {
      await loadConversations()
      const conversation = conversations.value.find((item) => item.peerId === peerId)
      if (conversation) advancePeerRead(peerId, conversation.peerReadSeq)
    } catch {
      /* 忽略:已读态拿不到不影响聊天 */
    }
    return list
  }

  async function sendText(peerId: string, text: string): Promise<ChatMessage> {
    await ensureConnected()
    const message = await client.sendText(peerId, text)
    appendMessage(peerId, message)
    upsertConversation({ ...message, isSelf: true })
    return message
  }

  /** 取出一份待发文件并从缓存里摘掉(重发时用)。 */
  function takePendingFile(msgId: string): File | null {
    const file = pendingFiles.value[msgId] ?? null
    if (!file) return null
    const rest = { ...pendingFiles.value }
    delete rest[msgId]
    pendingFiles.value = rest
    return file
  }

  /**
   * 乐观发送图片:先上屏本地预览占位,成功后就地替换。
   *
   * 占位必须先于 `ensureConnected()` 插入,失败时才有一条可重试的气泡;
   * 文件同时缓存进 `pendingFiles`,否则「重发」拿不到内容会静默失效。
   */
  async function sendImage(peerId: string, file: File): Promise<ChatMessage> {
    const placeholder: ChatMessage = {
      msgId: `local-${Date.now()}`,
      peerId,
      isSelf: true,
      seq: 0,
      timestamp: Date.now(),
      kind: ChatMessageKind.image,
      text: '',
      senderName: '',
      senderAvatar: null,
      isPending: true,
      isFailed: false,
      imageUrl: null,
      imageLargeUrl: null,
      isRevoked: false,
    }
    appendMessage(peerId, placeholder)
    pendingFiles.value = { ...pendingFiles.value, [placeholder.msgId]: file }
    try {
      await ensureConnected()
      const sent = await client.sendImage(peerId, file)
      replaceMessage(placeholder.msgId, sent)
      // 本地文件改挂到真实 msgId 上,重发时还能用
      const kept = takePendingFile(placeholder.msgId)
      if (kept) pendingFiles.value = { ...pendingFiles.value, [sent.msgId]: kept }
      upsertConversation({ ...sent, isSelf: true })
      return sent
    } catch (error) {
      replaceMessage(placeholder.msgId, { ...placeholder, isPending: false, isFailed: true })
      throw error
    }
  }

  /**
   * 乐观发送:先上屏占位(失败可重试),成功后就地替换成真实消息。
   *
   * 占位必须先于 `ensureConnected()` 插入 —— 连不上时也要留一条可重试的气泡,
   * 否则用户录了一段话会凭空消失。
   */
  async function sendVoice(peerId: string, blob: Blob, durationMs: number): Promise<ChatMessage> {
    const placeholder: ChatMessage = {
      msgId: `local-${Date.now()}`,
      peerId,
      isSelf: true,
      seq: 0,
      timestamp: Date.now(),
      kind: ChatMessageKind.voice,
      text: '',
      senderName: '',
      senderAvatar: null,
      isPending: true,
      isFailed: false,
      imageUrl: null,
      imageLargeUrl: null,
      voiceUrl: null,
      voiceDurationMs: durationMs,
      isRevoked: false,
    }
    appendMessage(peerId, placeholder)
    pendingVoices.set(placeholder.msgId, { blob, durationMs })
    try {
      await ensureConnected()
      const sent = await client.sendVoice(peerId, blob, durationMs)
      replaceMessage(placeholder.msgId, sent)
      pendingVoices.delete(placeholder.msgId)
      pendingVoices.set(sent.msgId, { blob, durationMs })
      upsertConversation({ ...sent, isSelf: true })
      return sent
    } catch (error) {
      replaceMessage(placeholder.msgId, { ...placeholder, isPending: false, isFailed: true })
      throw error
    }
  }

  /**
   * 乐观发送贴纸(批次 J):先上屏占位,成功后就地替换。
   *
   * 与图片/语音不同,贴纸**不需要缓存本地内容** —— id 本身就在消息里,
   * 重发时直接用 `message.stickerId`。
   */
  async function sendSticker(peerId: string, stickerId: string): Promise<ChatMessage> {
    const placeholder: ChatMessage = {
      msgId: `local-${Date.now()}`,
      peerId,
      isSelf: true,
      seq: 0,
      timestamp: Date.now(),
      kind: ChatMessageKind.sticker,
      text: '',
      senderName: '',
      senderAvatar: null,
      isPending: true,
      isFailed: false,
      imageUrl: null,
      imageLargeUrl: null,
      stickerId,
      isRevoked: false,
    }
    appendMessage(peerId, placeholder)
    try {
      await ensureConnected()
      const sent = await client.sendSticker(peerId, stickerId)
      replaceMessage(placeholder.msgId, sent)
      upsertConversation({ ...sent, isSelf: true })
      return sent
    } catch (error) {
      replaceMessage(placeholder.msgId, { ...placeholder, isPending: false, isFailed: true })
      throw error
    }
  }

  /** 重发失败的消息:文本直接重发,图片/语音用缓存的本地内容重发。 */
  async function resend(message: ChatMessage): Promise<void> {
    const list = messagesOf(message.peerId).filter((item) => item.msgId !== message.msgId)
    messages.value = { ...messages.value, [message.peerId]: list }
    if (message.kind === 'sticker' && message.stickerId) {
      await sendSticker(message.peerId, message.stickerId)
      return
    }
    if (message.kind === 'image') {
      const file = takePendingFile(message.msgId)
      if (!file) return
      await sendImage(message.peerId, file)
      return
    }
    if (message.kind === 'voice') {
      const voice = pendingVoices.get(message.msgId)
      if (!voice) return
      pendingVoices.delete(message.msgId)
      messages.value = {
        ...messages.value,
        [message.peerId]: messagesOf(message.peerId).filter((item) => item.msgId !== message.msgId),
      }
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
    takePendingFile(message.msgId)
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

  async function deleteConversation(peerId: string): Promise<void> {
    await ensureConnected()
    await client.deleteConversation(peerId)
    conversations.value = conversations.value.filter((item) => item.peerId !== peerId)
    const rest = { ...messages.value }
    delete rest[peerId]
    messages.value = rest
    if (activePeerId.value === peerId) activePeerId.value = null
  }

  async function close(): Promise<void> {
    cancelReconnect()
    reconnectAttempt = 0
    activePeerId.value = null
    await client.logout().catch(() => {})
    conversations.value = []
    messages.value = {}
    peerReadSeq.value = {}
    capabilities.value = {
      image: false,
      search: false,
      voice: false,
      readReceipt: false,
    }
    status.value = 'idle'
  }

  return {
    conversations,
    messages,
    status,
    error,
    capabilities,
    unreadTotal,
    /** 对端在每个会话里读到哪(已读回执);`seq <= peerReadSeq[peerId]` 的我方消息算已读 */
    peerReadSeq,
    /** 待发送图片的本地文件(键 = 消息 id),页面用它做发送中预览 */
    pendingFiles,
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
    sendSticker,
    resend,
    deleteMessage,
    revokeMessage,
    deleteConversation,
    messagesOf,
    close,
  }
})
