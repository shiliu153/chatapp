import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppAvatar from '@/components/AppAvatar.vue'

describe('AppAvatar', () => {
  it('有图时渲染 img,尺寸跟随 size', () => {
    const w = mount(AppAvatar, { props: { src: 'https://cdn/x.jpg', name: '小雨', size: 48 } })
    const img = w.find('img')
    expect(img.attributes('src')).toBe('https://cdn/x.jpg')
    expect(w.attributes('style')).toContain('48px')
  })

  it('无图时用昵称首字占位(心跳渐变底)', () => {
    const w = mount(AppAvatar, { props: { name: '小雨' } })
    expect(w.text()).toBe('小')
    expect(w.classes()).toContain('app-avatar--fallback')
  })

  it('昵称为空时占位为 ♥', () => {
    expect(mount(AppAvatar, { props: {} }).text()).toBe('♥')
  })

  it('传了 src 但为空字符串时仍走占位', () => {
    const w = mount(AppAvatar, { props: { src: '', name: '阿泽' } })
    expect(w.find('img').exists()).toBe(false)
    expect(w.text()).toBe('阿')
  })
})
