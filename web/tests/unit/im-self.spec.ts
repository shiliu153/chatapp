import { describe, expect, it, vi } from 'vitest'
import { SelfImClient } from '@/im/self/client'
import { messageFromJson } from '@/im/self/map'
import type { SelfTransport } from '@/im/self/transport'
import type { ImBootstrap, ImEvent } from '@/im/types'

class FakeTransport implements SelfTransport {
  sent: string[] = []
  closed = 0
  private handler?: (raw: string) => void
  private closeHandler?: (info: { code: number; reason: string }) => void

  onFrame(fn: (raw: string) => void): void {
    this.handler = fn
  }

  onClose(fn: (info: { code: number; reason: string }) => void): void {
    this.closeHandler = fn
  }

  async connect(): Promise<void> {}

  send(raw: string): void {
    this.sent.push(raw)
  }

  async close(): Promise<void> {
    this.closed += 1
  }

  emit(raw: string): void {
    this.handler?.(raw)
  }

  /** 模拟服务端关连接(75s 空闲踢出 / 网络中断) */
  emitClose(code = 1000, reason = ''): void {
    this.closeHandler?.({ code, reason })
  }
}

const bootstrap: ImBootstrap = {
  backend: 'self',
  sdkAppId: 0,
  token: 'tok',
  wsUrl: 'ws://test/im/ws',
  httpUrl: 'http://test/im/api',
  imUserId: 'u9',
}

describe('SelfImClient', () => {
  it('logs in with first-frame auth and resolves send on ack', async () => {
    const transport = new FakeTransport()
    const client = new SelfImClient(() => transport)
    await client.init(bootstrap)

    const login = client.login('u9', 'tok')
    await Promise.resolve()
    expect(transport.sent[0]).toContain('"type":"auth"')
    transport.emit('{"v":1,"type":"auth_ok","data":{"uid":9}}')
    await login
    expect(client.capabilities.image).toBe(true)

    const sending = client.sendText('u2', 'hi')
    await Promise.resolve()
    const frame = JSON.parse(transport.sent[transport.sent.length - 1])
    transport.emit(JSON.stringify({
      v: 1,
      type: 'ack',
      id: frame.id,
      data: { msg_id: '100', seq: 1, ts: 1 },
    }))
    const message = await sending
    expect(message.msgId).toBe('100')
    expect(message.text).toBe('hi')
  })

  it('sendImage 先上传再发 image 帧,ack 后返回图片消息', async () => {
    const transport = new FakeTransport()
    const uploads: File[] = []
    const client = new SelfImClient(() => transport, async (file: File) => {
      uploads.push(file)
      return {
        id: 1,
        url: 'http://cdn/media/chat/a.jpg',
        thumb_url: 'http://cdn/media/chat/a_thumb.jpg',
        width: 1080,
        height: 1440,
        size: 345678,
      }
    })
    await client.init(bootstrap)
    const login = client.login('u9', 'tok')
    await new Promise((resolve) => setTimeout(resolve, 0))
    transport.emit('{"v":1,"type":"auth_ok","data":{"uid":9}}')
    await login

    const file = new File([new Uint8Array([1])], 'a.jpg', { type: 'image/jpeg' })
    const pending = client.sendImage('u2', file)
    await new Promise((resolve) => setTimeout(resolve, 0))
    const frame = JSON.parse(transport.sent[transport.sent.length - 1])
    expect(frame.data.kind).toBe('image')
    expect(frame.data.image.thumb_url).toBe('http://cdn/media/chat/a_thumb.jpg')

    transport.emit(JSON.stringify({
      v: 1, type: 'ack', id: frame.id, data: { msg_id: '42', seq: 1, ts: 1700000000000 },
    }))
    const message = await pending
    expect(message.kind).toBe('image')
    expect(message.imageUrl).toBe('http://cdn/media/chat/a_thumb.jpg')
    expect(message.imageLargeUrl).toBe('http://cdn/media/chat/a.jpg')
    expect(uploads).toHaveLength(1)
  })

  it('解析收到的 image 消息', () => {
    const message = messageFromJson({
      msg_id: '7', seq: 2, from: 'u2', to: 'u9', kind: 'image', ts: 1, revoked: false,
      image: {
        url: 'http://cdn/b.jpg',
        thumb_url: 'http://cdn/b_thumb.jpg',
        width: 10,
        height: 20,
        size: 100,
      },
    }, 'u9')
    expect(message.kind).toBe('image')
    expect(message.seq).toBe(2)
    expect(message.imageUrl).toBe('http://cdn/b_thumb.jpg')
    expect(message.imageLargeUrl).toBe('http://cdn/b.jpg')
  })

  it('每 25 秒发一次业务 ping(与 App 对齐,防服务端 75s 空闲踢出)', async () => {
    vi.useFakeTimers()
    try {
      const transport = new FakeTransport()
      const client = new SelfImClient(() => transport)
      await client.init(bootstrap)
      const login = client.login('u9', 'tok')
      await vi.advanceTimersByTimeAsync(0)
      transport.emit('{"v":1,"type":"auth_ok","data":{"uid":9}}')
      await login

      const before = transport.sent.length
      await vi.advanceTimersByTimeAsync(25_000)
      expect(transport.sent.slice(before).some((raw) => raw.includes('"type":"ping"'))).toBe(true)

      await vi.advanceTimersByTimeAsync(25_000)
      const pings = transport.sent.filter((raw) => raw.includes('"type":"ping"'))
      expect(pings).toHaveLength(2)
      expect(JSON.parse(pings[0])).toEqual({ v: 1, type: 'ping', data: {} })

      await client.logout()
      const afterLogout = transport.sent.length
      await vi.advanceTimersByTimeAsync(60_000)
      expect(transport.sent.length).toBe(afterLogout) // 退出后不再发心跳
    } finally {
      vi.useRealTimers()
    }
  })

  it('连接被关闭时发出独立的 disconnected 事件(不冒充 kickedOffline)', async () => {
    const transport = new FakeTransport()
    const client = new SelfImClient(() => transport)
    const events: ImEvent[] = []
    client.onEvent((event) => events.push(event))
    await client.init(bootstrap)
    const login = client.login('u9', 'tok')
    await new Promise((resolve) => setTimeout(resolve, 0))
    transport.emit('{"v":1,"type":"auth_ok","data":{"uid":9}}')
    await login

    transport.emitClose(1000, 'idle')

    expect(events.map((event) => event.type)).toEqual(['disconnected'])
  })

  it('被顶(kicked)后连接关闭不再补发 disconnected(否则会被自动重连抢回来)', async () => {
    const transport = new FakeTransport()
    const client = new SelfImClient(() => transport)
    const events: ImEvent[] = []
    client.onEvent((event) => events.push(event))
    await client.init(bootstrap)
    const login = client.login('u9', 'tok')
    await new Promise((resolve) => setTimeout(resolve, 0))
    transport.emit('{"v":1,"type":"auth_ok","data":{"uid":9}}')
    await login

    transport.emit('{"v":1,"type":"kicked","data":{"reason":"multiAccount"}}')
    transport.emitClose(4001, '')

    expect(events.map((event) => event.type)).toEqual(['kickedOffline'])
  })

  it('断线时挂起的发送立即失败,不干等 10 秒 × 3 次', async () => {
    const transport = new FakeTransport()
    const client = new SelfImClient(() => transport)
    await client.init(bootstrap)
    const login = client.login('u9', 'tok')
    await new Promise((resolve) => setTimeout(resolve, 0))
    transport.emit('{"v":1,"type":"auth_ok","data":{"uid":9}}')
    await login

    const sending = client.sendText('u2', 'hi')
    await new Promise((resolve) => setTimeout(resolve, 0))
    transport.emitClose(1000, '')

    await expect(sending).rejects.toThrow('连接已断开')
  })

  it('searchMessages 调 /search 并映射 ImSearchHit', async () => {
    const requests: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      requests.push(String(input))
      return new Response(JSON.stringify({
        items: [
          {
            msg_id: '42', seq: 7, from: 'u2', to: 'u9', ts: 1761465600000,
            kind: 'text', text: '晚上吃火锅吗',
            peer: { id: 'u2', nickname: '阿九', avatar: 'https://a/9.png' },
          },
        ],
        has_more: true,
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))
    try {
      const client = new SelfImClient()
      await client.init(bootstrap)
      const result = await client.searchMessages('火锅', 10, '99')
      expect(requests[0]).toContain('/im/api/search?')
      expect(requests[0]).toContain('q=%E7%81%AB%E9%94%85')
      expect(requests[0]).toContain('limit=10')
      expect(requests[0]).toContain('before_id=99')
      expect(result.items).toHaveLength(1)
      expect(result.items[0]).toMatchObject({
        msgId: '42', seq: 7, peerId: 'u2', peerName: '阿九',
        peerAvatar: 'https://a/9.png', text: '晚上吃火锅吗',
      })
      expect(result.hasMore).toBe(true)
      expect(client.capabilities.search).toBe(true)
    } finally {
      vi.unstubAllGlobals()
    }
  })
})