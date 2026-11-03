import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  createReporter,
  currentRequestId,
  describeError,
  errorReportingEnabled,
  installClientErrorReporting,
  postClientError,
  rememberRequestId,
  type ClientErrorReport,
} from '@/api/clientErrors'

function collector() {
  const sent: ClientErrorReport[] = []
  const sender = vi.fn(async (report: ClientErrorReport) => {
    sent.push(report)
  })
  return { sender, sent }
}

describe('clientErrors', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('默认关闭:环境变量不是 1 时不上报', () => {
    vi.stubEnv('VITE_ERROR_REPORTING', '0')
    expect(errorReportingEnabled()).toBe(false)

    const { sender } = collector()
    const installed = installClientErrorReporting({ sender })
    installed.report(new Error('boom'))

    expect(sender).not.toHaveBeenCalled()
  })

  it('环境变量为 1 时开启', () => {
    vi.stubEnv('VITE_ERROR_REPORTING', '1')
    expect(errorReportingEnabled()).toBe(true)
  })

  it('window.onerror 会带着 platform/stack 上报', () => {
    const { sender, sent } = collector()
    const target = new EventTarget()
    installClientErrorReporting({
      enabled: true,
      sender,
      appVersion: '1.0.2',
      target: target as unknown as Window,
    })

    target.dispatchEvent(
      new ErrorEvent('error', {
        message: 'Cannot read properties of undefined',
        error: new Error('Cannot read properties of undefined'),
      }),
    )

    expect(sender).toHaveBeenCalledTimes(1)
    expect(sent[0]).toMatchObject({
      platform: 'web',
      message: 'Error: Cannot read properties of undefined',
      app_version: '1.0.2',
    })
    expect(sent[0].stack).toContain('Error')
  })

  it('unhandledrejection 也会上报', () => {
    const { sender, sent } = collector()
    const target = new EventTarget()
    installClientErrorReporting({ enabled: true, sender, target: target as unknown as Window })

    const event = new Event('unhandledrejection')
    Object.defineProperty(event, 'reason', { value: new Error('promise 挂了') })
    target.dispatchEvent(event)

    expect(sender).toHaveBeenCalledTimes(1)
    expect(sent[0].message).toBe('Error: promise 挂了')
  })

  it('dispose 之后不再上报(避免测试/热更新残留监听)', () => {
    const { sender } = collector()
    const target = new EventTarget()
    const installed = installClientErrorReporting({
      enabled: true,
      sender,
      target: target as unknown as Window,
    })

    installed.dispose()
    target.dispatchEvent(new ErrorEvent('error', { message: 'x', error: new Error('x') }))

    expect(sender).not.toHaveBeenCalled()
  })

  it('同一 message + 路由只报一次,且总数封顶 20 条', () => {
    const { sender } = collector()
    const reporter = createReporter(sender, '1.0.2')

    reporter.report(new Error('同一个错'), { route: '/chats/u9' })
    reporter.report(new Error('同一个错'), { route: '/chats/u9' })
    expect(sender).toHaveBeenCalledTimes(1) // 去重

    for (let index = 0; index < 50; index++) {
      reporter.report(new Error(`错 ${index}`), { route: '/feed' })
    }
    expect(sender).toHaveBeenCalledTimes(20) // 配额
    expect(reporter.sent).toBe(20)
  })

  it('上报时带上最近一次服务端 X-Request-Id,前后端日志能对上', () => {
    const { sender, sent } = collector()
    rememberRequestId('9f8c1b2e4d5a')
    expect(currentRequestId()).toBe('9f8c1b2e4d5a')

    createReporter(sender).report(new Error('boom'), { route: '/login' })

    expect(sent[0].request_id).toBe('9f8c1b2e4d5a')
  })

  it('超长 message / stack 会被截断(后端有 500 / 8000 字上限)', () => {
    const { sender, sent } = collector()
    createReporter(sender).report(new Error('x'.repeat(2000)), {
      route: '/feed',
      stack: 'y'.repeat(9000),
    })

    expect(sent[0].message.length).toBeLessThanOrEqual(480)
    expect(sent[0].stack!.length).toBeLessThanOrEqual(4000)
  })

  it('describeError 不产出 [object Object]', () => {
    expect(describeError(new TypeError('bad'))).toBe('TypeError: bad')
    expect(describeError('纯字符串')).toBe('纯字符串')
    expect(describeError({ message: '带 message 的对象' })).toBe('带 message 的对象')
    expect(describeError({ a: 1 })).toBe('{"a":1}')
  })

  it('默认发送器 POST 到 /api/v1/client-errors 且 keepalive', async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    await postClientError({ platform: 'web', message: 'boom' })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/client-errors')
    expect(init.method).toBe('POST')
    expect(init.keepalive).toBe(true)
    expect(JSON.parse(String(init.body))).toMatchObject({ platform: 'web', message: 'boom' })
  })

  it('发送失败不会把异常抛给调用方', async () => {
    const failing = vi.fn(async () => Promise.reject(new Error('network down')))
    const reporter = createReporter(failing)

    expect(() => reporter.report(new Error('boom'), { route: '/feed' })).not.toThrow()
    await Promise.resolve()
  })
})
