import {
  ChatMessageKind,
  type ChatMessage,
  type ImBootstrap,
  type ImCapabilities,
  type ImClient,
  type ImConversation,
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

  readonly capabilities: ImCapabilities = { image: true, search: true, voice: true }

  private bootstrap?: ImBootstrap
  private transport?: SelfTransport
  private listeners: ((event: ImEvent) => void)[] = []
  private pending = new Map<string, PendingSend>()
  private ackWaiters = new Map<string, () => void>()
  private authResolve?: () => void
  private authReject?: (error: Error) => void

  onEvent(listener: (event: ImEvent) => void): void {
    this.listeners.push(listener)
  }

  async init(bootstrap: ImBootstrap): Promise<void> {
    this.bootstrap = bootstrap
  }

  async login(userId: string, userSig: string): Promise<void> {
    void userId
    const bootstrap = this.bootstrap
    if (!bootstrap) throw new Error('IM 未初始化')
    const transport = this.transportFactory()
    this.transport = transport
    transport.onFrame((raw) => this.onFrame(raw))
    await transport.connect(bootstrap.wsUrl)

    await new Promise<void>((resolve, reject) => {
      this.authResolve = resolve
      this.authReject = reject
      transport.send(JSON.stringify({ v: 1, type: 'auth', data: { token: userSig } }))
      setTimeout(() => reject(new Error('IM 登录超时')), 5000)
    })
  }

  private emit(event: ImEvent): void {
    for (const listener of this.listeners) listener(event)
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
      this.authResolve?.()
      this.authResolve = undefined
      return
    }
    if (type === 'kicked') {
      this.emit({ type: 'kickedOffline', reason: 'multiAccount' })
      return
    }
    if (type === 'error') {
      const code = Number(data.code ?? 0)
      if (code === 40101) {
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
      pending.resolve({
        msgId: String(data.msg_id ?? ''),
        peerId: pending.peerId,
        isSelf: true,
        seq: Number(data.seq ?? 0),
        timestamp: Number(data.ts ?? Date.now()),
        kind: voice
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
    }
  }

  async logout(): Promise<void> {
    await this.transport?.close()
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

  async sendText(peerId: string, text: string): Promise<ChatMessage> {
    const id = `local-${Date.now()}${Math.floor(Math.random() * 1000)}`
    for (let attempt = 0; attempt < 3; attempt++) {
      const promise = new Promise<ChatMessage>((resolve, reject) => {
        this.pending.set(id, { peerId, text, resolve, reject })
      })
      this.transport?.send(JSON.stringify({
        v: 1,
        type: 'send',
        id,
        data: { client_msg_id: id, to: peerId, kind: 'text', text },
      }))
      try {
        return await Promise.race([
          promise,
          new Promise<ChatMessage>((_, reject) =>
            setTimeout(() => reject(new Error('发送超时')), 10000)),
        ])
      } catch {
        this.pending.delete(id)
      }
    }
    throw new Error('发送失败,请重试')
  }

  async sendImage(peerId: string, file: File): Promise<ChatMessage> {
    // 先上传到 Django 拿 URL,再发 WS 帧:帧里要带服务端校验过的地址
    const image = await this.uploadImage(file)
    const id = `local-${Date.now()}${Math.floor(Math.random() * 1000)}`
    for (let attempt = 0; attempt < 3; attempt++) {
      const promise = new Promise<ChatMessage>((resolve, reject) => {
        this.pending.set(id, { peerId, text: '', image, resolve, reject })
      })
      this.transport?.send(JSON.stringify({
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
        },
      }))
      try {
        return await Promise.race([
          promise,
          new Promise<ChatMessage>((_, reject) =>
            setTimeout(() => reject(new Error('发送超时')), 10000)),
        ])
      } catch {
        this.pending.delete(id)
      }
    }
    throw new Error('发送失败,请重试')
  }

  async sendVoice(peerId: string, blob: Blob, durationMs: number): Promise<ChatMessage> {
    // 先上传(Django 统一转 m4a 并校验时长),再发 WS 帧
    const voice = await this.uploadVoice(blob, durationMs)
    const id = `local-${Date.now()}${Math.floor(Math.random() * 1000)}`
    for (let attempt = 0; attempt < 3; attempt++) {
      const promise = new Promise<ChatMessage>((resolve, reject) => {
        this.pending.set(id, { peerId, text: '', voice, resolve, reject })
      })
      this.transport?.send(JSON.stringify({
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
        },
      }))
      try {
        return await Promise.race([
          promise,
          new Promise<ChatMessage>((_, reject) =>
            setTimeout(() => reject(new Error('发送超时')), 10000)),
        ])
      } catch {
        this.pending.delete(id)
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
    this.transport?.send(JSON.stringify({
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
    this.transport?.send(JSON.stringify({
      v: 1,
      type: 'read',
      id: `read-${Date.now()}`,
      data: { peer: peerId, seq: 0 },
    }))
  }

  async deleteConversation(peerId: string): Promise<void> {
    this.transport?.send(JSON.stringify({
      v: 1,
      type: 'conversation_delete',
      id: `delete-${Date.now()}`,
      data: { peer: peerId },
    }))
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
    if (!response.ok) throw new Error(`IM HTTP ${response.status}`)
    return (await response.json()) as Record<string, unknown>
  }
}
