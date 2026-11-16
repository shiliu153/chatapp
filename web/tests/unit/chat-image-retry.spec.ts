/**
 * 图片「重发」的错误与重试口径(#410,对齐 PR #406 的语音)。
 *
 * 要钉的是一句**行为契约**,不是「有没有抛异常」:
 *
 * - 本地 `File` 已失效(刷新 / 换页 / 浏览器回收内存)→ store 必须**抛一句能直接展示的话**
 *   并让界面看得见「不能重试」,绝不能像以前那样静默 `return`
 *   (老代码还会先把气泡从列表里摘掉,表现成「点了重发,气泡消失、什么都没发出去」);
 * - 本地 `File` 还在 → 重新上传,期间气泡回到「发送中」,成功后换成真实消息;
 * - 重新上传又失败 → 回到**可重试**的失败态(不能误标成「已失效」,否则用户再也没机会重试)。
 *
 * 上传本身的错误分类(401 立刻冒泡 / 429 退避)在 `im-image-upload-retry.spec.ts` 里钉。
 */
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { setImClientFactory } from '@/im/client'
import { CHAT_IMAGE_LOCAL_GONE_TEXT } from '@/im/self/image'
import { ChatMessageKind } from '@/im/types'
import { useChatStore } from '@/stores/chat'
import type { ChatMessage, ImClient } from '@/im/types'
import { server } from '../support/server'

/** 一条「发失败」的图片气泡:服务端没有它,本地 `pendingFiles` 里才可能有内容。 */
function imageMsg(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    msgId: 'local-old',
    peerId: 'u8',
    isSelf: true,
    seq: 0,
    timestamp: 1_700_000_000_000,
    kind: ChatMessageKind.image,
    text: '',
    senderName: '',
    senderAvatar: null,
    isPending: false,
    isFailed: true,
    imageUrl: null,
    imageLargeUrl: null,
    isRevoked: false,
    ...overrides,
  }
}

/** 只实现本文件会走到的客户端方法:重发路径需要 `sendImage`,其余给空实现占位。 */
function fakeClient() {
  return {
    capabilities: { image: true, search: true, voice: true, readReceipt: true },
    onEvent: vi.fn(),
    init: vi.fn(async () => {}),
    login: vi.fn(async () => {}),
    logout: vi.fn(async () => {}),
    fetchConversations: vi.fn(async () => []),
    fetchHistory: vi.fn(async () => []),
    searchMessages: vi.fn(async () => ({ items: [], hasMore: false })),
    markConversationRead: vi.fn(async () => {}),
    sendText: vi.fn(async (peerId: string) => imageMsg({ msgId: 'text-real', peerId })),
    sendImage: vi.fn(async (peerId: string) => imageMsg({ msgId: 'img-real', peerId, isFailed: false })),
    sendVoice: vi.fn(),
    sendSticker: vi.fn(),
    deleteMessage: vi.fn(async () => {}),
    deleteMessages: vi.fn(async (ids: string[]) => ids.length),
    revokeMessage: vi.fn(async () => {}),
    deleteConversation: vi.fn(async () => {}),
    setConversationFlags: vi.fn(),
  }
}

describe('图片重发:本地文件失效不再静默 return', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    // 重发前 store 会 `ensureConnected()`:IM 凭证这个接口必须有人应答,
    // 否则 MSW 按 `onUnhandledRequest: 'error'` 让请求失败(真发出去还会等超时)
    server.use(
      mswHttp.post('/api/v1/im/user_sig', () =>
        HttpResponse.json({ im_user_id: 'u9', token: 'tok-410' }),
      ),
    )
  })

  it('文件已失效:抛出可展示的提示,气泡留在原地并标成不可重试', async () => {
    const client = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    // 刷新/换页之后就是这样:失败气泡还在(本单测预置 messages),
    // 但内存里的 File 早就没了 —— 老代码在这里 `return`,界面毫无反应
    store.messages = { u8: [imageMsg()] }
    const failed = store.messagesOf('u8')[0]

    // 核心断言 ①:错误必须冒出来(不再是静默返回)
    await expect(store.resend(failed)).rejects.toThrow(CHAT_IMAGE_LOCAL_GONE_TEXT)
    // 核心断言 ②:气泡没被悄悄摘掉 —— 用户得知道这条没发出去
    const list = store.messagesOf('u8')
    expect(list).toHaveLength(1)
    expect(list[0].msgId).toBe('local-old')
    // 核心断言 ③:标成「不可重试」,界面据此把「重发」按钮换成说明文字
    expect(list[0].localFileGone).toBe(true)
    expect(list[0].isFailed).toBe(true)
    expect(list[0].isPending).toBe(false)
    // 没有文件就压根不该发起上传
    expect(client.sendImage).not.toHaveBeenCalled()
    // 再点一次也还是同一句话(不会变成「什么都不发生」)
    await expect(store.resend(store.messagesOf('u8')[0])).rejects.toThrow('图片已失效')
  })

  it('文件还在:重新上传,上传期间气泡是「发送中」,成功后换成真实消息', async () => {
    const client = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    const file = new File(['a'], 'a.png', { type: 'image/png' })
    store.messages = { u8: [imageMsg()] }
    store.pendingFiles = { 'local-old': file }

    let pendingWhileUploading = false
    client.sendImage = vi.fn(async (peerId: string) => {
      pendingWhileUploading = store
        .messagesOf('u8')
        .some((item) => item.kind === ChatMessageKind.image && item.isPending)
      return imageMsg({ msgId: 'img-real', peerId, isFailed: false })
    })

    await store.resend(store.messagesOf('u8')[0])

    // 界面回到「发送中」态:用户点了重发要看得到反应
    expect(pendingWhileUploading).toBe(true)
    expect(client.sendImage).toHaveBeenCalledWith('u8', file, undefined)
    const list = store.messagesOf('u8')
    expect(list).toHaveLength(1)
    expect(list[0].msgId).toBe('img-real')
    expect(list[0].localFileGone).toBeUndefined()
    // 本地文件改挂到真实 msgId 上:再失败一次仍然点得动「重发」
    expect(store.pendingFiles['img-real']).toBe(file)
    expect(store.pendingFiles['local-old']).toBeUndefined()
  })

  it('重新上传又失败:气泡回到可重试的失败态(不能误标成已失效)', async () => {
    const client = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    const file = new File(['a'], 'a.png', { type: 'image/png' })
    store.messages = { u8: [imageMsg()] }
    store.pendingFiles = { 'local-old': file }
    client.sendImage = vi.fn(async () => Promise.reject(new Error('发送失败,请重试')))

    await expect(store.resend(store.messagesOf('u8')[0])).rejects.toThrow('发送失败')

    const list = store.messagesOf('u8')
    expect(list).toHaveLength(1)
    expect(list[0].isFailed).toBe(true)
    expect(list[0].localFileGone).toBeUndefined()
    // 文件还在缓存里(键 = 新占位 id),所以「重发」按钮必须留着
    expect(Object.values(store.pendingFiles)).toEqual([file])
  })
})
