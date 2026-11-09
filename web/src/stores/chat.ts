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
  ImConversationFlags,
  ImConversationFlagsResult,
  ImSearchResult,
  QuoteRef,
  QuoteTarget,
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
  /**
   * 对端是否正在输入(批次 L-1),按会话记。
   *
   * 语义是「**最近 5 秒内**收到过对端的 `typing` 帧」,不是持久状态:typing 是可丢
   * 信号,服务端不落库、不补发、超限静默丢弃,所以必须自己过期 —— 否则对端停手
   * 之后「正在输入…」会一直挂着。
   */
  const peerTyping = ref<Record<string, boolean>>({})
  /** 每个会话的 5 秒过期定时器(收到新帧就续期) */
  const typingExpiryTimers = new Map<string, ReturnType<typeof setTimeout>>()
  /** 每个会话的 3 秒发送冷却(客户端节流,服务端另有令牌桶兜底) */
  const typingCooldownTimers = new Map<string, ReturnType<typeof setTimeout>>()
  /**
   * 当前会话的引用目标(批次 L-2):输入栏上方的引用条读它,发送成功后清空。
   *
   * 只存 id + 本地摘要 —— 上行**只发 `ref_msg_id`**,真正的内容由服务端回库查后
   * 生成快照(客户端传内容等于允许伪造「对方说过 X」)。
   */
  const quoteTarget = ref<QuoteTarget | null>(null)
  /** 自己的 IM id:引用条上判断「这句话是我说的还是对端说的」。连上之后才有值。 */
  const selfImId = ref('')
  /** 收帧后多久自动隐藏「正在输入…」(与设计文档 §3.3 一致) */
  const TYPING_EXPIRY_MS = 5000
  /** 客户端节流窗口:3 秒内最多发一次 */
  const TYPING_THROTTLE_MS = 3000
  /** 断线重连的退避定时器(同一时刻只排一个) */
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  /** 第几次退避,成功连上后清零 */
  let reconnectAttempt = 0
  /** 退避档位(秒),与 App 的 self_im_client.dart 一致 */
  const RECONNECT_DELAYS = [1, 2, 4, 8, 16, 30]

  const unreadTotal = computed(() =>
    conversations.value.reduce((sum, item) => sum + item.unreadCount, 0),
  )

  /**
   * 这个会话算不算「置顶组」。
   *
   * 系统通知是伪会话(不算用户的置顶偏好),但老规矩是恒在最前(spec §8),
   * 所以把它一并归进置顶组 —— 规则只写这一处,排序与分组标题都从这里派生。
   */
  function inPinnedGroup(item: ImConversation): boolean {
    return item.pinned || item.peerId === SYSTEM_NOTICE_PEER_ID
  }

  /**
   * 置顶组:组内**保持服务端返回顺序**(客户端不再排一次)。
   *
   * 服务端按 `ORDER BY (pinned_at>0) DESC, pinned_at DESC, last_msg_at DESC` 排好,
   * 后置顶的更靠前 —— 而 `pinned_at` 不下发,客户端根本排不出同样的顺序,重排只会打架。
   */
  const pinnedConversations = computed(() => conversations.value.filter(inPinnedGroup))

  /** 非置顶组:按最近消息排(本地新消息到达时也要能往上浮)。 */
  const otherConversations = computed(() =>
    conversations.value
      .filter((item) => !inPinnedGroup(item))
      .sort((a, b) => (b.lastMessage?.timestamp ?? 0) - (a.lastMessage?.timestamp ?? 0)),
  )

  function sortConversations(): void {
    conversations.value = [...pinnedConversations.value, ...otherConversations.value]
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
          // 只有服务端知道置顶/免打扰(批次 N):新会话先按「都没有」显示,
          // 下一次 loadConversations 会用真值覆盖。
          pinned: false,
          muted: false,
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

  /** 选中一条消息作为引用目标(批次 L-2)。 */
  function setQuoteTarget(target: QuoteTarget): void {
    quoteTarget.value = target
  }

  /** 取消引用(发送成功 / 点关闭按钮 / 切会话 / 退出登录)。 */
  function clearQuoteTarget(): void {
    quoteTarget.value = null
  }

  /**
   * 把引用目标变成一份**本地**快照,只用于刚发出的气泡上屏。
   *
   * 上行只发了 id,回执里自然没有 `ref`;不补这一份的话,引用块会在发送成功的
   * 一瞬间从气泡上消失。下次拉历史时由服务端的快照替换。
   */
  function localRefOf(target: QuoteTarget): QuoteRef {
    return {
      msgId: target.msgId,
      from: target.from,
      kind: 'text',
      text: target.text,
      revoked: false,
    }
  }

  /** 清掉某个会话的「正在输入」(连同它的 5 秒过期定时器)。 */
  function clearTyping(peerId: string): void {
    if (!peerId) return
    const timer = typingExpiryTimers.get(peerId)
    if (timer) {
      clearTimeout(timer)
      typingExpiryTimers.delete(peerId)
    }
    if (!(peerId in peerTyping.value)) return
    const rest = { ...peerTyping.value }
    delete rest[peerId]
    peerTyping.value = rest
  }

  /**
   * 收到对端的 `typing` 帧(批次 L-1):置真,并把 5 秒过期往后推。
   *
   * 为什么要自己过期:typing 是可丢信号,服务端不落库、不补发,「对端停手了」
   * 这件事没有任何帧会告诉客户端 —— 只能靠超时。
   */
  function markPeerTyping(peerId: string): void {
    if (!peerId) return
    const timer = typingExpiryTimers.get(peerId)
    if (timer) clearTimeout(timer)
    peerTyping.value = { ...peerTyping.value, [peerId]: true }
    typingExpiryTimers.set(
      peerId,
      setTimeout(() => {
        typingExpiryTimers.delete(peerId)
        clearTyping(peerId)
      }, TYPING_EXPIRY_MS),
    )
  }

  /**
   * 我在输入框里打字(批次 L-1):按 **3 秒**节流给服务端发一次 `typing`。
   *
   * 客户端节流只省流量;服务端另有 1 次 / 2 秒的令牌桶 —— 那层才是防伪造的。
   * 发不出去(没连上 / 被服务端静默丢弃)一律吞掉:这是可丢信号,不该弹错。
   */
  function notifyTyping(peerId: string): void {
    if (!peerId || typingCooldownTimers.has(peerId)) return
    typingCooldownTimers.set(
      peerId,
      setTimeout(() => typingCooldownTimers.delete(peerId), TYPING_THROTTLE_MS),
    )
    void client.sendTyping(peerId).catch(() => {})
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
    if (event.type === 'typing') {
      // 对端正在输入(批次 L-1)。只对**当前会话**有意义,其它会话的帧直接忽略。
      if (event.peerId === activePeerId.value) markPeerTyping(event.peerId)
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
      selfImId.value = raw.im_user_id
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
    // 切会话先清掉上一个会话的「正在输入」(批次 L-1):它是瞬时状态,不能跨会话残留
    const previous = activePeerId.value
    if (previous && previous !== peerId) {
      clearTyping(previous)
      // 引用条也不能跨会话残留:切走就等于「不引用了」(批次 L-2)
      clearQuoteTarget()
    }
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
    const target = quoteTarget.value
    const sent = await client.sendText(peerId, text, target?.msgId)
    const message = target ? { ...sent, ref: localRefOf(target) } : sent
    appendMessage(peerId, message)
    upsertConversation({ ...message, isSelf: true })
    // 发出去就清掉引用条:下一条消息默认不带引用(失败时上面会抛,引用条留着)
    if (target) clearQuoteTarget()
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
      const target = quoteTarget.value
      const sent = await client.sendImage(peerId, file, target?.msgId)
      const message = target ? { ...sent, ref: localRefOf(target) } : sent
      replaceMessage(placeholder.msgId, message)
      // 本地文件改挂到真实 msgId 上,重发时还能用
      const kept = takePendingFile(placeholder.msgId)
      if (kept) pendingFiles.value = { ...pendingFiles.value, [sent.msgId]: kept }
      upsertConversation({ ...message, isSelf: true })
      if (target) clearQuoteTarget()
      return message
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
      const target = quoteTarget.value
      const sent = await client.sendVoice(peerId, blob, durationMs, target?.msgId)
      const message = target ? { ...sent, ref: localRefOf(target) } : sent
      replaceMessage(placeholder.msgId, message)
      pendingVoices.delete(placeholder.msgId)
      pendingVoices.set(sent.msgId, { blob, durationMs })
      upsertConversation({ ...message, isSelf: true })
      if (target) clearQuoteTarget()
      return message
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
      const target = quoteTarget.value
      const sent = await client.sendSticker(peerId, stickerId, target?.msgId)
      const message = target ? { ...sent, ref: localRefOf(target) } : sent
      replaceMessage(placeholder.msgId, message)
      upsertConversation({ ...message, isSelf: true })
      if (target) clearQuoteTarget()
      return message
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
    removeConversation(peerId)
  }

  /**
   * 改会话的置顶 / 免打扰(批次 N)。
   *
   * 写入成功后按**服务端回读的真值**更新本地标志位,然后重拉一次会话列表 ——
   * 顺序以服务端为准(置顶组按置顶时间倒序,`pinned_at` 不下发,客户端排不出来)。
   * 重拉失败只吞掉:标志位已经生效,没必要因为它把成功变成失败。
   *
   * 失败(含会话不存在 `40401`、限流 `42901`)时**本地状态原样保留**,错误上抛给
   * 调用方提示 —— 不做乐观更新,免得失败后界面显示一个并不存在的状态。
   *
   * Args:
   *   peerId: 会话对端的 IM id,如 `u9`。
   *   flags: 要改的那几项;缺省的那一项不改。
   *
   * Returns:
   *   服务端回读后的 `{pinned, muted}`。
   */
  async function setConversationFlags(
    peerId: string,
    flags: ImConversationFlags,
  ): Promise<ImConversationFlagsResult> {
    await ensureConnected()
    const result = await client.setConversationFlags(peerId, flags)
    const target = conversations.value.find((item) => item.peerId === peerId)
    if (target) {
      target.pinned = result.pinned
      target.muted = result.muted
    }
    await loadConversations().catch(() => {})
    return result
  }

  async function close(): Promise<void> {
    cancelReconnect()
    reconnectAttempt = 0
    // 输入中状态的定时器一并收掉(批次 L-1):否则退出登录后它们还会回调
    for (const peerId of [...typingExpiryTimers.keys()]) clearTyping(peerId)
    for (const timer of typingCooldownTimers.values()) clearTimeout(timer)
    typingCooldownTimers.clear()
    activePeerId.value = null
    quoteTarget.value = null
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
    /** 置顶组(含系统通知):顺序 = 服务端返回顺序,消息页据此分组渲染(批次 N) */
    pinnedConversations,
    /** 非置顶组:按最近消息排,消息页「全部会话」分组读它(批次 N) */
    otherConversations,
    messages,
    status,
    error,
    capabilities,
    unreadTotal,
    /** 对端在每个会话里读到哪(已读回执);`seq <= peerReadSeq[peerId]` 的我方消息算已读 */
    peerReadSeq,
    /** 对端是否正在输入(批次 L-1),按会话记;5 秒没有新帧自动清掉 */
    peerTyping,
    /** 我在输入框里打字:按 3 秒节流发一次 `typing`(批次 L-1) */
    notifyTyping,
    /** 离开会话页时立即清掉「正在输入…」(批次 L-1) */
    clearPeerTyping: clearTyping,
    /** 当前会话的引用目标(批次 L-2);输入栏上方的引用条读它 */
    quoteTarget,
    /** 自己的 IM id(引用条署名用) */
    selfImId,
    /** 选中一条消息作为引用目标(批次 L-2) */
    setQuoteTarget,
    /** 取消引用(批次 L-2) */
    clearQuoteTarget,
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
    /** 置顶 / 免打扰(批次 N):写入后按服务端真值更新本地并重拉列表 */
    setConversationFlags,
    messagesOf,
    close,
  }
})
