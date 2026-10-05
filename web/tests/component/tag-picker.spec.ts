import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import TagPicker from '@/features/profile/TagPicker.vue'
import { useProfileStore } from '@/stores/profile'
import { freshPinia } from '../support/pinia'
import { server } from '../support/server'

const tags = [
  { id: 1, name: '旅行', icon: 'plane' },
  { id: 2, name: '电影', icon: 'film' },
]

/** 预置标签池的 pinia 与挂载时传入的必须是同一个,否则组件里读到的是空 store。 */
async function mountPicker(modelValue: number[]) {
  server.use(mswHttp.get('/api/v1/users/tags', () => HttpResponse.json(tags)))
  const pinia = freshPinia()
  const store = useProfileStore()
  await store.loadTags()
  const w = mount(TagPicker, { props: { modelValue }, global: { plugins: [pinia] } })
  await flushPromises()
  return w
}

describe('TagPicker', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('渲染标签池并展示已选项', async () => {
    const w = await mountPicker([2])

    expect(w.findAll('.tag-picker__chip')).toHaveLength(2)
    expect(w.findAll('.tag-picker__chip')[1].classes()).toContain('tag-picker__chip--active')
  })

  it('点击未选项 → 追加到 modelValue', async () => {
    const w = await mountPicker([])

    await w.findAll('.tag-picker__chip')[0].trigger('click')

    expect(w.emitted('update:modelValue')?.[0]).toEqual([[1]])
  })

  it('点击已选项 → 从 modelValue 移除', async () => {
    const w = await mountPicker([1, 2])

    await w.findAll('.tag-picker__chip')[0].trigger('click')

    expect(w.emitted('update:modelValue')?.[0]).toEqual([[2]])
  })
})
