import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import LegalPage from '@/features/legal/LegalPage.vue'

describe('LegalPage', () => {
  it('用户协议', () => {
    const w = mount(LegalPage, { props: { kind: 'agreement' } })
    expect(w.find('.legal__title').text()).toBe('用户协议')
    expect(w.find('.legal__body').text()).toContain('年满 18 周岁')
  })

  it('隐私政策', () => {
    const w = mount(LegalPage, { props: { kind: 'privacy' } })
    expect(w.find('.legal__title').text()).toBe('隐私政策')
    expect(w.find('.legal__body').text()).toContain('腾讯云 IM')
  })

  it('正文与 App 的 legal_texts.dart 逐字一致(抽查关键句)', () => {
    const agreement = mount(LegalPage, { props: { kind: 'agreement' } }).find('.legal__body').text()
    const privacy = mount(LegalPage, { props: { kind: 'privacy' } }).find('.legal__body').text()
    expect(agreement).toContain('本协议为开发阶段草稿,最终版本以正式上架时的文本为准。')
    expect(privacy).toContain('如对本政策有疑问或需要投诉,请通过应用商店页面提供的联系方式与我们联系。')
  })
})
