import { flushPromises, mount } from '@vue/test-utils'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import DiscoveryFilterPanel from '@/features/discovery/DiscoveryFilterPanel.vue'
import type { DiscoveryFilters, Preference } from '@/api/types'
import { freshPinia } from '../support/pinia'
import { server } from '../support/server'

/** 偏好是面板默认值的唯一来源(设置页仍是偏好的持久化入口) */
const preference: Preference = { target_gender: null, age_min: 25, age_max: 35, city: '上海' }

const tags = [
  { id: 1, name: '运动', icon: 'sports' },
  { id: 2, name: '电影', icon: 'movie' },
  { id: 3, name: '读书', icon: 'book' },
]

function mountPanel(initial: DiscoveryFilters = {}) {
  // 标签池由 TagPicker 挂载时自己拉(users.md §2.1)
  server.use(mswHttp.get('/api/v1/users/tags', () => HttpResponse.json(tags)))
  return mount(DiscoveryFilterPanel, {
    props: { preference, initial },
    global: { plugins: [freshPinia()] },
  })
}

/** 面板里的三个输入框顺序:年龄下限、年龄上限、城市 */
function inputs(w: ReturnType<typeof mountPanel>) {
  const all = w.findAll('input')
  return { ageMin: all[0], ageMax: all[1], city: all[2] }
}

describe('DiscoveryFilterPanel', () => {
  beforeEach(() => freshPinia())

  it('打开时默认值来自「想找的人」偏好', async () => {
    const w = mountPanel()
    await flushPromises()
    const { ageMin, ageMax, city } = inputs(w)

    expect((ageMin.element as HTMLInputElement).value).toBe('25')
    expect((ageMax.element as HTMLInputElement).value).toBe('35')
    expect((city.element as HTMLInputElement).value).toBe('上海')
  })

  it('已经生效的筛选优先于偏好作为默认值', async () => {
    const w = mountPanel({ age_min: 30, age_max: 40, city: '杭州', tag_ids: [2] })
    await flushPromises()
    const { ageMin, ageMax, city } = inputs(w)

    expect((ageMin.element as HTMLInputElement).value).toBe('30')
    expect((ageMax.element as HTMLInputElement).value).toBe('40')
    expect((city.element as HTMLInputElement).value).toBe('杭州')
    expect(w.find('.tag-picker__chip--active').text()).toBe('电影')
  })

  it('只改城市时只发 city(覆盖语义:不发年龄与标签)', async () => {
    const w = mountPanel()
    await flushPromises()

    await inputs(w).city.setValue('杭州')
    await w.find('.filter-panel__apply').trigger('click')

    expect(w.emitted('apply')?.[0]).toEqual([{ city: '杭州' }])
  })

  it('改年龄区间时发 age_min/age_max,城市与偏好相同则不发', async () => {
    const w = mountPanel()
    await flushPromises()

    await inputs(w).ageMin.setValue('28')
    await inputs(w).ageMax.setValue('40')
    await w.find('.filter-panel__apply').trigger('click')

    expect(w.emitted('apply')?.[0]).toEqual([{ age_min: 28, age_max: 40 }])
  })

  it('多选标签时发升序的 tag_ids', async () => {
    const w = mountPanel()
    await flushPromises()
    const chips = w.findAll('.tag-picker__chip')

    await chips[2].trigger('click') // 读书
    await chips[0].trigger('click') // 运动
    await w.find('.filter-panel__apply').trigger('click')

    expect(w.emitted('apply')?.[0]).toEqual([{ tag_ids: [1, 3] }])
  })

  it('把年龄改回偏好值等价于没改:一个参数都不发', async () => {
    const w = mountPanel({ age_min: 30, age_max: 40, city: '杭州' })
    await flushPromises()

    await inputs(w).ageMin.setValue('25')
    await inputs(w).ageMax.setValue('35')
    await inputs(w).city.setValue('上海')
    await w.find('.filter-panel__apply').trigger('click')

    expect(w.emitted('apply')?.[0]).toEqual([{}])
  })

  it('「重置」发出 reset(由父级清空筛选并重拉候选池)', async () => {
    const w = mountPanel({ city: '杭州' })
    await flushPromises()

    await w.find('.filter-panel__reset').trigger('click')

    expect(w.emitted('reset')).toHaveLength(1)
    expect(w.emitted('apply')).toBeUndefined()
  })

  it('年龄区间非法时本地拦下,不发请求(避免必然的 400)', async () => {
    const w = mountPanel()
    await flushPromises()

    await inputs(w).ageMin.setValue('40')
    await inputs(w).ageMax.setValue('20')
    await w.find('.filter-panel__apply').trigger('click')

    expect(w.emitted('apply')).toBeUndefined()
    expect(w.find('.filter-panel__error').text()).toContain('年龄区间')
  })

  it('点关闭按钮只发 close,不改筛选', async () => {
    const w = mountPanel()
    await flushPromises()

    await w.find('.filter-panel__close').trigger('click')

    expect(w.emitted('close')).toHaveLength(1)
    expect(w.emitted('apply')).toBeUndefined()
  })
})
