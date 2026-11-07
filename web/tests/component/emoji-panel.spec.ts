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

  it('切到贴纸 tab:渲染 12 张贴纸,点选派发 sticker', async () => {
    const w = mountPanel()
    expect(w.findAll('.emoji-panel__sticker')).toHaveLength(0)

    await w.get('[data-testid="panel-tab-sticker"]').trigger('click')
    expect(w.findAll('.emoji-panel__item')).toHaveLength(0)
    expect(w.findAll('.emoji-panel__sticker')).toHaveLength(12)

    await w.get('[data-testid="sticker-sticker_01"]').trigger('click')
    expect(w.emitted('sticker')).toEqual([['sticker_01']])
  })

  it('贴纸资源走 public 目录,src 与 id 对应', async () => {
    const w = mountPanel()
    await w.get('[data-testid="panel-tab-sticker"]').trigger('click')

    const img = w.get('[data-testid="sticker-sticker_03"]').get('img')
    expect(img.attributes('src')).toBe('/stickers/sticker_03.png')
    expect(img.attributes('alt')).toBe('点赞')
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
