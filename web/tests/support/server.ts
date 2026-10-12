import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll } from 'vitest'

/** 全局假网络:MSW 在网络层挡请求,组件与 store 都是真实的。 */
export const server = setupServer()

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers()
  localStorage.clear()
})
afterAll(() => server.close())
