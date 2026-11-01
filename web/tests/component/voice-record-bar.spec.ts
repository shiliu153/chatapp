import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import VoiceRecordBar from '@/features/chat/VoiceRecordBar.vue'

function mountBar(phase: 'recording' | 'sending' = 'recording', seconds = 5) {
  return mount(VoiceRecordBar, { props: { phase, seconds } })
}

describe('VoiceRecordBar', () => {
  it('渲染取消 / 计时 / 发送三段', () => {
    const w = mountBar('recording', 59)
    expect(w.text()).toContain('取消')
    expect(w.text()).toContain('00:59')
    expect(w.text()).toContain('发送')
  })

  it('超过 60 秒按上限显示', () => {
    expect(mountBar('recording', 65).text()).toContain('01:00')
  })

  it('点取消与发送各自 emit', async () => {
    const w = mountBar()
    await w.find('.voice-bar__cancel').trigger('click')
    await w.find('.voice-bar__send').trigger('click')
    expect(w.emitted('cancel')).toHaveLength(1)
    expect(w.emitted('send')).toHaveLength(1)
  })

  it('sending 态两个按钮都禁用', () => {
    const w = mountBar('sending')
    expect(w.find('.voice-bar__cancel').attributes('disabled')).toBeDefined()
    expect(w.find('.voice-bar__send').attributes('disabled')).toBeDefined()
    expect(w.text()).toContain('发送中')
  })
})
