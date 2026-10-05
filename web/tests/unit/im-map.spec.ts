import { describe, expect, it } from 'vitest'
import { chatMessageFromTim, conversationFromTim } from '@/im/map'
import { ChatMessageKind } from '@/im/types'

const base = {
  ID: 'm1',
  conversationID: 'C2Cu9',
  to: 'u9',
  from: 'u8',
  time: 1700000000,
  status: 'success',
}

describe('chatMessageFromTim', () => {
  it('文本消息:正文在 payload.text', () => {
    const message = chatMessageFromTim({
      ...base,
      type: 'TIMTextElem',
      payload: { text: '你好' },
      flow: 'in',
    })
    expect(message).toMatchObject({
      msgId: 'm1',
      peerId: 'u8',
      isSelf: false,
      kind: ChatMessageKind.text,
      text: '你好',
      timestamp: 1700000000000, // 秒 → 毫秒
    })
  })

  it('自己发的消息:flow 为 out,peerId 取接收者', () => {
    const message = chatMessageFromTim({
      ...base,
      type: 'TIMTextElem',
      payload: { text: '在吗' },
      flow: 'out',
    })
    expect(message.isSelf).toBe(true)
    expect(message.peerId).toBe('u9')
  })

  it('图片消息:从 imageInfoArray 里挑缩略图与原图', () => {
    const message = chatMessageFromTim({
      ...base,
      type: 'TIMImageElem',
      flow: 'in',
      payload: {
        imageInfoArray: [
          { type: 1, url: 'https://cos/origin.jpg' },
          { type: 2, url: 'https://cos/thumb.jpg' },
          { type: 3, url: 'https://cos/large.jpg' },
        ],
      },
    })
    expect(message.kind).toBe(ChatMessageKind.image)
    expect(message.imageUrl).toBe('https://cos/thumb.jpg')
    expect(message.imageLargeUrl).toBe('https://cos/origin.jpg')
  })

  it('图片消息按 sizeType 选图(spike 实测的真实结构)', () => {
    const message = chatMessageFromTim({
      ...base,
      type: 'TIMImageElem',
      flow: 'in',
      payload: {
        imageInfoArray: [
          { sizeType: 1, type: 0, imageUrl: 'https://cos/o.jpg', url: 'https://cos/o-http.jpg' },
          { sizeType: 3, type: 1, imageUrl: '', url: '' }, // 实测里这条就是空的
          { sizeType: 2, type: 2, imageUrl: 'https://cos/t.jpg', url: '' },
        ],
      },
    })
    expect(message.imageUrl).toBe('https://cos/t.jpg')
    expect(message.imageLargeUrl).toBe('https://cos/o.jpg')
  })

  it('系统灰条:自定义消息按 payload.data 里的 type 分流', () => {
    const match = chatMessageFromTim({
      ...base,
      type: 'TIMCustomElem',
      flow: 'in',
      payload: { data: JSON.stringify({ type: 'match_notice', text: '你们已互相喜欢' }) },
    })
    const ban = chatMessageFromTim({
      ...base,
      type: 'TIMCustomElem',
      flow: 'in',
      payload: { data: JSON.stringify({ type: 'ban_notice', text: '账号已被封禁' }) },
    })
    expect(match.kind).toBe(ChatMessageKind.matchNotice)
    expect(match.text).toBe('你们已互相喜欢')
    expect(ban.kind).toBe(ChatMessageKind.banNotice)
  })

  it('配对灰条:后端不带 text,用与 App 相同的固定文案兜底', () => {
    const match = chatMessageFromTim({
      ...base,
      type: 'TIMCustomElem',
      flow: 'in',
      payload: { data: JSON.stringify({ type: 'match_notice' }) },
    })
    expect(match.kind).toBe(ChatMessageKind.matchNotice)
    expect(match.text).toBe('你们已互相喜欢,开始聊天吧')
  })

  it('自定义消息负载坏掉时不抛异常,归为 other', () => {
    const broken = chatMessageFromTim({
      ...base,
      type: 'TIMCustomElem',
      flow: 'in',
      payload: { data: '{不是 JSON' },
    })
    expect(broken.kind).toBe(ChatMessageKind.other)
  })

  it('未知类型归为 other', () => {
    expect(
      chatMessageFromTim({ ...base, type: 'TIMSoundElem', flow: 'in', payload: {} }).kind,
    ).toBe(ChatMessageKind.other)
  })
})

describe('conversationFromTim', () => {
  it('从 C2C 会话 ID 解析出对端 IM id', () => {
    const conversation = conversationFromTim({
      conversationID: 'C2Cu8',
      type: 'C2C',
      unreadCount: 2,
      userProfile: { nick: '小雨', avatar: 'https://cdn/a.jpg' },
      lastMessage: { ...base, type: 'TIMTextElem', payload: { text: '在吗' }, flow: 'in' },
    })
    expect(conversation).toMatchObject({
      peerId: 'u8',
      unreadCount: 2,
      showName: '小雨',
      faceUrl: 'https://cdn/a.jpg',
    })
    expect(conversation?.lastMessage?.text).toBe('在吗')
  })

  it('会话 userProfile 还没填时,用 lastMessage.nick 兜底显示对端昵称', () => {
    // 真机实测:新建会话的 userProfile 可能为空,名字要先落到「u18」再由 SDK 补全,
    // 而 lastMessage.nick 在 C2C 里就是对方的昵称,可以直接用来显示。
    const conversation = conversationFromTim({
      conversationID: 'C2Cu18',
      type: 'C2C',
      unreadCount: 4,
      userProfile: { userID: 'u18', nick: '', avatar: '' },
      lastMessage: {
        ...base,
        nick: '婉婷18',
        avatar: 'https://cdn/p.jpg',
        type: 'TIMTextElem',
        payload: { text: '在吗' },
        flow: 'in',
      },
    })
    expect(conversation).toMatchObject({
      peerId: 'u18',
      showName: '婉婷18',
      faceUrl: 'https://cdn/p.jpg',
    })
  })

  it('非单聊会话被过滤掉(返回 null)', () => {
    expect(conversationFromTim({ conversationID: 'GROUP123', type: 'GROUP', unreadCount: 0 })).toBeNull()
  })
})
