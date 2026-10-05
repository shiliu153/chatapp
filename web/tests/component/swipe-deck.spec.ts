import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SwipeDeck from '@/features/discovery/SwipeDeck.vue'
import type { Candidate } from '@/api/types'

const candidate: Candidate = {
  user_id: 8,
  nickname: '小雨',
  gender: 'female',
  age: 26,
  city: '上海',
  bio: '',
  tags: [],
  photos: [{ id: 1, url: 'https://cdn/a.jpg', status: 'approved', order: 0 }],
}

describe('SwipeDeck', () => {
  it('点「喜欢」圆钮派发 decide(like)', async () => {
    const w = mount(SwipeDeck, { props: { candidate } })
    await w.find('.swipe-deck__like').trigger('click')
    expect(w.emitted('decide')?.[0]).toEqual(['like'])
  })

  it('点「不喜欢」圆钮派发 decide(pass)', async () => {
    const w = mount(SwipeDeck, { props: { candidate } })
    await w.find('.swipe-deck__pass').trigger('click')
    expect(w.emitted('decide')?.[0]).toEqual(['pass'])
  })

  it('键盘左右方向键与圆钮走同一处理函数', async () => {
    const w = mount(SwipeDeck, { props: { candidate }, attachTo: document.body })
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }))
    expect(w.emitted('decide')).toEqual([['like'], ['pass']])
    w.unmount()
  })

  it('没有卡片时不渲染操作区', () => {
    const w = mount(SwipeDeck, { props: { candidate: null } })
    expect(w.find('.swipe-deck__actions').exists()).toBe(false)
  })

  it('submitting 时不重复派发', async () => {
    const w = mount(SwipeDeck, { props: { candidate, submitting: true } })
    await w.find('.swipe-deck__like').trigger('click')
    expect(w.emitted('decide')).toBeUndefined()
  })
})
