/**
 * 语音播放单例:同一时刻只播一条,切歌先停上一条(批次 T 起带进度与倍速)。
 *
 * 为什么还得是单例:聊天气泡可能一屏十条语音,各自 `new Audio` 就会两条一起响。
 * 所以「当前播放器」只有一个,`playVoice` 第一件事就是停掉上一条 —— 并且**顺手
 * 通知上一条的 `onEnd`**,把它的图标收回去(否则上一条气泡会永远停在「播放中」,
 * 进度条也冻在那儿)。
 *
 * 失败要能被调用方感知(可选 `onError`):浏览器的失败有两种表现 —— `play()` 直接 reject
 * (自动播放被拦、链接过期)和 `error` 事件(资源 404、容器解不了)。两条都只复位图标的话,
 * 用户看到的就是「点了没声音也没提示」;资料语音是公开绝对地址,换域名/搬媒体目录时最先中招。
 */

/** 一次进度回报:`ratio` 是 0–1 的比例,另两个是毫秒数(气泡上要显示 mm:ss)。 */
export interface VoiceProgress {
  ratio: number
  currentMs: number
  durationMs: number
}

/** 当前在播的那一条(音频元素 + 它的「播完/被停」回调)。 */
interface ActiveVoice {
  audio: HTMLAudioElement
  finish: () => void
}

let current: ActiveVoice | null = null

/**
 * 播放 [url]。
 *
 * Args:
 *   url: 音频地址(聊天语音/资料语音都是限时签名地址)。
 *   onEnd: 播完、被下一条顶掉、被 `stopVoice()` 停掉时调用(用于复位图标)。
 *   onError: 加载/解码失败或被浏览器拦自动播放时调用(可选)。
 *   onProgress: 播放进度回调,由 `timeupdate` 驱动(可选;不传就完全不监听)。
 */
export function playVoice(
  url: string,
  onEnd: () => void,
  onError?: () => void,
  onProgress?: (progress: VoiceProgress) => void,
): void {
  // 停上一条(会调用它的 onEnd,把上一条气泡的状态收回去)
  stopVoice()
  const audio = new Audio(url)
  const active: ActiveVoice = { audio, finish: onEnd }
  current = active

  /** 这一次播放结束了:让出「当前播放器」,后续 stopVoice 不会再回调一次。 */
  const settle = (): void => {
    if (current === active) current = null
  }

  audio.addEventListener('ended', () => {
    settle()
    onEnd()
  })
  audio.addEventListener('error', () => {
    settle()
    onEnd()
    onError?.()
  })
  if (onProgress) {
    audio.addEventListener('timeupdate', () => {
      const total = audio.duration
      // duration 在元数据到位前是 NaN/Infinity:此时算不出比例,别回调一个假的 0
      if (!Number.isFinite(total) || total <= 0) return
      const ratio = Math.min(1, Math.max(0, audio.currentTime / total))
      onProgress({ ratio, currentMs: audio.currentTime * 1000, durationMs: total * 1000 })
    })
  }
  void audio.play().catch(() => {
    // 自动播放被浏览器拦截 / 链接过期:复位图标,并让调用方决定要不要提示
    settle()
    onEnd()
    onError?.()
  })
}

/** 停止当前播放(会把它的图标复位;没有在播时是空操作)。 */
export function stopVoice(): void {
  const active = current
  current = null
  if (!active) return
  active.audio.pause()
  active.finish()
}

/**
 * 拖进度条:按比例 seek(`ratio` 是 0–1)。
 *
 * 用 `currentTime` 而不是重开一个 Audio:重开会让「暂停中也想拖」变得不可能,
 * 而且会重新拉一遍资源。没有在播 / 时长未知时静默忽略。
 *
 * Args:
 *   ratio: 目标位置,0 = 开头,1 = 结尾;越界自动夹到区间内。
 */
export function seekVoice(ratio: number): void {
  const audio = current?.audio
  if (!audio) return
  const total = audio.duration
  if (!Number.isFinite(total) || total <= 0) return
  audio.currentTime = Math.min(1, Math.max(0, ratio)) * total
}

/**
 * 倍速播放(`1` / `1.5` / `2`)。
 *
 * 只作用于**当前这一条**:换一条播就是新的 Audio 元素,倍速自然回到 1.0x ——
 * 这也是「换条播放复位 1.0x」的实现方式,不靠调用方记得手动清。
 *
 * Args:
 *   rate: 播放速率;非正数忽略(浏览器会抛 `NotSupportedError`)。
 */
export function setVoiceRate(rate: number): void {
  const audio = current?.audio
  if (!audio || rate <= 0) return
  audio.playbackRate = rate
}
