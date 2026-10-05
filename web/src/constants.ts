/** 应用名(与 App、软著、备案名保持一致,改名要全栈同步)。 */
export const APP_NAME = '心跳'

/** 移动端引导页的「下载 App」入口开关:商店上架后改 true 即出现真实入口。 */
export const DOWNLOADS_ENABLED = false

/** 在线心跳间隔(毫秒),与 App 一致(presence 轮询本身就是心跳)。 */
export const HEARTBEAT_INTERVAL_MS = 45_000
