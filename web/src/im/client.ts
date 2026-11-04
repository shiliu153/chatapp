/**
 * IM 客户端入口(唯一实现 = 自建 imserver)。
 *
 * 腾讯云 IM 分支已于 2026-11-08 删除(backlog D-4):这里不再有 SDK 惰性加载、
 * 事件名映射与 payload 转换,只剩「全局单例工厂」这一层 —— Pinia 的 `useXxxStore()`
 * 不接受参数,所以 store 只能通过工厂拿客户端;测试用 `setImClientFactory` 换假实现
 * (必须在 `useChatStore()` 之前调用)。
 */
import { SelfImClient } from './self/client'
import type { ImClient } from './types'

// 使用方(含测试)从本模块取类型,不必知道文件布局
export type { ImClient, ImEvent } from './types'

let factory: () => ImClient = () => new SelfImClient()

/** 仅供测试替换;生产路径不要调用。 */
export function setImClientFactory(fn: () => ImClient): void {
  factory = fn
}

export function getImClient(): ImClient {
  return factory()
}
