import { describe, expect, it } from 'vitest'
import { SelfImClient } from '@/im/self/client'
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
    expect(client.capabilities.image).toBe(false)

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
})
