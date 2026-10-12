import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter, type RouteLocationRaw } from 'vue-router'
import { describe, expect, it } from 'vitest'
import AppSidebar from '@/components/AppSidebar.vue'
import { layout } from '@/layout'
import { freshPinia } from '../support/pinia'

const blank = { template: '<div/>' }

async function mountSidebar(width = 240, current: RouteLocationRaw = { name: 'discovery' }) {
  const pinia = freshPinia()
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'login', component: blank },
      { path: '/home/discovery', name: 'discovery', component: blank },
      { path: '/home/chats', name: 'chats', component: blank },
      { path: '/home/square', name: 'square', component: blank },
      { path: '/home/mine', name: 'mine', component: blank },
      { path: '/chat/:peerId', name: 'chat', component: blank },
      { path: '/settings', name: 'settings', component: blank },
    ],
  })
  await router.push(current)
  await router.isReady()

  const w = mount(AppSidebar, {
    props: { width, iconOnly: width < layout.sidebar.iconThreshold, unreadTotal: 3 },
    global: { plugins: [pinia, router], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
  return { w, router }
}

describe('AppSidebar', () => {
  it('宽态展示图标与文字', async () => {
    const { w } = await mountSidebar(240)
    expect(w.text()).toContain('发现')
    expect(w.text()).toContain('广场')
    expect(w.classes()).not.toContain('app-sidebar--icon-only')
  })

  it('窄态只显示图标,并给出 tooltip', async () => {
    const { w } = await mountSidebar(120)
    expect(w.classes()).toContain('app-sidebar--icon-only')
    expect(w.find('[title="发现"]').exists()).toBe(true)
  })

  it('选中态跟随当前路由(唯一高音)', async () => {
    const { w } = await mountSidebar(240, { name: 'square' })
    const active = w.findAll('.app-sidebar__item--active')
    expect(active).toHaveLength(1)
    expect(active[0].text()).toContain('广场')
  })

  it('聊天详情页时高亮「消息」', async () => {
    const { w } = await mountSidebar(240, { name: 'chat', params: { peerId: 'u8' } })
    expect(w.find('.app-sidebar__item--active').text()).toContain('消息')
  })

  it('宽态展示未读角标', async () => {
    const { w } = await mountSidebar(240)
    expect(w.find('.app-badge').text()).toBe('3')
  })

  it('窄态不展示角标(没地方放)', async () => {
    const { w } = await mountSidebar(120)
    expect(w.find('.app-badge').exists()).toBe(false)
  })

  it('拖拽手柄按下时派发 resize-start', async () => {
    const { w } = await mountSidebar(240)
    await w.find('.app-sidebar__handle').trigger('pointerdown')
    expect(w.emitted('resize-start')).toHaveLength(1)
  })

  it('双击手柄复位', async () => {
    const { w } = await mountSidebar(240)
    await w.find('.app-sidebar__handle').trigger('dblclick')
    expect(w.emitted('resize-reset')).toHaveLength(1)
  })
})
