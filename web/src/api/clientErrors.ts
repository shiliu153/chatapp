/**
 * 前端错误上报(自建端点,零第三方成本)。
 *
 * 为什么需要:服务端 Prometheus 只看得见自己返回的 5xx;白屏、JS 运行时异常、
 * 组件渲染报错全都发生在浏览器里,用户不刷新就没人知道(审查 N-7)。
 *
 * 设计要点:
 * 1. **上报是 fire-and-forget**:任何失败都静默丢弃,绝不影响用户流程;
 * 2. **开关走环境变量**(`VITE_ERROR_REPORTING`),本地与测试默认关 —— 否则开发时
 *    每改一行代码都会往生产日志里灌垃圾;
 * 3. **带 `request_id`**:后端每个响应都有 `X-Request-Id`,上报时一并带上,
 *    前后端日志就能按同一个 id 对上;
 * 4. **有配额与去重**:单个页面生命周期内最多上报 20 条,同一 message+路由只报一次 ——
 *    渲染循环里抛异常时,一秒能抛几百次,不限流等于自己 DDoS 自己。
 */

const ENDPOINT = '/api/v1/client-errors'
/** 单页面生命周期内的上报上限 */
const MAX_REPORTS = 20
/** 与后端序列化器的上限对齐(超了会被 400 拒掉) */
const MAX_MESSAGE = 480
const MAX_STACK = 4000
const MAX_ROUTE = 180

export interface ClientErrorReport {
  platform: 'web'
  message: string
  stack?: string
  route?: string
  app_version?: string
  request_id?: string
}

/** 真正发请求的函数;测试注入假实现。 */
export type ClientErrorSender = (report: ClientErrorReport) => Promise<void>

/** 最近一次拿到的服务端追踪 ID(来自响应头 `X-Request-Id`)。 */
let lastRequestId = ''

/** 记下服务端追踪 ID(由 http 拦截器在每次响应时调用)。 */
export function rememberRequestId(id: string | null | undefined): void {
  if (id) lastRequestId = id
}

/** 取最近一次的服务端追踪 ID;没有则为空串。 */
export function currentRequestId(): string {
  return lastRequestId
}

/** 上报开关:构建期环境变量,默认关。 */
export function errorReportingEnabled(): boolean {
  return import.meta.env.VITE_ERROR_REPORTING === '1'
}

/** 默认发送器:同源 POST,`keepalive` 让白屏跳转时的请求也能发出去。 */
export async function postClientError(report: ClientErrorReport): Promise<void> {
  await fetch(ENDPOINT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Client': 'web' },
    body: JSON.stringify(report),
    credentials: 'include',
    keepalive: true,
  })
}

/** 把任意抛出物转成一行可读的摘要(不上报 `[object Object]`)。 */
export function describeError(error: unknown): string {
  if (error instanceof Error) return `${error.name}: ${error.message}`
  if (typeof error === 'string') return error
  if (error && typeof error === 'object') {
    const message = (error as { message?: unknown }).message
    if (typeof message === 'string' && message) return message
    try {
      return JSON.stringify(error)
    } catch {
      return '未知错误'
    }
  }
  return String(error)
}

/** 取当前页面路径;带上 search 便于定位分享链接导致的报错。 */
function currentRoute(): string {
  if (typeof location === 'undefined') return ''
  return `${location.pathname}${location.search}`.slice(0, MAX_ROUTE)
}

export interface Reporter {
  /** 上报一条错误;同一 message+路由在本次页面生命周期内只报一次。 */
  report(error: unknown, options?: { stack?: string; route?: string }): void
  /** 已经上报的条数(测试用)。 */
  readonly sent: number
}

/**
 * 创建一个带配额与去重的上报器。
 *
 * @param sender 发送函数(测试注入假实现)
 * @param appVersion 客户端版本号
 */
export function createReporter(sender: ClientErrorSender, appVersion = ''): Reporter {
  const seen = new Set<string>()
  let sent = 0
  return {
    get sent() {
      return sent
    },
    report(error: unknown, options: { stack?: string; route?: string } = {}): void {
      if (sent >= MAX_REPORTS) return
      const message = describeError(error).slice(0, MAX_MESSAGE)
      const route = (options.route ?? currentRoute()).slice(0, MAX_ROUTE)
      const key = `${message}|${route}`
      if (seen.has(key)) return
      seen.add(key)
      sent += 1
      const report: ClientErrorReport = {
        platform: 'web',
        message,
        stack: (options.stack ?? (error instanceof Error ? error.stack ?? '' : '')).slice(0, MAX_STACK),
        route,
        app_version: appVersion,
        request_id: currentRequestId(),
      }
      void sender(report).catch(() => {
        // 上报失败不能影响用户:静默丢弃
      })
    },
  }
}

export interface InstallOptions {
  /** 是否启用;默认读环境变量 */
  enabled?: boolean
  /** 发送函数(测试注入) */
  sender?: ClientErrorSender
  /** 客户端版本号 */
  appVersion?: string
  /** 事件目标(测试注入) */
  target?: Pick<Window, 'addEventListener' | 'removeEventListener'>
}

export interface InstalledReporter {
  /** 手动上报(Vue 的 errorHandler 用它) */
  report: Reporter['report']
  /** 卸载监听(测试用) */
  dispose(): void
}

/**
 * 安装全局错误监听:`window.onerror` 与 `unhandledrejection`。
 *
 * @param options 启用开关 / 发送器 / 版本号 / 事件目标
 * @returns 上报函数与卸载函数;开关关闭时返回空实现
 */
export function installClientErrorReporting(options: InstallOptions = {}): InstalledReporter {
  const enabled = options.enabled ?? errorReportingEnabled()
  if (!enabled) return { report: () => {}, dispose: () => {} }

  const reporter = createReporter(options.sender ?? postClientError, options.appVersion ?? '')
  const target = options.target ?? window

  const onError = (event: Event): void => {
    const errorEvent = event as ErrorEvent
    // 资源加载失败(图片/脚本 404)没有 error 对象,只有 message,单独记一条
    if (!errorEvent.error && !errorEvent.message) return
    reporter.report(errorEvent.error ?? errorEvent.message)
  }
  const onRejection = (event: Event): void => {
    const rejection = event as PromiseRejectionEvent
    reporter.report(rejection.reason)
  }

  target.addEventListener('error', onError)
  target.addEventListener('unhandledrejection', onRejection)
  return {
    report: reporter.report,
    dispose(): void {
      target.removeEventListener('error', onError)
      target.removeEventListener('unhandledrejection', onRejection)
    },
  }
}
