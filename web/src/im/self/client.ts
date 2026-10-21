import {
  ChatMessageKind,
  type ChatMessage,
  type ImBootstrap,
  type ImCapabilities,
  type ImClient,
  type ImConversation,
  type ImEvent,
} from '../types'
import { conversationFromJson, messageFromJson } from './map'
import { BrowserWebSocketTransport, type SelfTransport } from './transport'

interface PendingSend {
  peerId: string
  text: string
  resolve: (message: ChatMessage) => void
  reject: (error: Error) => void
}

export class SelfImClient implements ImClient {
  constructor(private readonly transportFactory: () => SelfTransport =
      () => new BrowserWebSocketTransport()) {}

  readonly capabilities: ImCapabilities = { image: false }

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
      pending.resolve({
        msgId: String(data.msg_id ?? ''),
        peerId: pending.peerId,
        isSelf: true,
        timestamp: Number(data.ts ?? Date.now()),
        kind: ChatMessageKind.text,
        text: pending.text,
        senderName: '',
        senderAvatar: null,
        isPending: false,
        isFailed: false,
        imageUrl: null,
        imageLargeUrl: null,
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

  async fetchHistory(peerId: string, count = 50): Promise<ChatMessage[]> {
    const data = await this.get('/messages', { peer: peerId, limit: String(count) })
    const items = (data.items ?? []) as Record<string, unknown>[]
    return items.map((item) => messageFromJson(item, this.bootstrap?.imUserId ?? ''))
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
    void peerId
    void file
    throw new Error('当前聊天服务暂不支持图片')
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
