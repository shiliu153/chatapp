import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import PostDetailPage from '@/features/square/PostDetailPage.vue'
import { server } from '../support/server'

const post = {
  id: 5,
  author: { user_id: 3, nickname: '小雨', avatar_url: null },
  text: '正文',
  images: [],
  like_count: 0,
  comment_count: 1,
  liked_by_me: false,
  created_at: '2026-10-01T10:00:00Z',
}
const comment = {
  id: 1,
  author: { user_id: 4, nickname: '阿哲', avatar_url: null },
  text: '不错',
  created_at: '2026-10-01T11:00:00Z',
}
const paged = (results: unknown[]) => ({
  count: results.length,
  next: null,
  previous: null,
  results,
})

function mountPage(id = '5') {
  return mount(PostDetailPage, {
    props: { id },
    global: { plugins: [createPinia()], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
}

describe('PostDetailPage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('渲染正文与评论', async () => {
    server.use(
      mswHttp.get('/api/v1/posts/5', () => HttpResponse.json(post)),
      mswHttp.get('/api/v1/posts/5/comments', () => HttpResponse.json(paged([comment]))),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.text()).toContain('正文')
    expect(w.text()).toContain('不错')
  })

  it('没有评论时展示空态', async () => {
    server.use(
      mswHttp.get('/api/v1/posts/5', () => HttpResponse.json(post)),
      mswHttp.get('/api/v1/posts/5/comments', () => HttpResponse.json(paged([]))),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.text()).toContain('还没有评论')
  })

  it('发表评论后出现在列表最前', async () => {
    server.use(
      mswHttp.get('/api/v1/posts/5', () => HttpResponse.json(post)),
      mswHttp.get('/api/v1/posts/5/comments', () => HttpResponse.json(paged([comment]))),
      mswHttp.post('/api/v1/posts/5/comments', () =>
        HttpResponse.json({
          id: 2,
          author: { user_id: 9, nickname: '我', avatar_url: null },
          text: '沙发',
          created_at: '2026-10-01T12:00:00Z',
        }),
      ),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('input[type="text"]').setValue('沙发')
    await w.find('.comment-list__submit').trigger('click')
    await flushPromises()

    expect(w.findAll('.comment-list__item')[0].text()).toContain('沙发')
  })

  it('动态 404 时展示提示,不重试', async () => {
    server.use(
      mswHttp.get('/api/v1/posts/5', () =>
        HttpResponse.json(
          { code: 40404, message: '动态不存在或不可见', request_id: 'r' },
          { status: 404 },
        ),
      ),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.text()).toContain('动态不存在或不可见')
  })
})
