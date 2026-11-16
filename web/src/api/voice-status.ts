/**
 * 语音转码状态的轮询器(M-3,契约见 `docs/api/im.md` §6.5 与 `docs/api/users.md` §2.13)。
 *
 * 为什么单独一个模块:聊天语音(`GET /im/voices/{id}`)与资料语音(`GET /users/me/voice`)
 * 是**同一套三态语义**(`pending` / `ready` / `failed`)、同一份限流口径(480 次/小时)、
 * 同一套「网络抖动不要判死」的要求。两处各写一份循环,迟早只改一处 —— 而这里的坑
 * (退避、超时、哪些错误能吞)是**看不见的**:错了只会表现成「语音气泡永远转圈」。
 *
 * 三条硬约束:
 * - `pending` 时**只等不定死**:间隔优先用上传响应给的 `retry_after`(默认 5 秒),连续失败翻倍退避;
 * - **网络抖动 / 429 不算失败**(`onPending` 继续转圈),只有 401 / 403 / 404 这类「再问也一样」
 *   的错误立刻冒泡,以及连续失败到上限、整体超时才判失败;
 * - 不自己发请求:轮询哪个接口由调用方注入,便于单测用假网络、也避免这里知道 URL。
 */

import { parseApiError } from './error'
import type { VoiceStatus, VoiceStatusCode } from './types'

/** 后端 202 默认建议的轮询间隔(秒);响应里带了 `retry_after` 就以它为准。 */
export const VOICE_POLL_DEFAULT_INTERVAL_SECONDS = 5
/** 整体最长等待:再久也是运维问题,别让气泡无限转圈。 */
export const VOICE_POLL_TIMEOUT_MS = 90_000
/** 退避上限(秒级轮询没必要退太久,后端的转码只占 0.2–0.5 秒)。 */
export const VOICE_POLL_MAX_INTERVAL_MS = 15_000
/** 连续请求失败多少次后放弃(成功一次即清零)。 */
export const VOICE_POLL_MAX_FAILURES = 5
/** 超时话术:直接展示给用户,不是给开发看的。 */
export const VOICE_POLL_TIMEOUT_TEXT = '语音处理超时，请稍后重试'

export interface VoicePollOptions {
  /** 上传响应给的 `retry_after`(秒);缺省 5 秒 */
  retryAfterSeconds?: number
  /** 整体超时(毫秒),缺省 `VOICE_POLL_TIMEOUT_MS` */
  timeoutMs?: number
  /** 每轮还在 `pending` 时回调一次(UI 用它确认「还在转码」) */
  onPending?: () => void
  /** 延时注入点:单测用假定时器时不必替换,想完全去掉等待时再注入 */
  sleep?: (ms: number) => Promise<void>
}

/** 默认延时:用 `setTimeout` 而不是 `queueMicrotask`,否则假定时器里永远推进不下去。 */
function defaultSleep(ms: number): Promise<void> {
  return new Promise<void>((resolve) => setTimeout(resolve, ms))
}

/** 间隔夹在 [1 秒, 退避上限] 之间:后端给 0 / 负数时不要变成忙等。 */
function normalizeInterval(seconds: number | undefined): number {
  const raw = seconds !== undefined && Number.isFinite(seconds) ? seconds : VOICE_POLL_DEFAULT_INTERVAL_SECONDS
  return Math.min(VOICE_POLL_MAX_INTERVAL_MS, Math.max(1000, Math.round(raw * 1000)))
}

/**
 * 轮询到三态落定。
 *
 * Args:
 *   fetchStatus: 查询一次状态的函数;返回 `null` 表示「服务端没有这条语音」(资料语音的 404)。
 *   options: 轮询参数,见 `VoicePollOptions`。
 *
 * Returns:
 *   落定的状态(`ready` 或 `failed`),或 `null`(调用方返回 null 时原样透出)。
 *
 * Raises:
 *   ApiError: 401 / 403 / 404 这类重试无意义的错误,原样抛出。
 *   Error: 连续失败 `VOICE_POLL_MAX_FAILURES` 次、或整体超过 `timeoutMs`。
 */
export async function pollVoiceStatus(
  fetchStatus: () => Promise<VoiceStatus | null>,
  options: VoicePollOptions = {},
): Promise<VoiceStatus | null> {
  const timeoutMs = options.timeoutMs ?? VOICE_POLL_TIMEOUT_MS
  const sleep = options.sleep ?? defaultSleep
  let intervalMs = normalizeInterval(options.retryAfterSeconds)
  const deadline = Date.now() + timeoutMs
  let failures = 0

  for (;;) {
    try {
      const status = await fetchStatus()
      if (status === null) return null
      // 后端 `status` 是自由字符串,只认三态里的两个「落定」值,其余(含未知值)继续等
      const code = status.status as VoiceStatusCode
      if (code === 'ready' || code === 'failed') return status
      failures = 0
    } catch (error) {
      const apiError = parseApiError(error)
      // 「再问也一样」:令牌失效 / 被封禁 / 这条语音根本不是我的(404)。冒泡交给上层提示。
      if (apiError.status === 401 || apiError.status === 403 || apiError.status === 404) throw apiError
      failures += 1
      // 网络抖动与 429 只退避,不判死;但一直失败也得有个头
      if (failures >= VOICE_POLL_MAX_FAILURES) throw apiError
      intervalMs = Math.min(VOICE_POLL_MAX_INTERVAL_MS, intervalMs * 2)
    }
    if (Date.now() >= deadline) throw new Error(VOICE_POLL_TIMEOUT_TEXT)
    options.onPending?.()
    await sleep(intervalMs)
  }
}
