import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { isMobileDevice } from '@/composables/useDevice'
import { useProfileStore } from '@/stores/profile'
import { useSessionStore } from '@/stores/session'
import { routes } from './routes'

/** 组件目检页只在开发期注册(Task 1.7)。 */
function devRoutes(): RouteRecordRaw[] {
  return import.meta.env.DEV
    ? [{ path: '/dev/components', component: () => import('@/features/dev/ComponentsPage.vue') }]
    : []
}

export function createAppRouter() {
  const router = createRouter({
    history: createWebHistory(),
    routes: [...routes, ...devRoutes()],
  })

  router.beforeEach(async (to) => {
    // 1) 移动端浏览器:一律引导页(spec §6.1,按设备判定,不看窗口宽度)
    if (isMobileDevice() && to.name !== 'mobile-guard') {
      return { name: 'mobile-guard' }
    }

    // 2) 会话态:首次进入先恢复
    const session = useSessionStore()
    if (session.status === 'loading') await session.restore()

    // 3) 公开路由直接放行(协议全文未登录也要能看)
    if (to.meta.public) {
      // 已登录还停在登录页 → 回家。
      // ⚠️ 这里**不能**把 mobile-guard 也重定向:否则会死循环
      //    (移动端 → 引导页 → 已登录 → 首页 → 移动端 → 引导页 → …)
      if (session.status === 'loggedIn' && to.name === 'login') {
        return { name: 'discovery' }
      }
      return true
    }

    if (session.status !== 'loggedIn') return { name: 'login' }

    // 4) 封禁:重封禁全域拦截(spec §5.1)。
    //    资料只在首次进入时拉一次,避免每次路由跳转都打接口。
    const profile = useProfileStore()
    if (!profile.profile) {
      await profile.load()
    }
    if (profile.isBannedHeavy && to.name !== 'banned') {
      return { name: 'banned' }
    }
    return true
  })

  return router
}

export const router = createAppRouter()
