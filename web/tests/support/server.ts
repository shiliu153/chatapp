import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { tokenStore } from '@/api/token-store'

/** 全局假网络:MSW 在网络层挡请求,组件与 store 都是真实的。 */
export const server = setupServer()

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers()
  // access 只在内存里,localStorage.clear() 清不到它,必须显式清,否则会跨用例泄漏
  tokenStore.clear()
  localStorage.clear()
})
afterAll(() => server.close())
