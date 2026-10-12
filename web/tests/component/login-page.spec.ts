import { flushPromises, mount } from '@vue/test-utils'
import { HttpResponse, http as mswHttp } from 'msw'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'
import LoginPage from '@/features/auth/LoginPage.vue'
import { tokenStore } from '@/api/token-store'
import { freshPinia } from '../support/pinia'
import { server } from '../support/server'

/** 挂一个真实的 memory router,这样 useRouter()/router.push 都是真行为。 */
async function mountLogin() {
  const pinia = freshPinia()
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div/>' } },
      { path: '/home', name: 'home', component: { template: '<div/>' } },
      { path: '/onboarding', name: 'onboarding', component: { template: '<div/>' } },
      { path: '/login', name: 'login', component: { template: '<div/>' } },
    ],
  })
  await router.push('/login')
  await router.isReady()

  const w = mount(LoginPage, {
    global: { plugins: [pinia, router], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
  await flushPromises()
  return { w, router }
}

describe('LoginPage', () => {
  it('手机号格式不合法时不发码并给出提示', async () => {
    const { w } = await mountLogin()
    await w.find('input[type="tel"]').setValue('138')
    await w.find('.login__send').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('请输入 11 位手机号')
  })

  it('发码成功后进入 60 秒倒计时且按钮禁用', async () => {
    server.use(mswHttp.post('/api/v1/auth/sms/send', () => HttpResponse.json({ status: 'ok' })))
    const { w } = await mountLogin()
    await w.find('input[type="tel"]').setValue('13800000001')
    await w.find('.login__send').trigger('click')
    await flushPromises()

    expect(w.find('.login__send').text()).toContain('秒后重发')
    expect(w.find('.login__send').attributes('disabled')).toBeDefined()
  })

  it('42901 时按 Retry-After 提示等待', async () => {
    server.use(
      mswHttp.post('/api/v1/auth/sms/send', () =>
        HttpResponse.json(
          { code: 42901, message: '发送过于频繁,请稍后再试', request_id: 'r' },
          { status: 429, headers: { 'Retry-After': '45' } },
        ),
      ),
    )
    const { w } = await mountLogin()
    await w.find('input[type="tel"]').setValue('13800000001')
    await w.find('.login__send').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('发送过于频繁')
    expect(w.find('.login__send').text()).toContain('45')
  })

  it('验证码位数不足时不提交', async () => {
    const { w } = await mountLogin()
    await w.find('input[type="tel"]').setValue('13800000001')
    await w.find('input[inputmode="numeric"]').setValue('12')
    await w.find('.login__submit').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('请输入 6 位验证码')
    expect(tokenStore.access).toBeNull()
  })

  it('验证码错误时展示后端文案', async () => {
    server.use(
      mswHttp.post('/api/v1/auth/sms/verify', () =>
        HttpResponse.json({ code: 40003, message: '验证码错误', request_id: 'r' }, { status: 400 }),
      ),
    )
    const { w } = await mountLogin()
    await w.find('input[type="tel"]').setValue('13800000001')
    await w.find('input[inputmode="numeric"]').setValue('000000')
    await w.find('.login__submit').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('验证码错误')
    expect(tokenStore.access).toBeNull()
  })

  it('登录成功写入令牌并跳转 /home', async () => {
    server.use(
      mswHttp.post('/api/v1/auth/sms/verify', () =>
        HttpResponse.json({ access: 'a1', refresh: 'r1', is_new_user: false, user_id: 9 }),
      ),
    )
    const { w, router } = await mountLogin()
    await w.find('input[type="tel"]').setValue('13800000001')
    await w.find('input[inputmode="numeric"]').setValue('123456')
    await w.find('.login__submit').trigger('click')
    await flushPromises()

    expect(tokenStore.access).toBe('a1')
    expect(router.currentRoute.value.path).toBe('/home')
  })

  it('新用户登录后先去 /onboarding 完善资料(与 App 一致)', async () => {
    server.use(
      mswHttp.post('/api/v1/auth/sms/verify', () =>
        HttpResponse.json({ access: 'a1', refresh: 'r1', is_new_user: true, user_id: 9 }),
      ),
    )
    const { w, router } = await mountLogin()
    await w.find('input[type="tel"]').setValue('13800000001')
    await w.find('input[inputmode="numeric"]').setValue('123456')
    await w.find('.login__submit').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/onboarding')
  })

  it('连错锁定(42902)时展示后端文案', async () => {
    server.use(
      mswHttp.post('/api/v1/auth/sms/verify', () =>
        HttpResponse.json(
          { code: 42902, message: '错误次数过多,请 15 分钟后再试', request_id: 'r' },
          { status: 429 },
        ),
      ),
    )
    const { w } = await mountLogin()
    await w.find('input[type="tel"]').setValue('13800000001')
    await w.find('input[inputmode="numeric"]').setValue('000000')
    await w.find('.login__submit').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('错误次数过多')
  })
})
