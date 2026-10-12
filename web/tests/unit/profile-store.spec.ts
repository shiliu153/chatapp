import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { useProfileStore } from '@/stores/profile'
import { server } from '../support/server'

const mePayload = {
  id: 11,
  user_id: 9,
  phone: '13800000001',
  nickname: '',
  gender: '',
  birthday: null,
  age: null,
  city: '',
  bio: '',
  status: 'incomplete',
  ban_reason: '',
  missing_fields: ['nickname', 'photos'],
  tags: [],
  photos: [],
  preference: { target_gender: null, age_min: 18, age_max: 99, city: '' },
}

describe('profile store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('load 拉回资料并暴露缺项与封禁判定', async () => {
    server.use(mswHttp.get('/api/v1/users/me', () => HttpResponse.json(mePayload)))
    const store = useProfileStore()

    await store.load()

    expect(store.profile?.user_id).toBe(9)
    expect(store.isIncomplete).toBe(true)
    expect(store.isBannedHeavy).toBe(false)
    expect(store.missingFieldsText).toContain('昵称')
  })

  it('banned_heavy 时 isBannedHeavy 为真', async () => {
    server.use(
      mswHttp.get('/api/v1/users/me', () =>
        HttpResponse.json({ ...mePayload, status: 'banned_heavy', ban_reason: '违规' }),
      ),
    )
    const store = useProfileStore()
    await store.load()
    expect(store.isBannedHeavy).toBe(true)
    expect(store.profile?.ban_reason).toBe('违规')
  })

  it('save 后资料被替换为服务端返回的最新值', async () => {
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(mePayload)),
      mswHttp.patch('/api/v1/users/me', () =>
        HttpResponse.json({
          ...mePayload,
          nickname: '小雨',
          status: 'incomplete',
          missing_fields: ['photos'],
        }),
      ),
    )
    const store = useProfileStore()
    await store.load()

    await store.save({ nickname: '小雨' })

    expect(store.profile?.nickname).toBe('小雨')
    expect(store.profile?.missing_fields).toEqual(['photos'])
  })

  it('上传照片走 multipart,字段名固定为 file', async () => {
    // 只断言「我们控制的契约」:multipart、字段名 file、原始字节送达。
    // 文件名不断言 —— jsdom 的 File 与 undici 的 File 不是同一个类,MSW 序列化时
    // 会把 filename 回落成 "blob"(已在真实 body 里复核过);真浏览器走原生 XHR 不受影响。
    let contentType = ''
    let received: { keys: string[]; size: number } | null = null
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(mePayload)),
      mswHttp.post('/api/v1/users/me/photos', async ({ request }) => {
        contentType = request.headers.get('content-type') ?? ''
        const form = await request.formData()
        const file = form.get('file') as unknown as { size?: number } | null
        received = { keys: [...form.keys()], size: file?.size ?? -1 }
        return HttpResponse.json({ id: 3, url: 'https://cdn/x.jpg', status: 'pending', order: 0 })
      }),
    )
    const store = useProfileStore()
    await store.load()

    await store.uploadPhoto(new File(['x'], 'me.jpg', { type: 'image/jpeg' }))

    expect(contentType).toContain('multipart/form-data')
    expect(received).toEqual({ keys: ['file'], size: 1 })
    expect(store.profile?.photos).toHaveLength(1)
  })

  it('删除照片:DELETE 到 /users/me/photos/{id} 并从列表移除', async () => {
    let method = ''
    let url = ''
    server.use(
      mswHttp.get('/api/v1/users/me', () =>
        HttpResponse.json({
          ...mePayload,
          photos: [
            { id: 3, url: 'https://cdn/a.jpg', status: 'approved', order: 0 },
            { id: 4, url: 'https://cdn/b.jpg', status: 'pending', order: 1 },
          ],
        }),
      ),
      mswHttp.delete('/api/v1/users/me/photos/:id', ({ request }) => {
        method = request.method
        url = new URL(request.url).pathname
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const store = useProfileStore()
    await store.load()

    await store.removePhoto(3)

    expect(method).toBe('DELETE')
    expect(url).toBe('/api/v1/users/me/photos/3')
    expect(store.profile?.photos.map((p) => p.id)).toEqual([4])
  })

  it('加载失败时记录错误文案', async () => {
    server.use(
      mswHttp.get('/api/v1/users/me', () =>
        HttpResponse.json({ code: 50002, message: '服务器开小差了', request_id: 'r' }, { status: 500 }),
      ),
    )
    const store = useProfileStore()
    await store.load()
    expect(store.error).toBe('服务器开小差了')
  })
})
