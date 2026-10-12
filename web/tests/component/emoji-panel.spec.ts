import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import EmojiPanel from '@/features/chat/EmojiPanel.vue'

function mountPanel() {
  return mount(EmojiPanel, { attachTo: document.body })
}

describe('EmojiPanel', () => {
  it('渲染表情网格(与 App 同一组,32 个)', () => {
    const w = mountPanel()
    expect(w.findAll('.emoji-panel__item')).toHaveLength(32)
  })

  it('点某个表情派发 pick,且带的就是那个字符', async () => {
    const w = mountPanel()
    await w.findAll('.emoji-panel__item')[0].trigger('click')

    expect(w.emitted('pick')).toEqual([['😀']])
  })

  it('按 Esc 关闭面板', async () => {
    const w = mountPanel()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await w.vm.$nextTick()

    expect(w.emitted('close')).toHaveLength(1)
  })

  it('其它按键不关闭(否则打字时面板会莫名消失)', async () => {
    const w = mountPanel()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'a' }))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await w.vm.$nextTick()

    expect(w.emitted('close')).toBeUndefined()
  })

  it('卸载后不再监听键盘(避免面板关掉后 Esc 还在触发)', async () => {
    const w = mountPanel()
    w.unmount()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(w.emitted('close')).toBeUndefined()
  })
})
