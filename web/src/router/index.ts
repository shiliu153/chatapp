import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

/** 组件目检页只在开发期注册(Task 1.7)。 */
function devRoutes(): RouteRecordRaw[] {
  return import.meta.env.DEV
    ? [{ path: '/dev/components', component: () => import('@/features/dev/ComponentsPage.vue') }]
    : []
}

export const router = createRouter({
  history: createWebHistory(),
  routes: [{ path: '/', component: { template: '<div />' } }, ...devRoutes()],
})
