/**
 * 语音转码轮询器(M-3)的单元测试。
 *
 * 这个循环的坑都在「看不见的地方」:退避错了会变成忙等、判死早了会让用户在转码途中
 * 看到「失败」、把 429 也当失败会直接吃掉正常排队。所以每条都用**假定时器 + 假网络**
 * 钉住:请求次数、间隔、以及最终是 resolve 还是 reject。
 */
import { ApiError } from '@/api/error'
import {
  pollVoiceStatus,
  VOICE_POLL_MAX_FAILURES,
  VOICE_POLL_TIMEOUT_TEXT,
} from '@/api/voice-status'
import type { VoiceStatus } from '@/api/types'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/** 一条三态状态;测试只关心 status 与失败原因,其余按契约给 null。 */
function status(code: 'pending' | 'ready' | 'failed', extra: Partial<VoiceStatus> = {}): VoiceStatus {
  return {
    id: 46,
    status: code,
    url: code === 'ready' ? 'https://cdn/media/chat/voices/46.m4a?e=1&s=x' : null,
    duration_ms: code === 'ready' ? 3200 : null,
    size: code === 'ready' ? 12345 : null,
    code: null,
    message: null,
    ...extra,
  }
}

describe('pollVoiceStatus', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('pending → ready:按 retry_after 轮询,第二次拿到 url 就停', async () => {
    const answers = [status('pending'), status('ready')]
    const fetcher = vi.fn(async () => answers.shift() ?? status('ready'))

    const done = pollVoiceStatus(fetcher, { retryAfterSeconds: 5 })
    await vi.advanceTimersByTimeAsync(0)
    expect(fetcher).toHaveBeenCalledTimes(1)

    // 还没到 5 秒,不该有第二次请求(否则就是忙等)
    await vi.advanceTimersByTimeAsync(4000)
    expect(fetcher).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(1000)
    const result = await done

    expect(fetcher).toHaveBeenCalledTimes(2)
    expect(result?.status).toBe('ready')
    expect(result?.url).toBe('https://cdn/media/chat/voices/46.m4a?e=1&s=x')
  })

  it('failed 原样返回(不抛):失败原因交给调用方展示', async () => {
    const fetcher = vi.fn(async () =>
      status('failed', { code: '41301', message: '存储空间已满' }),
    )

    const result = await pollVoiceStatus(fetcher, { retryAfterSeconds: 5 })

    expect(result?.status).toBe('failed')
    expect(result?.code).toBe('41301')
    expect(result?.message).toBe('存储空间已满')
  })

  it('网络抖动不判死:失败后翻倍退避,拿到 ready 就收工', async () => {
    const fetcher = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(0, '网络连接失败,请检查网络后重试'))
      .mockResolvedValueOnce(status('ready'))

    const done = pollVoiceStatus(fetcher, { retryAfterSeconds: 5 })
    await vi.advanceTimersByTimeAsync(0)
    expect(fetcher).toHaveBeenCalledTimes(1)

    // 第一次失败后间隔翻倍 → 10 秒,5 秒时不该重试
    await vi.advanceTimersByTimeAsync(5000)
    expect(fetcher).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(5000)
    expect(fetcher).toHaveBeenCalledTimes(2)

    await expect(done).resolves.toMatchObject({ status: 'ready' })
  })

  it('429(轮询限流)只退避,不判死', async () => {
    const throttled = new ApiError(429, '请求过于频繁,请稍后再试', undefined, 429)
    const fetcher = vi.fn().mockRejectedValueOnce(throttled).mockResolvedValueOnce(status('ready'))

    const done = pollVoiceStatus(fetcher, { retryAfterSeconds: 5 })
    await vi.advanceTimersByTimeAsync(10_000)

    await expect(done).resolves.toMatchObject({ status: 'ready' })
  })

  it('401 这类「再问也一样」的错误立刻冒泡(不要空转到超时)', async () => {
    const unauthorized = new ApiError(401, '未认证或令牌失效', undefined, 401)
    const fetcher = vi.fn(async () => Promise.reject(unauthorized))

    const done = expect(
      pollVoiceStatus(fetcher, { retryAfterSeconds: 5 }),
    ).rejects.toBeInstanceOf(ApiError)
    await vi.advanceTimersByTimeAsync(0)

    await done
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('一直失败到上限就放弃(不是无限转圈)', async () => {
    const fetcher = vi.fn(async () => Promise.reject(new ApiError(0, '网络连接失败')))

    const done = expect(
      pollVoiceStatus(fetcher, { retryAfterSeconds: 1 }),
    ).rejects.toThrow('网络连接失败')
    await vi.advanceTimersByTimeAsync(120_000)

    await done
    expect(fetcher).toHaveBeenCalledTimes(VOICE_POLL_MAX_FAILURES)
  })

  it('整体超时给出可直接展示的话术', async () => {
    const fetcher = vi.fn(async () => status('pending'))

    const done = expect(
      pollVoiceStatus(fetcher, { retryAfterSeconds: 1, timeoutMs: 5000 }),
    ).rejects.toThrow(VOICE_POLL_TIMEOUT_TEXT)
    await vi.advanceTimersByTimeAsync(60_000)

    await done
  })

  it('查询函数返回 null(资料语音 404)时直接透出 null,不当错误', async () => {
    const fetcher = vi.fn(async () => null)

    await expect(pollVoiceStatus(fetcher, { retryAfterSeconds: 5 })).resolves.toBeNull()
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('retry_after 缺失/离谱时也夹在合理区间(1 秒起,最多 15 秒)', async () => {
    const sleeps: number[] = []
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(status('pending'))
      .mockResolvedValueOnce(status('pending'))
      .mockResolvedValueOnce(status('ready'))

    const done = pollVoiceStatus(fetcher, {
      retryAfterSeconds: 0,
      sleep: async (ms) => {
        sleeps.push(ms)
      },
    })

    await expect(done).resolves.toMatchObject({ status: 'ready' })
    expect(sleeps).toEqual([1000, 1000])
  })
})
