import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AboutPage from '@/features/settings/AboutPage.vue'

describe('AboutPage', () => {
  it('展示应用名、版本与协议入口', () => {
    const w = mount(AboutPage, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })

    expect(w.text()).toContain('心跳')
    expect(w.find('.about__version').text()).toContain('1.0.1')
    expect(w.find('.about__agreement').text()).toContain('用户协议')
    expect(w.find('.about__privacy').text()).toContain('隐私政策')
  })
})
