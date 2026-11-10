/**
 * `voicePlayer` 单例(批次 T 补齐进度 / seek / 倍速)。
 *
 * 用假 `Audio` 顶掉 jsdom(它的播放器什么都不做,`play()` 直接抛「未实现」),
 * 这样才测得到「`timeupdate` 推的比例对不对」「切歌时上一条的图标有没有收回去」
 * 「`seek` 用的是不是 `currentTime`」这些真正会错的地方。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { playVoice, seekVoice, setVoiceRate, stopVoice } from '@/im/voicePlayer'
import type { VoiceProgress } from '@/im/voicePlayer'

class FakeAudio {
  static instances: FakeAudio[] = []
  /** 让**下一条**播放的 `play()` 直接 reject(模拟自动播放被拦 / 链接过期) */
  static failNextPlay = false

  src: string
  currentTime = 0
  duration = 20
  playbackRate = 1
  paused = true
  /** `play()` 是否被调用过 */
  played = false
  failPlay = FakeAudio.failNextPlay
  private listeners = new Map<string, (() => void)[]>()

  constructor(src: string) {
    this.src = src
    FakeAudio.instances.push(this)
  }

  addEventListener(type: string, fn: () => void): void {
    const list = this.listeners.get(type) ?? []
    list.push(fn)
    this.listeners.set(type, list)
  }

  emit(type: string): void {
    for (const fn of this.listeners.get(type) ?? []) fn()
  }

  play(): Promise<void> {
    this.played = true
    if (this.failPlay) return Promise.reject(new Error('NotAllowedError'))
    this.paused = false
    return Promise.resolve()
  }

  pause(): void {
    this.paused = true
  }
}

/** 最后一次 new 出来的播放器(单例语义下就是「当前在播的那条」) */
function latest(): FakeAudio {
  const instance = FakeAudio.instances.at(-1)
  if (!instance) throw new Error('没有创建过 Audio')
  return instance
}

describe('voicePlayer', () => {
  beforeEach(() => {
    FakeAudio.instances = []
    FakeAudio.failNextPlay = false
    vi.stubGlobal('Audio', FakeAudio)
  })

  afterEach(() => {
    stopVoice()
    vi.unstubAllGlobals()
  })

  it('timeupdate 按比例回报进度(用 currentTime / duration)', () => {
    const progress: VoiceProgress[] = []
    playVoice('a.m4a', () => {}, undefined, (p) => progress.push(p))

    const audio = latest()
    audio.duration = 20
    audio.currentTime = 5
    audio.emit('timeupdate')

    expect(progress).toHaveLength(1)
    expect(progress[0]).toEqual({ ratio: 0.25, currentMs: 5000, durationMs: 20_000 })
  })

  it('时长还没拿到(duration 不是有限数)不回调假进度', () => {
    const progress: VoiceProgress[] = []
    playVoice('a.m4a', () => {}, undefined, (p) => progress.push(p))

    const audio = latest()
    audio.duration = Number.NaN
    audio.currentTime = 3
    audio.emit('timeupdate')

    expect(progress).toHaveLength(0)
  })

  it('播完回调 onEnd,之后再 stopVoice 不会再回调一次', () => {
    const onEnd = vi.fn()
    playVoice('a.m4a', onEnd)
    latest().emit('ended')

    expect(onEnd).toHaveBeenCalledTimes(1)
    stopVoice()
    expect(onEnd).toHaveBeenCalledTimes(1)
  })

  it('切歌先停上一条,并把它气泡上的状态收回去', () => {
    const firstEnd = vi.fn()
    playVoice('a.m4a', firstEnd)
    const first = latest()

    playVoice('b.m4a', () => {})

    expect(first.paused).toBe(true)
    // 上一条的图标要靠 onEnd 复位,否则它会永远停在「播放中」
    expect(firstEnd).toHaveBeenCalledTimes(1)
  })

  it('seek 用 currentTime 按比例定位,越界夹到区间内', () => {
    playVoice('a.m4a', () => {})
    const audio = latest()
    audio.duration = 30

    seekVoice(0.5)
    expect(audio.currentTime).toBe(15)

    seekVoice(2)
    expect(audio.currentTime).toBe(30)

    seekVoice(-1)
    expect(audio.currentTime).toBe(0)
  })

  it('没有在播时 seek / 改倍速是空操作(不抛错)', () => {
    expect(() => {
      seekVoice(0.5)
      setVoiceRate(2)
    }).not.toThrow()
  })

  it('倍速写进 playbackRate;换一条播放自动复位 1.0x', () => {
    playVoice('a.m4a', () => {})
    setVoiceRate(2)
    expect(latest().playbackRate).toBe(2)

    playVoice('b.m4a', () => {})
    expect(latest().playbackRate).toBe(1)
  })

  it('非正数倍速忽略(浏览器会抛 NotSupportedError)', () => {
    playVoice('a.m4a', () => {})
    setVoiceRate(0)
    expect(latest().playbackRate).toBe(1)
  })

  it('play() 被拦/链接过期:复位图标并回调 onError', async () => {
    FakeAudio.failNextPlay = true
    const onEnd = vi.fn()
    const onError = vi.fn()
    playVoice('a.m4a', onEnd, onError)
    // play() 的 reject 在微任务里落到 catch
    await Promise.resolve()
    await Promise.resolve()

    expect(onEnd).toHaveBeenCalledTimes(1)
    expect(onError).toHaveBeenCalledTimes(1)
    // 失败后不再占着「当前播放器」:下一次播放不该被它挡住
    stopVoice()
    expect(onEnd).toHaveBeenCalledTimes(1)
  })

  it('error 事件(资源 404 / 解不了容器):复位图标并回调 onError', () => {
    const onEnd = vi.fn()
    const onError = vi.fn()
    playVoice('a.m4a', onEnd, onError)
    latest().emit('error')

    expect(onEnd).toHaveBeenCalledTimes(1)
    expect(onError).toHaveBeenCalledTimes(1)
  })

  it('stopVoice 停掉当前播放并复位图标', () => {
    const onEnd = vi.fn()
    playVoice('a.m4a', onEnd)
    stopVoice()

    expect(latest().paused).toBe(true)
    expect(onEnd).toHaveBeenCalledTimes(1)
  })
})
