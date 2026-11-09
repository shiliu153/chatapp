import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import VoiceRecordBar from '@/features/chat/VoiceRecordBar.vue'

function mountBar(phase: 'recording' | 'sending' = 'recording', seconds = 5) {
  return mount(VoiceRecordBar, { props: { phase, seconds } })
}

/** 资料语音口径:30 秒上限 + 自己的文案(聊天默认值不受影响,见上面的用例) */
function mountProfileBar(phase: 'recording' | 'sending' = 'recording', seconds = 5) {
  return mount(VoiceRecordBar, {
    props: {
      phase,
      seconds,
      maxSeconds: 30,
      confirmLabel: '停止',
      sendingLabel: '处理中…',
    },
  })
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

  it('资料语音口径:计时按 30 秒封顶,确认按钮文案可替换', () => {
    expect(mountProfileBar('recording', 29).text()).toContain('00:29')
    // 超过 30 秒(理论上不会发生)也只显示到 00:30
    expect(mountProfileBar('recording', 45).text()).toContain('00:30')
    expect(mountProfileBar('recording', 3).text()).toContain('停止')
    expect(mountProfileBar('sending', 3).text()).toContain('处理中…')
  })

  it('sending 态两个按钮都禁用', () => {
    const w = mountBar('sending')
    expect(w.find('.voice-bar__cancel').attributes('disabled')).toBeDefined()
    expect(w.find('.voice-bar__send').attributes('disabled')).toBeDefined()
    expect(w.text()).toContain('发送中')
  })
})
