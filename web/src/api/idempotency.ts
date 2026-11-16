/**
 * 上传类接口的幂等键(`Idempotency-Key`)与「这次失败值不值得再试一次」的分类。
 *
 * 契约:`docs/api/conventions.md` §幂等键(后端 PR 416 合入;三个入口
 * `POST /im/images`、`POST /im/voices`、`POST /users/me/voice`)。三句话读完:
 *
 * 1. **一次上传一个 key**:用户选一张图 / 录一段语音 = 生成一个 key,这次上传的**所有自动
 *    重试都复用它**;换一张图、重新录一段 = 换新 key。重试换 key 等于告诉服务端「这是另一次
 *    上传」,会多落一份孤儿文件、白吃存储配额 —— 而这条路径错得**看不见**,只有日志能发现。
 * 2. **同 key 并发是可重试**:上一次还在处理时后到的请求回 `409` + `40901`。退避 1–2 秒后
 *    用**同一个 key** 再打一次,通常直接拿到首次的结果(`201` / 同一个 `id` 的 `202`)。
 *    把它当终态失败报给用户,等于让一次其实已经成功的上传变成失败。
 * 3. **`400` / `413` 立刻冒泡**:请求本身就不对(格式、时长、配额),服务端已经释放 key,
 *    重试只会再错一次;把服务端的中文原因早点交给用户比多转两圈有用。
 *
 * 为什么单独一个模块:三个上传入口是**同一套**口径(生成 key + 错误分类 + 退避循环)。
 * 各写一份的话,迟早只改其中一处。
 *
 * 关于 `FormData`:已经发出去的 `FormData` 会被浏览器标脏,重试用同一个对象会丢文件。
 * 所以 `withUploadRetries` 的 `run` 必须**每次重新构造**请求体 —— 三个入口都把
 * `new FormData()` 写在 `run` 里面,`rebuildBody` 供 401 刷新后重放时同样重建。
 */

import { isLocalError, parseApiError } from './error'

/**
 * key 的字符白名单与长度上限,与后端 `config/idempotency.py::KEY_PATTERN` 逐字一致。
 *
 * 为什么前端也要管:key 不合规服务端回 `400`(而不是静默忽略 —— 忽略会让客户端以为幂等
 * 生效,重试后才发现多了一份文件)。自己生成的值必须落在白名单里,这条正则就是单测的判据。
 */
export const IDEMPOTENCY_KEY_PATTERN = /^[A-Za-z0-9._:-]{1,128}$/

/** 一次上传最多试几次(含第一次)。3 次足够扛过抖动与一次 `40901`,再多只是让用户干等。 */
export const UPLOAD_ATTEMPTS = 3
/** 首次退避(毫秒),之后翻倍;`429` 带 `Retry-After` 时以它为准。 */
export const UPLOAD_BASE_DELAY_MS = 500
/** 退避上限:上传本来就是百毫秒级,退太久不如让用户重来。 */
export const UPLOAD_MAX_DELAY_MS = 4000
/**
 * 「同一个 key 的上一次上传还在处理中」的业务码(`409` + `40901`)。
 *
 * 分支判断以 `code` 为准(CLAUDE.md「错误契约」),不匹配中文文案。
 */
export const UPLOAD_IN_FLIGHT_CODE = 40901
/** `40901` 的建议退避(毫秒):契约写的是「退避 1–2 秒」,这里取 1 秒起步。 */
export const UPLOAD_IN_FLIGHT_DELAY_MS = 1000

/** 默认延时:用 `setTimeout` 而不是 `queueMicrotask`,否则假定时器里永远推进不下去。 */
function defaultSleep(ms: number): Promise<void> {
  return new Promise<void>((resolve) => setTimeout(resolve, ms))
}

/**
 * 生成一个幂等键(一次「用户发起的上传」一个)。
 *
 * 优先 `crypto.randomUUID()`(安全上下文下的现代浏览器、Node 22 与 jsdom 都有);
 * 没有时退回手搓 UUID v4 —— 不赌运行环境,拿不到随机源也不会让上传直接挂掉。
 *
 * Returns:
 *   36 字符的 UUID 字符串,落在 `IDEMPOTENCY_KEY_PATTERN` 里。
 */
export function newIdempotencyKey(): string {
  if (typeof globalThis.crypto?.randomUUID === 'function') return globalThis.crypto.randomUUID()
  const bytes = new Uint8Array(16)
  if (typeof globalThis.crypto?.getRandomValues === 'function') {
    globalThis.crypto.getRandomValues(bytes)
  } else {
    for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256)
  }
  // 版本位与变体位:生成的仍是合法 UUID v4(而不是「像 UUID 的随机串」)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20),
  ].join('-')
}

/**
 * 这次上传失败值不值得退避重试;值得就返回要等多久(毫秒),不值得返回 `null`。
 *
 * 判据四条,三个上传入口共用一套:
 * 1. 请求没到服务端(断网 / 超时)→ 退避再试;
 * 2. `429` 限流 → 按服务端 `Retry-After` 等,没给就用退避值;
 * 3. **`409` + `40901`(同 key 的上一次还在跑)→ 退避后再试**,契约建议 1–2 秒;
 * 4. `5xx` → 退避再试(服务端重启中,再问一次大概率就好了)。
 * 其余(401 / 403 / 404 / 400 / 413 …)一律不重试,原样上抛。
 *
 * Args:
 *   error: 上一次上传抛出的异常(axios 错误、`ApiError` 或本地错误)。
 *   backoffMs: 本次退避建议值(毫秒),由调用方按尝试次数翻倍。
 *
 * Returns:
 *   要等的毫秒数;`null` 表示「再试也一样,立刻冒泡」。
 */
export function uploadRetryDelay(error: unknown, backoffMs: number): number | null {
  const apiError = parseApiError(error)
  if (apiError.status === undefined) {
    // 没有 HTTP 状态码:请求没到服务端(断网/超时)值得退避再试;
    // 本地错误(压缩失败这类)再试一百遍也一样,直接抛
    return isLocalError(error) ? null : backoffMs
  }
  if (apiError.status === 429) {
    return apiError.retryAfter ? apiError.retryAfter * 1000 : backoffMs
  }
  if (apiError.status === 409 && apiError.code === UPLOAD_IN_FLIGHT_CODE) {
    // 不是失败,是「上一次还没跑完」:同一个 key 再打一次就能拿到首次的结果
    const retryAfterMs = apiError.retryAfter ? apiError.retryAfter * 1000 : 0
    return Math.max(UPLOAD_IN_FLIGHT_DELAY_MS, retryAfterMs, backoffMs)
  }
  if (apiError.status >= 500) return backoffMs
  // 401 / 403 / 404 是「再问也一样」;其余 4xx 是请求本身不对(像素超限 / 配额满 / 格式不支持)
  return null
}

/** 上传重试参数(单测注入点:不必真等)。 */
export interface UploadRetryOptions {
  /** 最多试几次(含第一次),缺省 `UPLOAD_ATTEMPTS` */
  attempts?: number
  /** 延时注入点;缺省 `setTimeout`(假定时器能够推进) */
  sleep?: (ms: number) => Promise<void>
  /** 首次退避(毫秒),缺省 `UPLOAD_BASE_DELAY_MS` */
  baseDelayMs?: number
  /** 退避上限(毫秒),缺省 `UPLOAD_MAX_DELAY_MS` */
  maxDelayMs?: number
}

/**
 * 跑一次上传,按 `uploadRetryDelay` 的分类自动退避重试。
 *
 * `run` 每次被调用都必须是**一次完整、干净**的请求:重新构造 `FormData`(已发送的对象会被
 * 浏览器标脏)、带上调用方闭包里的**同一个** `Idempotency-Key`。重试次数用尽时把最后一次的
 * 错误原样抛出(它的 `message` 可以直接展示给用户)。
 *
 * Args:
 *   run: 发一次请求(含构造请求体);抛出的错误交给 `uploadRetryDelay` 分类。
 *   options: 重试参数,见 `UploadRetryOptions`。
 *
 * Returns:
 *   `run` 第一次成功的返回值。
 *
 * Raises:
 *   ApiError / Error: 不可重试的错误,或重试次数用尽后的最后一次错误。
 */
export async function withUploadRetries<T>(
  run: () => Promise<T>,
  options: UploadRetryOptions = {},
): Promise<T> {
  const attempts = Math.max(1, options.attempts ?? UPLOAD_ATTEMPTS)
  const sleep = options.sleep ?? defaultSleep
  const maxDelayMs = options.maxDelayMs ?? UPLOAD_MAX_DELAY_MS
  let backoffMs = options.baseDelayMs ?? UPLOAD_BASE_DELAY_MS
  for (let attempt = 1; ; attempt += 1) {
    try {
      return await run()
    } catch (error) {
      const delay = attempt < attempts ? uploadRetryDelay(error, backoffMs) : null
      if (delay === null) throw error
      await sleep(delay)
      backoffMs = Math.min(maxDelayMs, backoffMs * 2)
    }
  }
}
