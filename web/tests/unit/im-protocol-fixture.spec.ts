/**
 * 跨栈协议 fixture 契约测试(backlog E-2)。
 *
 * 用 Web 的**真实解析路径**吃 `imserver/tests/fixtures/ws/*.json`:
 * 下行帧断言产出的 `ImEvent`,上行帧断言客户端实际发出的 JSON 与 fixture 一致。
 * 服务端改了帧格式(或只改了 fixture)时这里会红,不再依赖人工手测。
 * 契约与改法见 `imserver/tests/fixtures/ws/README.md`。
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import { SelfImClient } from '@/im/self/client'
import type { SelfTransport } from '@/im/self/transport'
import type { ImBootstrap, ImEvent } from '@/im/types'

/** 假传输:只记录客户端发出的帧,并把测试注入的帧喂给客户端。 */
class FakeTransport implements SelfTransport {
  sent: string[] = []
  closed = 0
  private handler?: (raw: string) => void

  onFrame(fn: (raw: string) => void): void {
    this.handler = fn
  }

  /** 本测试不模拟服务端关连接,留空实现满足接口。 */
  onClose(): void {}

  async connect(): Promise<void> {}

  send(raw: string): void {
    this.sent.push(raw)
  }

  async close(): Promise<void> {
    this.closed += 1
  }

  /** 模拟服务端下发一帧。 */
  emit(raw: string): void {
    this.handler?.(raw)
  }
}

interface FixtureFrame {
  name: string
  frame: Record<string, unknown>
}

interface FixtureDocument {
  protocol_version: number
  frames: FixtureFrame[]
}

const bootstrap: ImBootstrap = {
  token: 'tok',
  wsUrl: 'ws://test/im/ws',
  httpUrl: 'http://test/im/api',
  imUserId: 'u9',
}

/** 读取仓库里共享的协议 fixture。 */
function loadFixture(name: string): FixtureDocument {
  // 不用 `new URL(..., import.meta.url)`:Vite 会把这种写法当静态资源导入,
  // 而 fixture 在 web/ 根目录之外(会被 fs.allow 拒绝)。直接用文件系统路径。
  const here = dirname(fileURLToPath(import.meta.url))
  const path = resolve(here, '../../..', 'imserver/tests/fixtures/ws', name)
  return JSON.parse(readFileSync(path, 'utf-8')) as FixtureDocument
}

/** 按名字取 fixture 里的一帧。 */
function frameOf(document: FixtureDocument, name: string): Record<string, unknown> {
  const hit = document.frames.find((item) => item.name === name)
  if (!hit) throw new Error(`fixture 里没有帧:${name}`)
  return hit.frame
}

/**
 * 把客户端实际发出的帧与 fixture 逐字段比对。
 *
 * 客户端会生成动态 id(`local-…` / `read-…`),比对前把 id 与 `client_msg_id`
 * 归一化成 fixture 里的值;其余字段必须完全一致。
 */
function expectFrameMatches(
  actual: Record<string, unknown>,
  fixture: Record<string, unknown>,
): void {
  const normalized = JSON.parse(JSON.stringify(actual)) as Record<string, unknown>
  normalized.id = fixture.id
  const data = normalized.data as Record<string, unknown>
  if ('client_msg_id' in data) {
    data.client_msg_id = (fixture.data as Record<string, unknown>).client_msg_id
  }
  expect(normalized).toEqual(fixture)
}

/** 登录并返回已就绪的客户端、假传输与事件收集器。 */
async function loginClient(options: { uploader?: boolean } = {}): Promise<{
  client: SelfImClient
  transport: FakeTransport
  events: ImEvent[]
}> {
  const transport = new FakeTransport()
  const client = new SelfImClient(
    () => transport,
    options.uploader
      ? async () => ({
          id: 1,
          url: 'http://cdn/media/chat/a.jpg',
          thumb_url: 'http://cdn/media/chat/a_thumb.jpg',
          width: 1080,
          height: 1440,
          size: 345678,
        })
      : undefined,
    options.uploader
      ? async () => ({
          id: 2,
          url: 'http://cdn/media/chat/v.m4a',
          duration_ms: 3200,
          size: 12345,
        })
      : undefined,
  )
  const events: ImEvent[] = []
  client.onEvent((event) => events.push(event))
  await client.init(bootstrap)
  const login = client.login('u9', 'tok')
  await Promise.resolve()
  transport.emit(
    JSON.stringify(frameOf(loadFixture('server_to_client.json'), 'auth_ok')),
  )
  await login
  await Promise.resolve()
  return { client, transport, events }
}

/** 让出微任务队列,等客户端把帧发出去。 */
async function flush(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0))
}

describe('IM 协议 fixture', () => {
  it('下行 fixture:消息与事件模型符合契约', async () => {
    const server = loadFixture('server_to_client.json')
    const { client, transport, events } = await loginClient()

    transport.emit(JSON.stringify(frameOf(server, 'message_text')))
    await flush()
    const text = events.find((event) => event.type === 'newMessage')
    if (text?.type !== 'newMessage') throw new Error('没有收到 newMessage')
    expect(text.message.msgId).toBe('900124')
    expect(text.message.seq).toBe(42)
    expect(text.message.text).toBe('你好')
    expect(text.message.peerId).toBe('u2')
    expect(text.message.isSelf).toBe(false)
    expect(text.message.timestamp).toBe(1720000000000)
    expect(text.message.kind).toBe('text')
    expect(text.message.senderName).toBe('小九')
    expect(text.message.senderAvatar).toBe('http://cdn/avatar/u2.jpg')

    events.length = 0
    transport.emit(JSON.stringify(frameOf(server, 'message_image')))
    await flush()
    const image = events.find((event) => event.type === 'newMessage')
    if (image?.type !== 'newMessage') throw new Error('没有收到图片消息')
    expect(image.message.kind).toBe('image')
    expect(image.message.imageUrl).toBe('http://cdn/media/chat/a_thumb.jpg')
    expect(image.message.imageLargeUrl).toBe('http://cdn/media/chat/a.jpg')

    events.length = 0
    transport.emit(JSON.stringify(frameOf(server, 'message_voice')))
    await flush()
    const voice = events.find((event) => event.type === 'newMessage')
    if (voice?.type !== 'newMessage') throw new Error('没有收到语音消息')
    expect(voice.message.kind).toBe('voice')
    expect(voice.message.voiceUrl).toBe('http://cdn/media/chat/v.m4a')
    expect(voice.message.voiceDurationMs).toBe(3200)

    events.length = 0
    transport.emit(JSON.stringify(frameOf(server, 'read_down')))
    await flush()
    expect(events).toContainEqual({ type: 'peerRead', peerId: 'u2', seq: 42 })

    events.length = 0
    transport.emit(JSON.stringify(frameOf(server, 'revoked')))
    await flush()
    expect(events).toContainEqual({ type: 'messageRevoked', msgId: '900124' })

    events.length = 0
    transport.emit(JSON.stringify(frameOf(server, 'pong')))
    transport.emit(JSON.stringify(frameOf(server, 'error_42201')))
    await flush()
    expect(events).toEqual([])

    await client.logout()
  })

  it('终止类下行帧:error 40101 → 令牌过期,kicked → 被顶下线', async () => {
    const server = loadFixture('server_to_client.json')

    const expired = await loginClient()
    expired.events.length = 0
    expired.transport.emit(JSON.stringify(frameOf(server, 'error_40101')))
    await flush()
    expect(expired.events).toContainEqual({
      type: 'kickedOffline',
      reason: 'sigExpired',
    })
    await expired.client.logout()

    const kicked = await loginClient()
    kicked.events.length = 0
    kicked.transport.emit(JSON.stringify(frameOf(server, 'kicked')))
    await flush()
    expect(kicked.events).toContainEqual({
      type: 'kickedOffline',
      reason: 'multiAccount',
    })
    await kicked.client.logout()
  })

  it('上行 fixture:客户端发出的帧与契约一致', async () => {
    const server = loadFixture('server_to_client.json')
    const clientToServer = loadFixture('client_to_server.json')
    const { client, transport } = await loginClient({ uploader: true })

    // auth:登录首帧(动态部分是 token,换成测试令牌后逐字段比对)
    const auth = JSON.parse(transport.sent[0]) as Record<string, unknown>
    const expectedAuth = JSON.parse(
      JSON.stringify(frameOf(clientToServer, 'auth')),
    ) as Record<string, unknown>
    ;(expectedAuth.data as Record<string, unknown>).token = 'tok'
    expect(auth).toEqual(expectedAuth)

    // send_text
    const sendingText = client.sendText('u2', '你好')
    await flush()
    const sendText = JSON.parse(transport.sent[transport.sent.length - 1]) as Record<
      string,
      unknown
    >
    expectFrameMatches(sendText, frameOf(clientToServer, 'send_text'))
    const textAck = JSON.parse(JSON.stringify(frameOf(server, 'ack_send'))) as Record<
      string,
      unknown
    >
    textAck.id = sendText.id
    transport.emit(JSON.stringify(textAck))
    const textMessage = await sendingText
    expect(textMessage.msgId).toBe('900124')
    expect(textMessage.seq).toBe(42)

    // send_image
    const file = new File([new Uint8Array([1])], 'a.jpg', { type: 'image/jpeg' })
    const sendingImage = client.sendImage('u2', file)
    await flush()
    const sendImage = JSON.parse(transport.sent[transport.sent.length - 1]) as Record<
      string,
      unknown
    >
    expectFrameMatches(sendImage, frameOf(clientToServer, 'send_image'))
    const imageAck = JSON.parse(JSON.stringify(frameOf(server, 'ack_send'))) as Record<
      string,
      unknown
    >
    imageAck.id = sendImage.id
    transport.emit(JSON.stringify(imageAck))
    await sendingImage

    // send_voice
    const sendingVoice = client.sendVoice('u2', new Blob([new Uint8Array([1])]), 3200)
    await flush()
    const sendVoice = JSON.parse(transport.sent[transport.sent.length - 1]) as Record<
      string,
      unknown
    >
    expectFrameMatches(sendVoice, frameOf(clientToServer, 'send_voice'))
    const voiceAck = JSON.parse(JSON.stringify(frameOf(server, 'ack_send'))) as Record<
      string,
      unknown
    >
    voiceAck.id = sendVoice.id
    transport.emit(JSON.stringify(voiceAck))
    await sendingVoice

    // read
    await client.markConversationRead('u2')
    expectFrameMatches(
      JSON.parse(transport.sent[transport.sent.length - 1]) as Record<string, unknown>,
      frameOf(clientToServer, 'read'),
    )

    // revoke:等 ack_ok 才返回
    const revoking = client.revokeMessage('900123')
    await flush()
    const revoke = JSON.parse(transport.sent[transport.sent.length - 1]) as Record<
      string,
      unknown
    >
    expectFrameMatches(revoke, frameOf(clientToServer, 'revoke'))
    const revokeAck = JSON.parse(JSON.stringify(frameOf(server, 'ack_ok'))) as Record<
      string,
      unknown
    >
    revokeAck.id = revoke.id
    transport.emit(JSON.stringify(revokeAck))
    await revoking

    // conversation_delete
    await client.deleteConversation('u2')
    expectFrameMatches(
      JSON.parse(transport.sent[transport.sent.length - 1]) as Record<string, unknown>,
      frameOf(clientToServer, 'conversation_delete'),
    )

    await client.logout()
  })
})
