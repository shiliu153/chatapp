import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PostCard from '@/features/square/PostCard.vue'
import type { Post } from '@/api/types'

const base: Post = {
  id: 1,
  author: { user_id: 3, nickname: '小雨', avatar_url: null },
  text: '今天天气不错',
  images: [],
  like_count: 2,
  comment_count: 1,
  liked_by_me: false,
  created_at: '2026-10-01T10:00:00Z',
}

function mountCard(overrides: Partial<Post> = {}, mine = false) {
  return mount(PostCard, {
    props: { post: { ...base, ...overrides }, mine },
    global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
}

describe('PostCard', () => {
  it('展示作者、正文、点赞与评论数', () => {
    const w = mountCard()
    expect(w.text()).toContain('小雨')
    expect(w.text()).toContain('今天天气不错')
    expect(w.find('.post-card__like').text()).toContain('2')
    expect(w.find('.post-card__comment').text()).toContain('1')
  })

  it('已点赞时按钮为选中态', () => {
    expect(mountCard({ liked_by_me: true }).find('.post-card__like').classes()).toContain(
      'post-card__like--active',
    )
  })

  it('点击点赞按钮派发 like 事件', async () => {
    const w = mountCard()
    await w.find('.post-card__like').trigger('click')
    expect(w.emitted('like')).toHaveLength(1)
  })

  it('图片数量决定网格类名', () => {
    expect(mountCard({ images: ['a'] }).find('.post-card__images--1').exists()).toBe(true)
    expect(mountCard({ images: ['a', 'b'] }).find('.post-card__images--2').exists()).toBe(true)
    expect(mountCard({ images: ['a', 'b', 'c'] }).find('.post-card__images--many').exists()).toBe(true)
  })

  it('是自己的动态才显示删除', async () => {
    expect(mountCard({}, true).find('.post-card__delete').exists()).toBe(true)
    expect(mountCard({}, false).find('.post-card__delete').exists()).toBe(false)
    const w = mountCard({}, true)
    await w.find('.post-card__delete').trigger('click')
    expect(w.emitted('delete')).toHaveLength(1)
  })
})
