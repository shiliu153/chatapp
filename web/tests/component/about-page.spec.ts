import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AboutPage from '@/features/settings/AboutPage.vue'
import pkg from '../../package.json'

describe('AboutPage', () => {
  it('展示应用名、版本与协议入口', () => {
    const w = mount(AboutPage, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })

    expect(w.text()).toContain('心跳')
    // 版本号来自 package.json,经 vite.config 的 define 注入成 __APP_VERSION__ ——
    // 断言对着 package.json 读,升版本号时不需要手改本文件。
    expect(w.find('.about__version').text()).toContain(pkg.version)
    expect(w.find('.about__agreement').text()).toContain('用户协议')
    expect(w.find('.about__privacy').text()).toContain('隐私政策')
  })
})
