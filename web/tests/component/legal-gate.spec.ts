import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import LegalGate from '@/features/legal/LegalGate.vue'
import { LEGAL_VERSION, isAgreed, markAgreed } from '@/features/legal/agreed'

const stubs = { RouterLink: { template: '<a><slot /></a>' } }

describe('LegalGate', () => {
  beforeEach(() => localStorage.clear())

  it('未同意时展示弹窗,且必须勾选才能继续', async () => {
    const w = mount(LegalGate, { global: { stubs } })
    expect(isAgreed()).toBe(false)
    expect(w.find('.legal-gate').exists()).toBe(true)

    await w.find('.legal-gate__submit').trigger('click')
    expect(isAgreed()).toBe(false)
    expect(w.text()).toContain('请先阅读并同意')
  })

  it('勾选后同意 → 落盘并关闭弹窗', async () => {
    const w = mount(LegalGate, { global: { stubs } })
    await w.find('input[type="checkbox"]').setValue(true)
    await w.find('.legal-gate__submit').trigger('click')

    expect(isAgreed()).toBe(true)
    expect(w.find('.legal-gate').exists()).toBe(false)
  })

  it('已同意当前版本时不再展示', () => {
    markAgreed()
    const w = mount(LegalGate, { global: { stubs } })
    expect(w.find('.legal-gate').exists()).toBe(false)
  })

  it('协议升版后会重新弹一次(与 App 的 legalVersion 语义一致)', () => {
    localStorage.setItem('hb.legalAgreed', String(LEGAL_VERSION - 1))
    expect(isAgreed()).toBe(false)
    expect(mount(LegalGate, { global: { stubs } }).find('.legal-gate').exists()).toBe(true)
  })

  it('弹窗里有协议与隐私两个可打开的链接', () => {
    const w = mount(LegalGate, { global: { stubs } })
    expect(w.text()).toContain('《用户协议》')
    expect(w.text()).toContain('《隐私政策》')
  })
})
