/**
 * 会话草稿(批次 T)的存储口径。
 *
 * 重点不是「能存能取」,而是三件容易漏的:**空文本 = 没有草稿**(否则列表会挂一个
 * 点进去什么都没有的「[草稿] 」)、**镜像优先**(清过的键不能再去存储里捞回旧值)、
 * 以及 `localStorage` 抛异常(隐私模式/配额满)时不能把聊天页搞崩。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  clearDraft,
  draftKey,
  hasDraft,
  readDraft,
  resetDrafts,
  saveDraft,
} from '@/features/chat/draft'

describe('会话草稿', () => {
  beforeEach(() => {
    localStorage.clear()
    resetDrafts()
    vi.restoreAllMocks()
  })

  it('键名固定为 chat_draft:{peerId}', () => {
    expect(draftKey('u8')).toBe('chat_draft:u8')
  })

  it('存了就能读回来,并且写进了 localStorage(刷新后还在)', () => {
    saveDraft('u8', '在吗')
    expect(readDraft('u8')).toBe('在吗')
    expect(localStorage.getItem('chat_draft:u8')).toBe('在吗')
    expect(hasDraft('u8')).toBe(true)
  })

  it('没有草稿时读回空串,hasDraft 为 false', () => {
    expect(readDraft('u9')).toBe('')
    expect(hasDraft('u9')).toBe(false)
  })

  it('存空文本(或纯空白)等价于删除:不留「[草稿] 」前缀', () => {
    saveDraft('u8', '打了一半')
    saveDraft('u8', '   ')
    expect(readDraft('u8')).toBe('')
    expect(hasDraft('u8')).toBe(false)
    expect(localStorage.getItem('chat_draft:u8')).toBeNull()
  })

  it('clearDraft 之后不会再从存储里捞回旧值(镜像优先)', () => {
    saveDraft('u8', '旧草稿')
    clearDraft('u8')
    expect(readDraft('u8')).toBe('')
    expect(hasDraft('u8')).toBe(false)
    expect(localStorage.getItem('chat_draft:u8')).toBeNull()
  })

  it('镜像清掉后再读仍为空:存储里确实已经不在了', () => {
    saveDraft('u8', '旧草稿')
    clearDraft('u8')
    resetDrafts()
    expect(readDraft('u8')).toBe('')
  })

  it('另一个标签页写的草稿(镜像里没有)也能读到', () => {
    localStorage.setItem('chat_draft:u42', '别的窗口写的')
    expect(readDraft('u42')).toBe('别的窗口写的')
  })

  it('不改用户的内容:前导空格原样保存', () => {
    saveDraft('u8', '  缩进的一句话')
    expect(localStorage.getItem('chat_draft:u8')).toBe('  缩进的一句话')
  })

  it('localStorage 抛异常(隐私模式)时不影响调用方', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError')
    })
    expect(() => saveDraft('u8', '写不进去')).not.toThrow()
    // 内存镜像仍然可用:本次会话里「[草稿] 」照样该出现
    expect(hasDraft('u8')).toBe(true)
  })

  it('不同会话的草稿互不干扰', () => {
    saveDraft('u8', '给小雨')
    saveDraft('u9', '给小明')
    clearDraft('u8')
    expect(readDraft('u9')).toBe('给小明')
  })
})
