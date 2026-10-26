import { describe, expect, it } from 'vitest'
import { SelfImClient } from '@/im/self/client'
import { messageFromJson } from '@/im/self/map'
import type { SelfTransport } from '@/im/self/transport'
import type { ImBootstrap } from '@/im/types'

class FakeTransport implements SelfTransport {
  sent: string[] = []
  private handler?: (raw: string) => void

  onFrame(fn: (raw: string) => void): void {
    this.handler = fn
  }

  async connect(): Promise<void> {}

  send(raw: string): void {
    this.sent.push(raw)
  }

  async close(): Promise<void> {}

  emit(raw: string): void {
    this.handler?.(raw)
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
    expect(message.imageUrl).toBe('http://cdn/b_thumb.jpg')
    expect(message.imageLargeUrl).toBe('http://cdn/b.jpg')
  })
})