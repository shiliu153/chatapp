import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter, type RouteRecordRaw } from 'vue-router'
import { routes } from '@/router/routes'

/** 递归收集所有懒加载组件,逐个 import 以确保文件真实存在(防止拼错路径)。 */
function collect(records: readonly RouteRecordRaw[]): { name: string; load: () => Promise<unknown> }[] {
  const out: { name: string; load: () => Promise<unknown> }[] = []
  for (const record of records) {
    const name = String(record.name ?? record.path)
    if (typeof record.component === 'function') {
      out.push({ name, load: record.component as () => Promise<unknown> })
    }
    if (record.children) out.push(...collect(record.children))
  }
  return out
}

const REQUIRED_ROUTES = [
  'login',
  'onboarding',
  'discovery',
  'square',
  'chats',
  'mine',
  'chat',
  'user-profile',
  'post-detail',
  'post-compose',
  'my-posts',
  'settings',
  'settings-blocks',
  'profile-edit',
  'preference',
  'legal-agreement',
  'legal-privacy',
  'mobile-guard',
  'banned',
]

describe('路由表', () => {
  const entries = collect(routes)

  it('覆盖 spec §5.1 要求的全部页面', () => {
    const names = entries.map((e) => e.name)
    for (const required of REQUIRED_ROUTES) {
      expect(names, `缺少路由 ${required}`).toContain(required)
    }
  })

  it('每个懒加载组件都能真实加载(路径没写错)', { timeout: 15000 }, async () => {
    // 全量套件并行跑时,逐个 import 全部页面会超过默认 5s;这里只放宽超时,
    // 断言仍是「每个组件都能真实加载」
    expect(entries.length).toBeGreaterThanOrEqual(REQUIRED_ROUTES.length)
    for (const entry of entries) {
      await expect(entry.load(), `${entry.name} 加载失败`).resolves.toBeTruthy()
    }
  })

  it('公开路由都标了 meta.public(协议全文未登录可看)', () => {
    const publicNames = routes.filter((r) => r.meta?.public).map((r) => String(r.name))
    expect(publicNames).toContain('login')
    expect(publicNames).toContain('legal-agreement')
    expect(publicNames).toContain('legal-privacy')
    expect(publicNames).toContain('mobile-guard')
  })

  it('代码里跳转用到的路由名都必须能解析(登录后跳 home 曾因漏起名而失败)', () => {
    // 这些名字在页面代码里以 { name: ... } 形式出现;漏起名会在真实运行时
    // 报 "No match for {name:...}",而组件测试里自建的 router 抓不到
    const usedNames = [
      'home',
      'discovery',
      'square',
      'chats',
      'mine',
      'login',
      'chat',
      'settings',
      'settings-blocks',
      'profile-edit',
      'preference',
      'post-compose',
      'post-detail',
      'my-posts',
      'user-profile',
      'onboarding',
      'banned',
      'mobile-guard',
    ]
    const router = createRouter({ history: createMemoryHistory(), routes })
    // 带路径参数的路由各补一个占位参数,只验「名字能解析到」
    const paramsByName: Record<string, Record<string, string>> = {
      chat: { peerId: 'u1' },
      'user-profile': { id: '1' },
      'post-detail': { id: '1' },
    }
    for (const name of usedNames) {
      const params = paramsByName[name] ?? {}
      expect(
        router.resolve({ name, params }).matched.length,
        `路由名 ${name} 解析不到`,
      ).toBeGreaterThan(0)
    }
  })
})
