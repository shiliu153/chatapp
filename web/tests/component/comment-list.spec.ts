import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import CommentList from '@/features/square/CommentList.vue'
import { useSessionStore } from '@/stores/session'
import type { Comment } from '@/api/types'
import { server } from '../support/server'

const replyTo = { user_id: 9, nickname: '阿哲' }

function comment(over: Partial<Comment> = {}): Comment {
  return {
    id: 1,
    author: { user_id: 9, nickname: '阿哲', avatar_url: null },
    text: '一楼',
    parent_id: null,
    reply_to: null,
    reply_count: 0,
    replies: [],
    created_at: '2026-10-01T11:00:00Z',
    ...over,
  }
}

function reply(id: number, text: string): Comment {
  return comment({
    id,
    text,
    parent_id: 1,
    reply_to: replyTo,
    author: { user_id: 12, nickname: '小雨', avatar_url: null },
  })
}

function mountList(comments: Comment[], count = comments.length) {
  return mount(CommentList, {
    props: { postId: 5, comments, count },
    global: {
      plugins: [createPinia()],
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
}

describe('CommentList 楼中楼', () => {
  it('渲染内嵌回复与「回复 @」前缀', () => {
    const w = mountList([
      comment({ reply_count: 2, replies: [reply(2, '回复一'), reply(3, '回复二')] }),
    ])
    expect(w.text()).toContain('回复一')
    expect(w.text()).toContain('回复 @阿哲')
  })

  it('回复多于内嵌条数时展示「查看全部」并展开', async () => {
    server.use(
      mswHttp.get('/api/v1/posts/5/comments/1/replies', () =>
        HttpResponse.json({
          count: 3,
          next: null,
          previous: null,
          results: [reply(2, '回复一'), reply(3, '回复二'), reply(4, '回复三')],
        }),
      ),
    )
    const w = mountList([comment({ reply_count: 3, replies: [reply(2, '回复一')] })])
    const more = w.find('.comment-list__more')
    expect(more.text()).toContain('查看全部 3 条回复')

    await more.trigger('click')
    await flushPromises()
    expect(w.text()).toContain('回复二')
    expect(w.text()).toContain('回复三')
  })

  it('点「回复」后提交带 parent_id', async () => {
    const created = reply(9, '回你')
    let body: unknown = null
    server.use(
      mswHttp.post('/api/v1/posts/5/comments', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json(created, { status: 201 })
      }),
    )
    const w = mountList([comment()])
    await w.find('.comment-list__reply').trigger('click')
    expect(w.text()).toContain('回复 @阿哲')

    await w.find('input[type="text"]').setValue('回你')
    await w.find('.comment-list__submit').trigger('click')
    await flushPromises()

    expect(body).toEqual({ text: '回你', parent_id: 1 })
    expect(w.emitted('added')?.[0]).toEqual([created])
  })

  it('自己的评论显示删除,确认后回调', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    server.use(
      mswHttp.delete('/api/v1/posts/5/comments/1', () => new HttpResponse(null, { status: 204 })),
    )
    const pinia = createPinia()
    setActivePinia(pinia)
    useSessionStore().userId = 7
    const mine = comment({ author: { user_id: 7, nickname: '我', avatar_url: null } })
    const w = mount(CommentList, {
      props: { postId: 5, comments: [mine], count: 1 },
      global: { plugins: [pinia], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })

    await w.find('.comment-list__delete').trigger('click')
    await flushPromises()

    expect(w.emitted('deleted')?.[0]).toEqual([mine])
  })
})
