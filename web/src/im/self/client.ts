import { ApiError } from '@/api/error'
import {
  ChatMessageKind,
  type ChatMessage,
  type ImBootstrap,
  type ImCapabilities,
  type ImClient,
  type ImConversation,
  type ImConversationFlags,
  type ImConversationFlagsResult,
  type ImEvent,
  type ImSearchResult,
} from '../types'
import { type UploadedImage, uploadChatImage } from './image'
import { conversationFromJson, messageFromJson } from './map'
import { BrowserWebSocketTransport, type SelfTransport } from './transport'
import { type UploadedVoice, uploadChatVoice } from './voice'

interface PendingSend {
  peerId: string
  text: string
  /** 图片消息才有:上传结果,ack 回来时用它还原 ChatMessage */
  image?: UploadedImage
  /** 语音消息才有:上传结果,ack 回来时用它还原 ChatMessage */
  voice?: UploadedVoice
  /** 贴纸消息才有:贴纸 id,ack 回来时用它还原 ChatMessage */
  stickerId?: string
  resolve: (message: ChatMessage) => void
  reject: (error: Error) => void
}

export class SelfImClient implements ImClient {
  constructor(
    private readonly transportFactory: () => SelfTransport =
      () => new BrowserWebSocketTransport(),
    private readonly uploadImage: (file: File) => Promise<UploadedImage> = uploadChatImage,
    private readonly uploadVoice: (blob: Blob, durationMs: number) => Promise<UploadedVoice> =
      uploadChatVoice,
  ) {}

  readonly capabilities: ImCapabilities = {
    image: true,
    search: true,
    voice: true,
    readReceipt: true,
  }

  private bootstrap?: ImBootstrap
  private transport?: SelfTransport
  private listeners: ((event: ImEvent) => void)[] = []
  private pending = new Map<string, PendingSend>()
  private ackWaiters = new Map<string, () => void>()
  private authResolve?: () => void
  private authReject?: (error: Error) => void
  /** 登录超时定时器:auth_ok 到达后必须清掉,否则 5 秒后会对着已完成的 Promise 再 reject */
  private authTimer?: ReturnType<typeof setTimeout>
  /** 25s 业务心跳:与 App 对齐。服务端只认业务帧,WS 层 keep-alive 救不了(审查 N-1) */
  private heartbeat?: ReturnType<typeof setInterval>
  /** 握手是否已完成:未完成的失败由 login() 抛出,不重复报断线 */
  private authed = false
  /** 已被顶号/令牌过期:随后的 onclose 不能再报 disconnected(否则会被自动重连抢回来) */
  private suppressClose = false

  onEvent(listener: (event: ImEvent) => void): void {
    this.listeners.push(listener)
  }

  async init(bootstrap: ImBootstrap): Promise<void> {
    this.bootstrap = bootstrap
  }

  async login(userId: string, token: string): Promise<void> {
    void userId
    const bootstrap = this.bootstrap
    if (!bootstrap) throw new Error('IM 未初始化')
    // 重连时先关掉上一条连接,别让旧连接的定时器与 onclose 继续影响新连接。
    // 不 await:close() 只是发起关闭,等它会白白多一个微任务(旧连接通常已经断了)。
    const previous = this.transport
    this.transport = undefined
    void previous?.close().catch(() => {})
    this.stopHeartbeat()
    const transport = this.transportFactory()
    this.transport = transport
    this.authed = false
    this.suppressClose = false
    let closeHandled = false
    transport.onFrame((raw) => this.onFrame(raw))
    transport.onClose((info) => {
      if (closeHandled) return
      closeHandled = true
      this.onTransportClosed(info)
    })
    await transport.connect(bootstrap.wsUrl)

    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.authTimer = undefined
        reject(new Error('IM 登录超时'))
      }, 5000)
      this.authTimer = timer
      this.authResolve = () => {
        this.clearAuthTimer()
        resolve()
      }
      this.authReject = (error: Error) => {
        this.clearAuthTimer()
        reject(error)
      }
      transport.send(JSON.stringify({ v: 1, type: 'auth', data: { token } }))
    })
  }

  private clearAuthTimer(): void {
    if (this.authTimer) clearTimeout(this.authTimer)
    this.authTimer = undefined
  }

  private emit(event: ImEvent): void {
    for (const listener of this.listeners) listener(event)
  }

  /**
   * 连接被关闭(非本端主动):停心跳、让挂起的发送立刻失败,并上报 `disconnected`。
   *
   * 未完成握手时不上报 —— 那种失败由 `login()` 的 Promise 抛出,重连由调用方处理。
   */
  private onTransportClosed(info: { code: number; reason: string }): void {
    this.stopHeartbeat()
    if (this.suppressClose) {
      this.suppressClose = false
      return
    }
    const wasAuthed = this.authed
    this.authed = false
    if (!wasAuthed) return
    // 连接没了,挂起的发送永远等不到 ack:立刻失败,让 UI 出「重发」而不是干等 30 秒
    this.failPending(new Error('IM 连接已断开'))
    this.emit({ type: 'disconnected', code: info.code, reason: info.reason })
  }

  private failPending(error: Error): void {
    for (const pending of this.pending.values()) pending.reject(error)
    this.pending.clear()
    this.ackWaiters.clear()
  }

  private startHeartbeat(): void {
    this.stopHeartbeat()
    this.heartbeat = setInterval(() => {
      this.sendFrame(JSON.stringify({ v: 1, type: 'ping', data: {} }))
    }, 25_000)
  }

  private stopHeartbeat(): void {
    if (this.heartbeat) clearInterval(this.heartbeat)
    this.heartbeat = undefined
  }

  /** 发帧永不上抛:连接已断时静默丢弃,交给心跳/重连与发送超时兜底。 */
  private sendFrame(raw: string): void {
    try {
      this.transport?.send(raw)
    } catch {
      // 已关闭的 WebSocket 调 send 会抛 InvalidStateError,不能冒到 UI 层
    }
  }

  private onFrame(raw: string): void {
    let frame: Record<string, unknown>
    try {
      frame = JSON.parse(raw) as Record<string, unknown>
    } catch {
      return
    }
    const type = String(frame.type ?? '')
    const data = (frame.data ?? {}) as Record<string, unknown>
    if (type === 'auth_ok') {
      this.authed = true
      this.startHeartbeat()
      this.authResolve?.()
      this.authResolve = undefined
      return
    }
    if (type === 'kicked') {
      // 服务端随后会用 4001 关连接:那是被顶号,不是断线,不能让 store 自动重连
      this.suppressClose = true
      this.stopHeartbeat()
      this.emit({ type: 'kickedOffline', reason: 'multiAccount' })
      return
    }
    if (type === 'error') {
      const code = Number(data.code ?? 0)
      if (code === 40101) {
        this.suppressClose = true
        this.stopHeartbeat()
        this.authReject?.(new Error('IM 登录已过期'))
        this.emit({ type: 'kickedOffline', reason: 'sigExpired' })
        return
      }
      for (const pending of this.pending.values()) {
        pending.reject(new Error(String(data.message ?? 'IM 错误')))
      }
      this.pending.clear()
      return
    }
    if (type === 'ack') {
      const id = String(frame.id ?? '')
      const waiter = this.ackWaiters.get(id)
      if (waiter) {
        this.ackWaiters.delete(id)
        waiter()
      }
      const pending = this.pending.get(id)
      if (!pending) return
      this.pending.delete(id)
      const image = pending.image
      const voice = pending.voice
      const stickerId = pending.stickerId
      pending.resolve({
        msgId: String(data.msg_id ?? ''),
        peerId: pending.peerId,
        isSelf: true,
        seq: Number(data.seq ?? 0),
        timestamp: Number(data.ts ?? Date.now()),
        kind: stickerId
          ? ChatMessageKind.sticker
          : voice
            ? ChatMessageKind.voice
            : image
              ? ChatMessageKind.image
              : ChatMessageKind.text,
        text: pending.text,
        senderName: '',
        senderAvatar: null,
        isPending: false,
        isFailed: false,
        imageUrl: image ? image.thumb_url : null,
        imageLargeUrl: image ? image.url : null,
        voiceUrl: voice ? voice.url : null,
        voiceDurationMs: voice ? voice.duration_ms : 0,
        stickerId: stickerId ?? null,
        isRevoked: false,
      })
      return
    }
    if (type === 'message') {
      const message = messageFromJson(data, this.bootstrap?.imUserId ?? '')
      this.emit({ type: 'newMessage', message })
      this.emit({ type: 'conversationsChanged' })
      return
    }
    if (type === 'revoked') {
      this.emit({ type: 'messageRevoked', msgId: String(data.msg_id ?? '') })
      return
    }
    if (type === 'read') {
      // 对端读到哪(已读回执)。服务端主动推,不要求 ack。
      this.emit({
        type: 'peerRead',
        peerId: String(data.peer ?? ''),
        seq: Number(data.seq ?? 0),
      })
      return
    }
    if (type === 'self_read') {
      // **我**在另一台设备上读到哪(多端在线 K-3)。别和上面的 read 混:
      // 那个是「对端读我」,这个只清我这边的未读。
      this.emit({
        type: 'selfRead',
        peerId: String(data.peer ?? ''),
        seq: Number(data.seq ?? 0),
      })
      return
    }
    if (type === 'conversation_deleted') {
      // **我**在另一台设备上删了与 peer 的会话(K-3)。只发给本人的其他端。
      this.emit({ type: 'conversationDeleted', peerId: String(data.peer ?? '') })
      return
    }
    if (type === 'typing') {
      // 对端正在输入(批次 L-1)。可丢信号:没有 id、不用 ack、服务端不补发。
      this.emit({ type: 'typing', peerId: String(data.peer ?? '') })
    }
  }

  async logout(): Promise<void> {
    this.suppressClose = true
    this.authed = false
    this.stopHeartbeat()
    await this.transport?.close().catch(() => {})
    this.transport = undefined
  }

  async fetchConversations(): Promise<ImConversation[]> {
    const data = await this.get('/conversations', { limit: '100' })
    const items = (data.items ?? []) as Record<string, unknown>[]
    return items.map((item) => conversationFromJson(item, this.bootstrap?.imUserId ?? ''))
  }

  async fetchHistory(peerId: string, count = 50, beforeSeq?: number): Promise<ChatMessage[]> {
    const query: Record<string, string> = { peer: peerId, limit: String(count) }
    if (beforeSeq != null && beforeSeq > 0) query.before_seq = String(beforeSeq)
    const data = await this.get('/messages', query)
    const items = (data.items ?? []) as Record<string, unknown>[]
    return items.map((item) => messageFromJson(item, this.bootstrap?.imUserId ?? ''))
  }

  async searchMessages(keyword: string, limit = 20, beforeId?: string): Promise<ImSearchResult> {
    const query: Record<string, string> = { q: keyword, limit: String(limit) }
    if (beforeId) query.before_id = beforeId
    const data = await this.get('/search', query)
    const items = ((data.items ?? []) as Record<string, unknown>[]).map((item) => {
      const peer = (item.peer ?? {}) as Record<string, unknown>
      return {
        msgId: String(item.msg_id ?? ''),
        seq: Number(item.seq ?? 0),
        peerId: String(peer.id ?? ''),
        peerName: String(peer.nickname ?? ''),
        peerAvatar: (peer.avatar as string | null) ?? null,
        text: String(item.text ?? ''),
        timestamp: Number(item.ts ?? 0),
      }
    })
    return { items, hasMore: data.has_more === true }
  }

  async sendText(peerId: string, text: string, refMsgId?: number): Promise<ChatMessage> {
    const id = `local-${Date.now()}${Math.floor(Math.random() * 1000)}`
    for (let attempt = 0; attempt < 3; attempt++) {
      const promise = new Promise<ChatMessage>((resolve, reject) => {
        this.pending.set(id, { peerId, text, resolve, reject })
      })
      this.sendFrame(JSON.stringify({
        v: 1,
        type: 'send',
        id,
        // 引用(批次 L-2):**只上行 id**,被引用内容由服务端回库查后生成快照。
        data: { client_msg_id: id, to: peerId, kind: 'text', text, ...refField(refMsgId) },
      }))
      try {
        return await Promise.race([
          promise,
          new Promise<ChatMessage>((_, reject) =>
            setTimeout(() => reject(new Error('发送超时')), 10000)),
        ])
      } catch (error) {
        this.pending.delete(id)
        // 连接已断:再重试也发不出去,立刻把失败交给 UI(否则要连等 3 × 10 秒)
        if (!this.authed) throw error instanceof Error ? error : new Error('IM 连接已断开')
      }
    }
    throw new Error('发送失败,请重试')
  }

  async sendImage(peerId: string, file: File, refMsgId?: number): Promise<ChatMessage> {
    // 先上传到 Django 拿 URL,再发 WS 帧:帧里要带服务端校验过的地址
    const image = await this.uploadImage(file)
    const id = `local-${Date.now()}${Math.floor(Math.random() * 1000)}`
    for (let attempt = 0; attempt < 3; attempt++) {
      const promise = new Promise<ChatMessage>((resolve, reject) => {
        this.pending.set(id, { peerId, text: '', image, resolve, reject })
      })
      this.sendFrame(JSON.stringify({
        v: 1,
        type: 'send',
        id,
        data: {
          client_msg_id: id,
          to: peerId,
          kind: 'image',
          image: {
            url: image.url,
            thumb_url: image.thumb_url,
            width: image.width,
            height: image.height,
            size: image.size,
          },
          ...refField(refMsgId),
        },
      }))
      try {
        return await Promise.race([
          promise,
          new Promise<ChatMessage>((_, reject) =>
            setTimeout(() => reject(new Error('发送超时')), 10000)),
        ])
      } catch (error) {
        this.pending.delete(id)
        // 连接已断:再重试也发不出去,立刻把失败交给 UI(否则要连等 3 × 10 秒)
        if (!this.authed) throw error instanceof Error ? error : new Error('IM 连接已断开')
      }
    }
    throw new Error('发送失败,请重试')
  }

  async sendVoice(
    peerId: string,
    blob: Blob,
    durationMs: number,
    refMsgId?: number,
  ): Promise<ChatMessage> {
    // 先上传(Django 统一转 m4a 并校验时长),再发 WS 帧
    const voice = await this.uploadVoice(blob, durationMs)
    const id = `local-${Date.now()}${Math.floor(Math.random() * 1000)}`
    for (let attempt = 0; attempt < 3; attempt++) {
      const promise = new Promise<ChatMessage>((resolve, reject) => {
        this.pending.set(id, { peerId, text: '', voice, resolve, reject })
      })
      this.sendFrame(JSON.stringify({
        v: 1,
        type: 'send',
        id,
        data: {
          client_msg_id: id,
          to: peerId,
          kind: 'voice',
          voice: {
            url: voice.url,
            duration_ms: voice.duration_ms,
            size: voice.size,
          },
          ...refField(refMsgId),
        },
      }))
      try {
        return await Promise.race([
          promise,
          new Promise<ChatMessage>((_, reject) =>
            setTimeout(() => reject(new Error('发送超时')), 10000)),
        ])
      } catch (error) {
        this.pending.delete(id)
        // 连接已断:再重试也发不出去,立刻把失败交给 UI(否则要连等 3 × 10 秒)
        if (!this.authed) throw error instanceof Error ? error : new Error('IM 连接已断开')
      }
    }
    throw new Error('发送失败,请重试')
  }

  /**
   * 发贴纸(批次 J):复用 `kind=custom`,载荷只有 `{type:'sticker', id}`。
   *
   * 资源在客户端本地(`public/stickers/`),消息里不传图;服务端会校验 id 形状,
   * 不合法回 42201。
   */
  async sendSticker(peerId: string, stickerId: string, refMsgId?: number):
    Promise<ChatMessage> {
    const id = `local-${Date.now()}${Math.floor(Math.random() * 1000)}`
    for (let attempt = 0; attempt < 3; attempt++) {
      const promise = new Promise<ChatMessage>((resolve, reject) => {
        this.pending.set(id, { peerId, text: '', stickerId, resolve, reject })
      })
      this.sendFrame(JSON.stringify({
        v: 1,
        type: 'send',
        id,
        data: {
          client_msg_id: id,
          to: peerId,
          kind: 'custom',
          custom: { type: 'sticker', id: stickerId },
          ...refField(refMsgId),
        },
      }))
      try {
        return await Promise.race([
          promise,
          new Promise<ChatMessage>((_, reject) =>
            setTimeout(() => reject(new Error('发送超时')), 10000)),
        ])
      } catch (error) {
        this.pending.delete(id)
        // 连接已断:再重试也发不出去,立刻把失败交给 UI(否则要连等 3 × 10 秒)
        if (!this.authed) throw error instanceof Error ? error : new Error('IM 连接已断开')
      }
    }
    throw new Error('发送失败,请重试')
  }

  async deleteMessage(msgId: string): Promise<void> {
    void msgId
  }

  async revokeMessage(msgId: string): Promise<void> {
    const id = `revoke-${Date.now()}`
    const waiter = new Promise<void>((resolve) => this.ackWaiters.set(id, resolve))
    this.sendFrame(JSON.stringify({
      v: 1,
      type: 'revoke',
      id,
      data: { msg_id: msgId },
    }))
    await Promise.race([
      waiter,
      new Promise<void>((_, reject) =>
        setTimeout(() => reject(new Error('撤回失败')), 5000)),
    ])
  }

  async markConversationRead(peerId: string): Promise<void> {
    this.sendFrame(JSON.stringify({
      v: 1,
      type: 'read',
      id: `read-${Date.now()}`,
      data: { peer: peerId, seq: 0 },
    }))
  }

  async sendTyping(peerId: string): Promise<void> {
    // 上行 `typing`(批次 L-1):**没有 id、不等 ack**。服务端超限 / 未配对时静默
    // 丢弃,所以这里不登记 ackWaiter —— 登记了就会永远等不到回执。
    this.sendFrame(JSON.stringify({
      v: 1,
      type: 'typing',
      data: { to: peerId },
    }))
  }

  async deleteConversation(peerId: string): Promise<void> {
    this.sendFrame(JSON.stringify({
      v: 1,
      type: 'conversation_delete',
      id: `delete-${Date.now()}`,
      data: { peer: peerId },
    }))
  }

  /**
   * 写会话偏好(批次 N):`POST /im/api/conversations/flags`。
   *
   * **没传的那一项不上行** —— 服务端语义是「缺省 = 这一项不改」,传 `muted: undefined`
   * 会被 `JSON.stringify` 丢掉、传 `muted: false` 则是「取消免打扰」,两者不能混。
   */
  async setConversationFlags(
    peerId: string,
    flags: ImConversationFlags,
  ): Promise<ImConversationFlagsResult> {
    const body: Record<string, unknown> = { peer: peerId }
    if (flags.pinned !== undefined) body.pinned = flags.pinned
    if (flags.muted !== undefined) body.muted = flags.muted
    const data = await this.post('/conversations/flags', body)
    return { pinned: data.pinned === true, muted: data.muted === true }
  }

  private async get(path: string, query: Record<string, string>):
      Promise<Record<string, unknown>> {
    const bootstrap = this.bootstrap
    if (!bootstrap) throw new Error('IM 未初始化')
    const url = new URL(`${bootstrap.httpUrl}${path}`)
    for (const [key, value] of Object.entries(query)) {
      url.searchParams.set(key, value)
    }
    const response = await fetch(url.toString(), {
      headers: { Authorization: `Bearer ${bootstrap.token}` },
    })
    return await this.decode(response)
  }

  /**
   * POST 一个 JSON body(`/im/api/*` 的写路径)。
   *
   * Args:
   *   path: 相对 `http_url` 的路径,如 `/conversations/flags`。
   *   body: 请求体(会被 `JSON.stringify`)。
   *
   * Returns:
   *   响应 JSON 对象。
   */
  private async post(
    path: string,
    body: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const bootstrap = this.bootstrap
    if (!bootstrap) throw new Error('IM 未初始化')
    const response = await fetch(`${bootstrap.httpUrl}${path}`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${bootstrap.token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    })
    return await this.decode(response)
  }

  /**
   * 把 `/im/api/*` 的响应解成 JSON;非 2xx 时抛**统一** `ApiError`。
   *
   * 为什么不再抛 `new Error('IM HTTP 500')`:imserver 的错误体本来就是
   * `{"code":<业务码>,"message":"<中文>"}`,把业务码丢掉的话调用方没法分流
   * (`40401` 会话不存在要刷新列表、`42901` 要提示限流)。`ApiError` 是前端唯一的
   * 错误类型,`parseApiError` 遇到它原样透传,所以 UI 侧照旧只认一种错误。
   *
   * Args:
   *   response: `fetch` 的响应。
   *
   * Returns:
   *   解析后的 JSON 对象。
   *
   * Raises:
   *   ApiError: HTTP 非 2xx;`code` 取错误体里的业务码,缺失时退回 HTTP 状态码。
   */
  private async decode(response: Response): Promise<Record<string, unknown>> {
    if (!response.ok) throw await imHttpError(response)
    return (await response.json()) as Record<string, unknown>
  }
}

/**
 * 把 `/im/api/*` 的错误响应变成 `ApiError`。
 *
 * Args:
 *   response: 状态码非 2xx 的响应(imserver 的 body 形如 `{"code":40401,"message":"…"}`)。
 *
 * Returns:
 *   填好 `code` / `status` 的 `ApiError`,由调用方 `throw`。
 */
async function imHttpError(response: Response): Promise<ApiError> {
  const status = response.status
  let code = status
  let message = `IM HTTP ${status}`
  try {
    const body = (await response.json()) as Record<string, unknown>
    if (typeof body.code === 'number') code = body.code
    if (typeof body.message === 'string' && body.message) message = body.message
  } catch {
    // 非 JSON 错误体(nginx 502 之类的 HTML):保留 HTTP 状态码与兜底文案
  }
  return new ApiError(code, message, undefined, status)
}

/**
 * 上行帧里的引用字段(批次 L-2)。
 *
 * 单独抽出来是为了「没有引用时**完全不出现** `ref_msg_id` 键」:写
 * `ref_msg_id: undefined` 会被 `JSON.stringify` 丢掉,但显式展开更不容易看错。
 *
 * Args:
 *   refMsgId: 被引用消息 id;没有引用时是 undefined。
 *
 * Returns:
 *   带 `ref_msg_id` 的对象,或空对象。
 */
function refField(refMsgId?: number): Record<string, number> {
  return refMsgId === undefined ? {} : { ref_msg_id: refMsgId }
}
