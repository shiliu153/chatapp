import { describe, expect, it } from 'vitest'
import { matchIcebreaker } from '@/features/discovery/icebreaker'

/** 配对那一刻的破冰文案(计划 §2.2):只在配对瞬间展示共同点,聊天页不提示。 */
describe('matchIcebreaker', () => {
  it('有共同标签 → 列出最多 2 个标签并邀请开口', () => {
    expect(
      matchIcebreaker({
        sharedTagNames: ['运动', '电影', '音乐'],
        myCity: '上海',
        peerCity: '上海',
      }),
    ).toBe('你们都喜欢 运动、电影,不如从这儿聊起?')
  })

  it('有共同标签时优先说标签,不再提城市', () => {
    const text = matchIcebreaker({ sharedTagNames: ['运动'], myCity: '上海', peerCity: '上海' })
    expect(text).toBe('你们都喜欢 运动,不如从这儿聊起?')
    expect(text).not.toContain('都在')
  })

  it('无共同标签且同城 → 只提城市', () => {
    expect(matchIcebreaker({ sharedTagNames: [], myCity: '杭州', peerCity: '杭州' })).toBe(
      '你们都在 杭州',
    )
  })

  it('无共同标签且城市为空 → 整行不展示', () => {
    expect(matchIcebreaker({ sharedTagNames: [], myCity: '', peerCity: '' })).toBeNull()
    expect(matchIcebreaker({ sharedTagNames: [], myCity: '杭州', peerCity: '' })).toBeNull()
  })

  it('无共同标签且不同城 → 不替用户断言', () => {
    expect(matchIcebreaker({ sharedTagNames: [], myCity: '杭州', peerCity: '成都' })).toBeNull()
  })

  it('标签名带空白或空串时忽略', () => {
    expect(matchIcebreaker({ sharedTagNames: ['  ', '运动 '] })).toBe(
      '你们都喜欢 运动,不如从这儿聊起?',
    )
  })
})
