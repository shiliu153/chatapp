/**
 * 语音播放单例:同一时刻只播一条,切歌先停上一条。
 *
 * 不做播放进度:气泡只展示总时长与播放/暂停图标(与 App 端一致)。
 */

let current: HTMLAudioElement | null = null

/** 播放 [url],播完回调 [onEnd](用于复位气泡图标)。 */
export function playVoice(url: string, onEnd: () => void): void {
  stopVoice()
  current = new Audio(url)
  current.addEventListener('ended', onEnd)
  void current.play().catch(() => {
    // 自动播放被浏览器拦截 / 链接过期:静默复位,不让聊天页炸掉
    onEnd()
  })
}

/** 停止当前播放。 */
export function stopVoice(): void {
  current?.pause()
  current = null
}
