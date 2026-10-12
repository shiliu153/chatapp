import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MatchMoment from '@/features/discovery/MatchMoment.vue'
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

const stubs = { RouterLink: { template: '<a><slot /></a>' } }

describe('MatchMoment', () => {
  it('展示配对文案与对方昵称', () => {
    const w = mount(MatchMoment, { props: { candidate }, global: { stubs } })
    expect(w.text()).toContain('你们互相喜欢')
    expect(w.text()).toContain('小雨')
  })

  it('「继续滑」派发 close', async () => {
    const w = mount(MatchMoment, { props: { candidate }, global: { stubs } })
    await w.find('.match-moment__close').trigger('click')
    expect(w.emitted('close')).toHaveLength(1)
  })
})
