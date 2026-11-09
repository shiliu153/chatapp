/**
 * 语音播放单例:同一时刻只播一条,切歌先停上一条。
 *
 * 不做播放进度:气泡只展示总时长与播放/暂停图标(与 App 端一致)。
 *
 * 失败要能被调用方感知(可选 `onError`):浏览器的失败有两种表现 —— `play()` 直接 reject
 * (自动播放被拦、链接过期)和 `error` 事件(资源 404、容器解不了)。两条都只复位图标的话,
 * 用户看到的就是「点了没声音也没提示」;资料语音是公开绝对地址,换域名/搬媒体目录时最先中招。
 */

let current: HTMLAudioElement | null = null

/** 播放 [url],播完回调 [onEnd](用于复位图标),加载/解码失败回调 [onError](可选)。 */
export function playVoice(url: string, onEnd: () => void, onError?: () => void): void {
  stopVoice()
  const audio = new Audio(url)
  current = audio
  audio.addEventListener('ended', onEnd)
  audio.addEventListener('error', () => onError?.())
  void audio.play().catch(() => {
    // 自动播放被浏览器拦截 / 链接过期:复位图标,并让调用方决定要不要提示
    onEnd()
    onError?.()
  })
}

/** 停止当前播放。 */
export function stopVoice(): void {
  current?.pause()
  current = null
}
