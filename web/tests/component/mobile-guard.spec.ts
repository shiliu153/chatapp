import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MobileGuard from '@/layouts/MobileGuard.vue'

describe('MobileGuard', () => {
  it('提示去电脑打开、手机用 App', () => {
    const w = mount(MobileGuard)
    expect(w.text()).toContain('请在电脑上打开网页版')
    expect(w.text()).toContain('手机上请使用「心跳」App')
  })

  it('商店未上架时下载按钮为「敬请期待」且不可点', () => {
    const w = mount(MobileGuard)
    const btn = w.find('button')
    expect(btn.text()).toContain('敬请期待')
    expect(btn.attributes('disabled')).toBeDefined()
  })
})
