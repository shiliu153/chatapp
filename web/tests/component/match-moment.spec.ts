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

  it('有共同标签 → 展示「你们都喜欢 X、Y」', () => {
    const w = mount(MatchMoment, {
      props: {
        candidate,
        myCity: '上海',
        sharedTags: [
          { id: 1, name: '运动', icon: 'sports' },
          { id: 3, name: '电影', icon: 'movie' },
          { id: 5, name: '音乐', icon: 'music' },
        ],
      },
      global: { stubs },
    })
    expect(w.find('.match-moment__icebreaker').text()).toBe(
      '你们都喜欢 运动、电影,不如从这儿聊起?',
    )
  })

  it('没有共同标签也不同城 → 整行不展示', () => {
    const w = mount(MatchMoment, {
      props: { candidate: { ...candidate, city: '成都' }, myCity: '杭州' },
      global: { stubs },
    })
    expect(w.find('.match-moment__icebreaker').exists()).toBe(false)
  })

  it('没有共同标签但同城 → 只说城市', () => {
    const w = mount(MatchMoment, {
      props: { candidate: { ...candidate, city: '杭州' }, myCity: '杭州' },
      global: { stubs },
    })
    expect(w.find('.match-moment__icebreaker').text()).toBe('你们都在 杭州')
  })
})
