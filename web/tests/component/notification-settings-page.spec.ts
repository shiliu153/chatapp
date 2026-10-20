import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import NotificationSettingsPage from '@/features/settings/NotificationSettingsPage.vue'

describe('NotificationSettingsPage', () => {
  it('两个开关都禁用并标注即将上线', () => {
    const w = mount(NotificationSettingsPage, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })

    expect(w.text()).toContain('新配对提醒')
    expect(w.text()).toContain('新消息提醒')
    expect(w.findAll('.notify__soon')).toHaveLength(2)

    const switches = w.findAll('.notify__switch')
    expect(switches).toHaveLength(2)
    for (const item of switches) expect(item.attributes('disabled')).toBeDefined()
  })
})
