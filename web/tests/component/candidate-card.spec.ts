import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CandidateCard from '@/features/discovery/CandidateCard.vue'
import type { Candidate } from '@/api/types'

// 夹具显式标类型:否则 `gender: 'female'` 会被推断成 string,与 Gender 字面量联合不兼容
// (mount 会按组件 props 类型做检查,这类错误只有 vue-tsc 会报)。
const candidate: Candidate = {
  user_id: 8,
  nickname: '小雨',
  gender: 'female',
  age: 26,
  city: '上海',
  bio: '喜欢爬山',
  tags: [
    { id: 1, name: '旅行', icon: 'plane' },
    { id: 2, name: '电影', icon: 'film' },
    { id: 3, name: '咖啡', icon: 'coffee' },
    { id: 4, name: '摄影', icon: 'camera' },
  ],
  photos: [{ id: 1, url: 'https://cdn/a.jpg', status: 'approved', order: 0 }],
}

describe('CandidateCard', () => {
  it('展示照片、昵称年龄城市与最多 3 个标签', () => {
    const w = mount(CandidateCard, { props: { candidate } })
    expect(w.find('.candidate-card__photo').attributes('src')).toBe('https://cdn/a.jpg')
    expect(w.text()).toContain('小雨')
    expect(w.text()).toContain('26')
    expect(w.text()).toContain('上海')
    expect(w.findAll('.candidate-card__tag')).toHaveLength(3)
  })

  it('没有照片时用头像首字兜底', () => {
    const w = mount(CandidateCard, { props: { candidate: { ...candidate, photos: [] } } })
    expect(w.find('.candidate-card__photo').exists()).toBe(false)
    expect(w.find('.candidate-card__fallback').exists()).toBe(true)
  })

  it('在线时才渲染在线光', () => {
    expect(
      mount(CandidateCard, { props: { candidate, online: true } })
        .find('.candidate-card__online')
        .exists(),
    ).toBe(true)
    expect(
      mount(CandidateCard, { props: { candidate } }).find('.candidate-card__online').exists(),
    ).toBe(false)
  })
})
