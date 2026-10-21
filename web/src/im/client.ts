/**
 * 腾讯云 IM 客户端封装。
 *
 * 设计要点:
 * 1. **业务层只见 `ImClient` / `ImEvent`**,SDK 类型不外泄(用 `./types` 的结构化最小类型)。
 * 2. **真 SDK 惰性加载**:模块顶层不 import `@tencentcloud/chat`,避免单测在 jsdom 里把
 *    整个 SDK 拉起来;只有真正要走网络时(`init` → `login`)才动态 import。
 * 3. 事件名默认值写死为 spike 实测值(见计划三执行记录 Task 6.1),测试可注入假名。
 */
import { chatMessageFromTim, conversationFromTim } from './map'
import { RoutingImClient } from './routing'
import {
  ChatMessageKind,
  type ChatMessage,
  type ImBootstrap,
  type ImClient,
  type ImConversation,
  type ImEvent,
  type ImEventNames,
  type KickReason,
  type TimChatLike,
  type TimMessageLike,
} from './types'

/** spike 实测的事件名(SDK 常量值)。 */
export const DEFAULT_EVENT_NAMES: ImEventNames = {
  messageReceived: 'onMessageReceived',
  conversationListUpdated: 'onConversationListUpdated',
  messageRevoked: 'onMessageRevoked',
  kickedOut: 'kickedOut',
  ready: 'sdkStateReady',
}

// 使用方(含测试)从本模块取类型,不必知道文件布局
export type { TimChatLike, ImClient, ImEvent } from './types'

/**
 * 全局单例入口。Pinia 的 `useXxxStore()` 不接受参数,所以 store 只能通过这个工厂拿客户端;
 * 测试用 `setImClientFactory` 换成假实现(`useChatStore()` 之前调用)。
 */
let factory: () => ImClient = () => new RoutingImClient()

/** 仅供测试替换;生产路径不要调用。 */
export function setImClientFactory(fn: () => ImClient): void {
  factory = fn
}

export function getImClient(): ImClient {
  return factory()
}

/** 踢出原因:同端多实例 vs 多端登录,处理方式不同(同端多实例绝不能清凭证)。 */
export function kickReasonOf(raw: unknown): KickReason {
  const type = (raw as { type?: string } | null)?.type ?? ''
  if (type === 'multipleDevice') return 'multiDevice'
  if (type === 'multipleAccount') return 'multiAccount'
  if (type === 'userSigExpired') return 'sigExpired'
  return 'restApi'
}

export interface CreateImClientOptions {
  /** 注入假 SDK(测试);不传则走真 SDK 惰性加载。 */
  sdk?: TimChatLike
  events?: Partial<ImEventNames>
}

/** 真 SDK 的加载结果(只在这里出现 `unknown` 转换,不外泄)。 */
interface RealSdkBundle {
  create(options: { SDKAppID: number }): TimChatLike
  plugin: unknown
}

let realSdkPromise: Promise<RealSdkBundle> | null = null

async function loadRealSdk(): Promise<RealSdkBundle> {
  realSdkPromise ??= (async () => {
    const [chatModule, pluginModule] = await Promise.all([
      import('@tencentcloud/chat'),
      import('tim-upload-plugin'),
    ])
    const chat = (chatModule as { default?: unknown }).default ?? chatModule
    const plugin = (pluginModule as { default?: unknown }).default ?? pluginModule
    return {
      create: (options) => (chat as { create(o: { SDKAppID: number }): TimChatLike }).create(options),
      plugin,
    }
  })()
  return realSdkPromise
}

export function createImClient(options: CreateImClientOptions = {}): ImClient {
  const names: ImEventNames = { ...DEFAULT_EVENT_NAMES, ...options.events }
  const listeners: ((event: ImEvent) => void)[] = []
  /** msgId → 原始 SDK 消息(删除本地消息需要消息实例) */
  const known = new Map<string, TimMessageLike>()

  let sdk: TimChatLike | null = null
  let pendingSdk: Promise<TimChatLike> | null = null
  let wired = false
  let sdkAppId = 0

  function emit(event: ImEvent): void {
    for (const listener of listeners) listener(event)
  }

  function onEvent(listener: (event: ImEvent) => void): void {
    listeners.push(listener)
  }

  function remember(messages: TimMessageLike[]): void {
    for (const message of messages) known.set(message.ID, message)
  }

  function wire(instance: TimChatLike): void {
    if (wired) return
    wired = true
    instance.on(names.messageReceived, (event) => {
      const messages = (Array.isArray(event.data) ? event.data : []) as TimMessageLike[]
      remember(messages)
      for (const message of messages) emit({ type: 'newMessage', message: chatMessageFromTim(message) })
    })
    instance.on(names.conversationListUpdated, () => emit({ type: 'conversationsChanged' }))
    instance.on(names.messageRevoked, (event) => {
      const data = event.data as { msgID?: string } | string | null
      const msgId = typeof data === 'string' ? data : data?.msgID
      if (msgId) emit({ type: 'messageRevoked', msgId })
    })
    instance.on(names.ready, () => emit({ type: 'ready' }))
    instance.on(names.kickedOut, (event) => {
      emit({ type: 'kickedOffline', reason: kickReasonOf(event.data) })
    })
  }

  async function ensureSdk(): Promise<TimChatLike> {
    if (sdk) return sdk
    if (!pendingSdk) {
      pendingSdk = loadRealSdk().then((bundle) => {
        const instance = bundle.create({ SDKAppID: sdkAppId })
        // ⚠️ 必须在 login 之前注册:上传模块在构造时就缓存插件引用,
        //    登录后再注册会一直报 `code 2040 未检测到上传插件`(spike 实测)。
        instance.registerPlugin?.({ 'tim-upload-plugin': bundle.plugin })
        sdk = instance
        wire(instance)
        return instance
      })
    }
    return pendingSdk
  }

  function init(bootstrap: ImBootstrap): void {
    sdkAppId = bootstrap.sdkAppId
  }

  /**
   * 等 SDK 真正就绪。
   * ⚠️ spike 实测:login 的 Promise resolve 时 `isReady()` 仍是 false,
   * 此时调其它 API 会拿到「SDK 未就绪」错误(真机上表现为聊天历史永远空白)。
   */
  async function waitForReady(instance: TimChatLike, timeoutMs = 10_000): Promise<void> {
    if (instance.isReady()) return
    await new Promise<void>((resolve) => {
      let settled = false
      const finish = () => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        instance.off(names.ready, handler)
        resolve()
      }
      const handler = () => finish()
      const timer = setTimeout(finish, timeoutMs)
      instance.on(names.ready, handler)
    })
  }

  async function login(userId: string, userSig: string): Promise<void> {
    const instance = await ensureSdk()
    wire(instance)
    await instance.login({ userID: userId, userSig })
    await waitForReady(instance)
  }

  async function logout(): Promise<void> {
    if (!sdk) return
    await sdk.logout()
  }

  async function fetchConversations(): Promise<ImConversation[]> {
    const instance = await ensureSdk()
    const res = await instance.getConversationList()
    const list = res?.data?.conversationList ?? []
    const conversations = list
      .map((conversation) => conversationFromTim(conversation))
      .filter((conversation): conversation is ImConversation => conversation !== null)

    // ⚠️ 实测:新建会话的服务端摘要可能不带昵称/头像,而 SDK **不会**自己补全
    //   (等 8 秒也没变),所以这里主动补拉一次用户资料。
    const unknown = conversations
      .filter((item) => !item.showName && item.peerId !== 'system_notice')
      .map((item) => item.peerId)
    if (unknown.length && instance.getUserProfile) {
      const profiles = await instance.getUserProfile({ userIDList: unknown }).catch(() => null)
      for (const profile of profiles?.data ?? []) {
        const target = conversations.find((item) => item.peerId === profile.userID)
        if (!target) continue
        target.showName = profile.nick ?? ''
        target.faceUrl = target.faceUrl ?? profile.avatar ?? null
      }
    }
    return conversations
  }

  async function fetchHistory(peerId: string, count = 20): Promise<ChatMessage[]> {
    const instance = await ensureSdk()
    const res = await instance.getMessageList({ conversationID: `C2C${peerId}`, count })
    const list = res?.data?.messageList ?? []
    remember(list)
    // SDK 返回的是「最旧 → 最新」,与气泡渲染顺序一致
    return list.map((message) => chatMessageFromTim(message))
  }

  /** 本端消息:SDK 在 send 前可能还没写 flow,这里一律按「自己发的」兜底。 */
  function ownMessage(timMessage: TimMessageLike, peerId: string): ChatMessage {
    const message = chatMessageFromTim(timMessage)
    return {
      ...message,
      isSelf: true,
      peerId: message.peerId || peerId,
      isPending: message.isFailed ? false : message.isPending,
    }
  }

  async function sendText(peerId: string, text: string): Promise<ChatMessage> {
    const instance = await ensureSdk()
    const created = instance.createTextMessage({
      to: peerId,
      conversationType: 'C2C',
      payload: { text },
    })
    const res = (await instance.sendMessage(created)) as { data?: { message?: TimMessageLike } }
    const sent = res?.data?.message ?? created
    remember([sent])
    return ownMessage(sent, peerId)
  }

  async function sendImage(peerId: string, file: File): Promise<ChatMessage> {
    const instance = await ensureSdk()
    // 字段名 `file` 由 spike 实测确认(计划三执行记录 Task 6.1 第 6 条)
    const created = instance.createImageMessage({
      to: peerId,
      conversationType: 'C2C',
      payload: { file },
    })
    const res = (await instance.sendMessage(created)) as { data?: { message?: TimMessageLike } }
    const sent = res?.data?.message ?? created
    remember([sent])
    const message = ownMessage(sent, peerId)
    return { ...message, kind: ChatMessageKind.image }
  }

  async function deleteMessage(msgId: string): Promise<void> {
    const instance = await ensureSdk()
    const message = known.get(msgId)
    if (!message) return // 没见过的消息(不在本地缓存里)无需删除
    await instance.deleteMessage([message])
    known.delete(msgId)
  }

  async function revokeMessage(msgId: string): Promise<void> {
    const instance = await ensureSdk()
    const message = known.get(msgId)
    if (!message) return // 没见过的消息(不在本地缓存里)无需撤回
    await instance.revokeMessage(message)
    known.delete(msgId)
  }

  async function markConversationRead(peerId: string): Promise<void> {
    const instance = await ensureSdk()
    await instance.setMessageRead({ conversationID: `C2C${peerId}` })
  }

  async function deleteConversation(peerId: string): Promise<void> {
    const instance = await ensureSdk()
    await instance.deleteConversation(`C2C${peerId}`)
  }

  // 注入的假 SDK 立即接线(测试里不经过 login 也会触发事件)
  if (options.sdk) {
    sdk = options.sdk
    wire(sdk)
  }

  return {
    onEvent,
    capabilities: { image: true },
    init,
    login,
    logout,
    fetchConversations,
    fetchHistory,
    sendText,
    sendImage,
    deleteMessage,
    revokeMessage,
    markConversationRead,
    deleteConversation,
  }
}
