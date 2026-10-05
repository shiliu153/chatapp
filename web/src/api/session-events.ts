/** 会话级事件:由 http 层触发,由 UI 层监听(避免 http 反向依赖 Pinia / 路由)。 */
type Handler = () => void

const kickedOfflineHandlers = new Set<Handler>()
const sessionExpiredHandlers = new Set<Handler>()

export const sessionEvents = {
  onKickedOffline(handler: Handler): void {
    kickedOfflineHandlers.add(handler)
  },
  onSessionExpired(handler: Handler): void {
    sessionExpiredHandlers.add(handler)
  },
  emitKickedOffline(): void {
    kickedOfflineHandlers.forEach((h) => h())
  },
  emitSessionExpired(): void {
    sessionExpiredHandlers.forEach((h) => h())
  },
  /** 仅供测试重置 */
  _reset(): void {
    kickedOfflineHandlers.clear()
    sessionExpiredHandlers.clear()
  },
}
