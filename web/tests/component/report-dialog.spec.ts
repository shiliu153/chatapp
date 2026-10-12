import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ReportDialog from '@/features/moderation/ReportDialog.vue'

describe('ReportDialog', () => {
  it('open 为 false 时不渲染', () => {
    expect(
      mount(ReportDialog, { props: { open: false, target: 'post' } })
        .find('.report-dialog')
        .exists(),
    ).toBe(false)
  })

  it('未选理由时不能提交', async () => {
    const w = mount(ReportDialog, { props: { open: true, target: 'post' } })
    await w.find('.report-dialog__submit').trigger('click')
    expect(w.text()).toContain('请选择举报理由')
    expect(w.emitted('submitted')).toBeUndefined()
  })

  it('选择理由后派发 submitted 并带上类型', async () => {
    const w = mount(ReportDialog, { props: { open: true, target: 'post' } })
    await w.findAll('.report-dialog__reason')[1].trigger('click') // porn
    await w.find('.report-dialog__submit').trigger('click')

    expect(w.emitted('submitted')?.[0]).toEqual(['porn', ''])
  })

  it('可以填补充说明', async () => {
    const w = mount(ReportDialog, { props: { open: true, target: 'user' } })
    await w.findAll('.report-dialog__reason')[0].trigger('click')
    await w.find('textarea').setValue('一直发广告')
    await w.find('.report-dialog__submit').trigger('click')

    expect(w.emitted('submitted')?.[0]).toEqual(['harassment', '一直发广告'])
  })

  it('点取消派发 close', async () => {
    const w = mount(ReportDialog, { props: { open: true, target: 'user' } })
    await w.find('.report-dialog__cancel').trigger('click')
    expect(w.emitted('close')).toHaveLength(1)
  })
})
