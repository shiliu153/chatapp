# 网页端实施计划(三):聊天 / 测试与 CI / 部署文档(16 个任务)

> **For agentic workers:** REQUIRED SUB-SKILL: 用 `executing-plans` **内联**逐任务实现(项目全局约定:superpowers 类任务一律内联执行,不派发子 agent)。进度以本文件的 checkbox 为准。

**前置:** 计划一(`2026-10-05-web-frontend.md`,T1–T3)与计划二(`2026-10-05-web-features.md`,T4/T5/T7/T8)已完成。

**Goal:** 用腾讯云 IM 的**浏览器端无头 SDK** 把聊天跑通(会话列表 + 聊天页 + 图片消息),补齐端到端测试与 CI,并把部署与纪律文档落地。

**Architecture:** `src/im/` 是全项目**唯一** import 腾讯 SDK 的目录(与 App 的 `lib/im/` 同构):`types.ts`(自有类型,SDK 不泄漏到业务层)+ `client.ts`(SDK 适配)+ `map.ts`(纯函数映射,可单测)。业务只认 `stores/chat.ts`。

**Tech Stack:** `@tencentcloud/chat` ^3.6.7(已核对 `index.d.ts`)+ Playwright + GitHub Actions。

## Global Constraints

计划一、计划二的 Global Constraints **全部继续适用**。本计划额外补充(全部来自已核对的 `index.d.ts`):

- **SDK 入口**:`import TencentCloudChat from '@tencentcloud/chat'` → `TencentCloudChat.create({ SDKAppID: number })`;所有 API **平铺在实例上**(`chat.login` / `chat.sendMessage` / `chat.on`…),**没有** `getMessageManager()` 这类分层(我核对了 `declare class ChatSDK`)。
- **事件名以 `TencentCloudChat.EVENT` 为准**,其中最关键的一条:踢下线事件是 **`KICKED_OUT = 'kickedOut'`**,踢出原因在 `TYPES` 里:
  `KICKED_OUT_MULT_DEVICE`(多端)/ `KICKED_OUT_MULT_ACCOUNT`(同端多实例)/ `KICKED_OUT_USERSIG_EXPIRED`(签名过期)/ `KICKED_OUT_REST_API`(服务端 REST 踢人)。**没有** `USER_SIG_EXPIRED` 这个独立事件。
- **消息对象字段**(`export declare interface Message`):`ID` / `type` / `payload`(内容全在 `payload` 里,**不是** Flutter 插件那种 `textElem`/`imageElem` 平铺字段)/ `conversationID` / `to` / `from` / `flow`(`'in'` / `'out'`)/ `time`(**秒**)/ `status`(`'unSend'` / `'success'` / `'fail'`)/ `nick` / `avatar` / `cloudCustomData` / `isRevoked`。
- **会话对象字段**(`export declare interface Conversation`):`conversationID`(格式 `C2C${userID}`、`GROUP${groupID}`、`@TIM#SYSTEM`)/ `type` / `unreadCount` / `lastMessage` / `userProfile` / `isPinned` / `draftText`。
- **图片消息需要注册上传插件**:`registerPlugin` 的文档原文是「Before sending messages, such as image, audio, video, and file messages, the Chat SDK needs to use the upload plugin to upload files to Tencent COS」→ **Task 6.1 必须实测确认这一步与插件包名**。
- **跨栈契约**:IM 账号 = `u{user_id}`;系统通知账号 = `system_notice`(会话 ID 即 `C2Csystem_notice`)。

---

## 组 T6:聊天(8 个任务)

### Task 6.1:IM 通路验证 spike(⚠️ 不通过就停下来找用户)

**Files:** 无(临时验证,产物是**写进本文件「执行记录」的 API 事实清单**;不提交临时代码)

**Interfaces:**
- Consumes: `POST /api/v1/im/user_sig` 的响应(`{ user_sig, sdkappid, im_user_id, expire }`,见 `docs/api/im.md`)。
- Produces:一份事实清单,后续 7 个任务全部以它为准。

**必须逐条实测并在「执行记录」里写下结论(不许写「应该可以」):**

1. `TencentCloudChat.create({ SDKAppID })` 能否创建实例(`SDKAppID` 用接口返回的 `sdkappid`,**注意返回的是字符串,要转数字**)
2. `chat.login({ userID: 'u{user_id}', userSig })` 能否成功;不成功时的 `code` 与 `message` 是什么
3. 监听哪些事件能收到「对方发来的消息」(预期 `TencentCloudChat.EVENT.MESSAGE_RECEIVED`),`event.data` 的**实际数组结构**
4. `chat.createTextMessage({ to, conversationType, payload: { text } })` + `chat.sendMessage(message)` 能否发出
5. **收到的文本消息里,正文到底在哪个字段**(预期 `payload.text`;此条决定 Task 6.3 的映射函数)
6. **图片消息**:`registerPlugin` 需要哪个包、怎么注册;`createImageMessage` 的 `payload` 该传什么(预期 `{ file: File }`);**收到的图片消息里 URL 数组的字段名与 type 取值**(预期 `payload.imageInfoArray`,type 1=原图/2=缩略/3=大图)
7. `chat.getConversationList()` 返回结构;`chat.getMessageList({ conversationID: 'C2Cu9' })` 返回结构
8. `chat.getTotalUnreadMessageCount()` 是否存在且返回数字
9. 同账号在第二个标签页登录时,第一个标签页收到的 `KICKED_OUT` 的**具体原因值**
10. 控制台「在线 Web 实例数」当前值(决定多标签页行为;默认 1)

- [ ] **Step 1:起后端与前端**

```bash
# 终端 1:后端(需要 Redis 在跑)
cd chatapp && python manage.py runserver
# 终端 2:Celery(IM 副作用;Windows 必须 solo)
cd chatapp && python -m celery -A config worker -l info --pool=solo
# 终端 3:前端
cd web && npm run dev
```

- [ ] **Step 2:在浏览器控制台做最小验证**

先登录网页端(`http://localhost:5173/login`,验证码 `123456`),然后在 DevTools 控制台:

```js
// 1) 取 userSig
const sig = await fetch('/api/v1/im/user_sig', {
  method: 'POST',
  headers: { Authorization: `Bearer ${localStorage.getItem('hb.access')}` },
}).then((r) => r.json())
console.log(sig) // 期望 { user_sig, sdkappid: "1400...", im_user_id: "u9", expire }

// 2) 动态加载 SDK(Vite 下用 import;此处只为验证通路)
const mod = await import('/node_modules/.vite/deps/@tencentcloud__chat.js')
const TencentCloudChat = mod.default
const chat = TencentCloudChat.create({ SDKAppID: Number(sig.sdkappid) })
chat.on(TencentCloudChat.EVENT.MESSAGE_RECEIVED, (e) => console.log('RECV', e.data))
await chat.login({ userID: sig.im_user_id, userSig: sig.user_sig })
console.log('ready?', chat.isReady())
```

- [ ] **Step 3:用后端代发一条消息验证收取**

```bash
cd chatapp
python manage.py im_send --from u<你的账号ID> --to u<对方账号ID> --text "spike 测试"
```

Expected: 控制台打印 `RECV [...]`,数组元素里能看到正文**具体在哪个字段**。

- [ ] **Step 4:验证发送**

```js
const msg = chat.createTextMessage({
  to: 'u<对方ID>',
  conversationType: TencentCloudChat.TYPES.CONV_C2C,
  payload: { text: 'spike 发出的消息' },
})
const res = await chat.sendMessage(msg)
console.log('SENT', res)
```

Expected: 对方(用 `im_send` 反向验证或另一个账号登录)能收到。

- [ ] **Step 5:验证图片消息与插件**

```js
// 按实测结果注册上传插件(官方为 @tencentcloud/upload-plugin;若需要则 npm install 后:
// import { plugin } from '@tencentcloud/upload-plugin'
// chat.registerPlugin({ 'cos-js-sdk': plugin })
const file = new File([new Uint8Array([137, 80, 78, 71])], 'x.png', { type: 'image/png' })
const img = chat.createImageMessage({
  to: 'u<对方ID>',
  conversationType: TencentCloudChat.TYPES.CONV_C2C,
  payload: { file },
})
console.log(await chat.sendMessage(img))
```

Expected: 发出成功;收到的图片消息里能找到 URL 数组字段名与 type 取值。**若报错提示缺少上传插件,把插件包名与注册方式写进事实清单。**

- [ ] **Step 6:写事实清单并提交**

把 10 条的实测结论写进本文件「执行记录」,然后:

```bash
git add docs/superpowers/plans/2026-10-05-web-chat-qa.md
git commit -m "docs(web): IM 通路 spike 实测结论"
```

> **不通过的处置**:若登录或收发无法完成(例如体验版限制、SDKAppID 未开通 Web 端),**停下来找用户**,不要在坏地基上继续做完 T6。备选:在腾讯云控制台开通/升级,或回头评估是否放弃 Web 端聊天。

### Task 6.2:IM 类型层与客户端封装

**Files:**
- Create: `web/src/im/types.ts`、`web/src/im/client.ts`
- Test: `web/tests/unit/im-client.spec.ts`

**Interfaces:**
- Consumes: 事实清单(Task 6.1)、`HEARTBEAT` 无关。
- Produces(**业务层只认这些,SDK 类型不泄漏**):

```ts
// im/types.ts
export enum ChatMessageKind { text = 'text', matchNotice = 'matchNotice', banNotice = 'banNotice', image = 'image', other = 'other' }

export interface ChatMessage {
  msgId: string
  peerId: string          // 对端 IM id,如 'u9'
  isSelf: boolean
  timestamp: number       // 毫秒
  kind: ChatMessageKind
  text: string
  isPending: boolean
  isFailed: boolean
  imageUrl: string | null      // 缩略图
  imageLargeUrl: string | null // 原图
}

export interface ImConversation {
  peerId: string
  unreadCount: number
  showName: string
  faceUrl: string | null
  lastMessage: ChatMessage | null
}

export type ImEvent =
  | { type: 'newMessage'; message: ChatMessage }
  | { type: 'conversationsChanged' }
  | { type: 'kickedOffline'; reason: 'multiDevice' | 'multiAccount' | 'sigExpired' | 'restApi' }
  | { type: 'ready' }

export interface ImClient {
  events: ImEvent[]
  onEvent(listener: (event: ImEvent) => void): void
  init(sdkAppId: number): void
  login(userId: string, userSig: string): Promise<void>
  logout(): Promise<void>
  fetchConversations(): Promise<ImConversation[]>
  fetchHistory(peerId: string, count?: number): Promise<ChatMessage[]>
  sendText(peerId: string, text: string): Promise<ChatMessage>
  sendImage(peerId: string, file: File): Promise<ChatMessage>
  deleteMessage(msgId: string): Promise<void>
  markConversationRead(peerId: string): Promise<void>
  deleteConversation(peerId: string): Promise<void>
}
```

- `im/client.ts` 的 `createImClient()` 返回上述接口;内部用一个**结构化最小类型**描述 SDK 实例,不用 `@tencentcloud/chat` 的导出类型(避免其 `.d.ts` 的模块声明风格与 TS 配置打架):

```ts
type TimChat = {
  login(options: { userID: string; userSig: string }): Promise<unknown>
  logout(): Promise<void>
  isReady(): boolean
  on(eventName: string, handler: (event: { data: unknown; name?: string }) => void): void
  off(eventName: string, handler: Function): void
  registerPlugin?(options: Record<string, unknown>): void
  createTextMessage(options: TimMessageOptions): TimMessageLike
  createImageMessage(options: TimMessageOptions): TimMessageLike
  sendMessage(message: TimMessageLike): Promise<unknown>
  deleteMessage(messages: TimMessageLike[]): Promise<unknown>
  getMessageList(options: { conversationID: string; nextReqMessageID?: string }): Promise<{ data: { messageList: TimMessageLike[]; nextReqMessageID?: string } }>
  setMessageRead(options: { conversationID: string }): Promise<unknown>
  getConversationList(): Promise<{ data: { conversationList: TimConversationLike[] } }>
  deleteConversation(options: string | { conversationIDList: string[]; clearHistoryMessage?: boolean }): Promise<unknown>
}
```

- [ ] **Step 1:写失败的测试(用假 SDK,不碰真腾讯云)**

`web/tests/unit/im-client.spec.ts`:

```ts
import { describe, expect, it, vi } from 'vitest'
import { createImClient, type TimChatLike } from '@/im/client'

/** 手写一个最小假 SDK:记录调用、可手动触发事件。 */
function fakeSdk() {
  const handlers = new Map<string, Function[]>()
  const sent: unknown[] = []
  const sdk: TimChatLike = {
    login: vi.fn(async () => ({})),
    logout: vi.fn(async () => {}),
    isReady: () => true,
    on: (name, handler) => {
      handlers.set(name, [...(handlers.get(name) ?? []), handler])
    },
    off: (name, handler) => {
      handlers.set(name, (handlers.get(name) ?? []).filter((h) => h !== handler))
    },
    createTextMessage: ({ payload }) => ({ ID: 'm1', type: 'TIMTextElem', payload, flow: 'out' }),
    createImageMessage: ({ payload }) => ({ ID: 'm2', type: 'TIMImageElem', payload, flow: 'out' }),
    sendMessage: vi.fn(async (message: unknown) => {
      sent.push(message)
      return { data: message }
    }),
    deleteMessage: vi.fn(async () => ({})),
    getMessageList: vi.fn(async () => ({ data: { messageList: [] } })),
    setMessageRead: vi.fn(async () => ({})),
    getConversationList: vi.fn(async () => ({ data: { conversationList: [] } })),
    deleteConversation: vi.fn(async () => ({})),
  }
  return {
    sdk,
    sent,
    emit: (name: string, data: unknown) => handlers.get(name)?.forEach((h) => h({ data, name })),
  }
}

describe('im client', () => {
  it('登录后把新消息转成领域事件', async () => {
    const { sdk, emit } = fakeSdk()
    const client = createImClient({ sdk, events: { messageReceived: 'onMessageReceived' } })
    const events: unknown[] = []
    client.onEvent((e) => events.push(e))

    await client.login('u9', 'sig')
    emit('onMessageReceived', [
      { ID: 'x1', type: 'TIMTextElem', payload: { text: '你好' }, flow: 'in', from: 'u8', to: 'u9', time: 1700000000, status: 'success' },
    ])

    expect(events).toEqual([
      expect.objectContaining({
        type: 'newMessage',
        message: expect.objectContaining({ text: '你好', isSelf: false, peerId: 'u8' }),
      }),
    ])
  })

  it('发文本走 createTextMessage + sendMessage,并返回本端消息', async () => {
    const { sdk, sent } = fakeSdk()
    const client = createImClient({ sdk, events: { messageReceived: 'onMessageReceived' } })

    const message = await client.sendText('u8', '在吗')

    expect(sent).toHaveLength(1)
    expect(message).toMatchObject({ text: '在吗', isSelf: true, peerId: 'u8' })
  })

  it('发图片把 File 交给 SDK(浏览器原生对象,不做路径转换)', async () => {
    const { sdk } = fakeSdk()
    const client = createImClient({ sdk, events: { messageReceived: 'onMessageReceived' } })
    const file = new File(['x'], 'a.png', { type: 'image/png' })

    const message = await client.sendImage('u8', file)

    expect(message.isSelf).toBe(true)
    expect(message.kind).toBe('image')
  })

  it('踢下线事件带上原因', async () => {
    const { sdk, emit } = fakeSdk()
    const client = createImClient({ sdk, events: { kickedOut: 'kickedOut' } })
    const events: { type: string; reason?: string }[] = []
    client.onEvent((e) => events.push(e as never))

    emit('kickedOut', { type: 'multipleDevice' })

    expect(events[0]).toMatchObject({ type: 'kickedOffline', reason: 'multiDevice' })
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/unit/im-client.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现 `im/types.ts` 与 `im/client.ts`**

`im/types.ts`:照抄上面的接口定义(含 `TimMessageLike` / `TimConversationLike` / `TimChatLike` 的结构化最小类型)。

`im/client.ts`(要点):

```ts
import TencentCloudChat from '@tencentcloud/chat'
import { chatMessageFromTim, conversationFromTim } from './map'
import { ChatMessageKind, type ChatMessage, type ImConversation, type ImEvent, type ImClient } from './types'

/** 踢出原因:同端多实例 vs 多端登录,处理方式不同(Task 6.4 会用到)。 */
export function kickReasonOf(raw: unknown): 'multiDevice' | 'multiAccount' | 'sigExpired' | 'restApi' {
  const type = (raw as { type?: string } | null)?.type ?? ''
  if (type === 'multipleDevice') return 'multiDevice'
  if (type === 'multipleAccount') return 'multiAccount'
  if (type === 'userSigExpired') return 'sigExpired'
  return 'restApi'
}

export function createImClient(options?: { sdk?: TimChatLike; events?: EventNames }): ImClient {
  const names = {
    messageReceived: TencentCloudChat.EVENT.MESSAGE_RECEIVED,
    conversationListUpdated: TencentCloudChat.EVENT.CONVERSATION_LIST_UPDATED,
    kickedOut: TencentCloudChat.EVENT.KICKED_OUT,
    ready: TencentCloudChat.EVENT.SDK_READY,
    ...options?.events,
  }
  // 事件名默认取 SDK 常量,测试可注入(见测试里的 events 参数)
  ...
}
```

**实现要求**:
- `createImClient` 支持注入假 SDK 与假事件名(**测试里不 import 真 SDK**)。若 `@tencentcloud/chat` 在 vitest 环境里加载就报错(它依赖浏览器全局),则把 `import TencentCloudChat` 改成**惰性**:在 `createImClient` 未传 `sdk` 时才 `await import('@tencentcloud/chat')`,并把 `createImClient` 的默认路径做成 `async`。
- `sendImage(peerId, file)` 直接传 `{ file }`;若 Task 6.1 实测出别的字段名,以事实清单为准并在此处注释出处。
- `markConversationRead(peerId)` → `chat.setMessageRead({ conversationID: 'C2C' + peerId })`。
- `deleteConversation(peerId)` → `chat.deleteConversation('C2C' + peerId)`。
- `deleteMessage(msgId)` 需要消息对象,故按 `getMessageList` 结果里 `ID` 匹配后调用 `chat.deleteMessage([message])`。

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run tests/unit/im-client.spec.ts && npm run type-check`;Expected: 4 passed

- [ ] **Step 5:提交**

```bash
git add web/src/im web/tests/unit
git commit -m "feat(web): IM 客户端封装(可注入假 SDK)"
```

### Task 6.3:消息映射(纯函数)

**Files:**
- Create: `web/src/im/map.ts`
- Test: `web/tests/unit/im-map.spec.ts`

**Interfaces:**
- Consumes: `im/types.ts`。
- Produces:`chatMessageFromTim(message)`、`conversationFromTim(conversation)`、`SYSTEM_NOTICE_PEER_ID = 'system_notice'`。
- **与 App 的差异**(必须在文件头注释里写清):Web SDK 把内容放在 `message.payload` 里,而 Flutter 插件是 `message.textElem` / `message.imageElem` / `message.customElem` 平铺字段 —— 这也是为什么 App 的 `chatMessageFromSdk` **不能**复用。

- [ ] **Step 1:写失败的测试**

```ts
import { describe, expect, it } from 'vitest'
import { chatMessageFromTim, conversationFromTim } from '@/im/map'
import { ChatMessageKind } from '@/im/types'

const base = { ID: 'm1', conversationID: 'C2Cu9', to: 'u9', from: 'u8', time: 1700000000, status: 'success' }

describe('chatMessageFromTim', () => {
  it('文本消息:正文在 payload.text', () => {
    const message = chatMessageFromTim({ ...base, type: 'TIMTextElem', payload: { text: '你好' }, flow: 'in' })
    expect(message).toMatchObject({
      msgId: 'm1', peerId: 'u8', isSelf: false, kind: ChatMessageKind.text, text: '你好',
      timestamp: 1700000000000, // 秒 → 毫秒
    })
  })

  it('自己发的消息:flow 为 out,peerId 取接收者', () => {
    const message = chatMessageFromTim({ ...base, type: 'TIMTextElem', payload: { text: '在吗' }, flow: 'out' })
    expect(message.isSelf).toBe(true)
    expect(message.peerId).toBe('u9')
  })

  it('图片消息:从 imageInfoArray 里挑缩略图与原图', () => {
    const message = chatMessageFromTim({
      ...base, type: 'TIMImageElem', flow: 'in',
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

  it('系统灰条:自定义消息按 payload.data 里的 type 分流', () => {
    const match = chatMessageFromTim({
      ...base, type: 'TIMCustomElem', flow: 'in',
      payload: { data: JSON.stringify({ type: 'match_notice', text: '你们已互相喜欢' }) },
    })
    const ban = chatMessageFromTim({
      ...base, type: 'TIMCustomElem', flow: 'in',
      payload: { data: JSON.stringify({ type: 'ban_notice', text: '账号已被封禁' }) },
    })
    expect(match.kind).toBe(ChatMessageKind.matchNotice)
    expect(match.text).toBe('你们已互相喜欢')
    expect(ban.kind).toBe(ChatMessageKind.banNotice)
  })

  it('自定义消息负载坏掉时不抛异常,归为 other', () => {
    const broken = chatMessageFromTim({ ...base, type: 'TIMCustomElem', flow: 'in', payload: { data: '{不是 JSON' } })
    expect(broken.kind).toBe(ChatMessageKind.other)
  })

  it('未知类型归为 other', () => {
    expect(chatMessageFromTim({ ...base, type: 'TIMSoundElem', flow: 'in', payload: {} }).kind).toBe(ChatMessageKind.other)
  })
})

describe('conversationFromTim', () => {
  it('从 C2C 会话 ID 解析出对端 IM id', () => {
    const conversation = conversationFromTim({
      conversationID: 'C2Cu8', type: 'C2C', unreadCount: 2,
      userProfile: { nick: '小雨', avatar: 'https://cdn/a.jpg' },
      lastMessage: { ...base, type: 'TIMTextElem', payload: { text: '在吗' }, flow: 'in' },
    })
    expect(conversation).toMatchObject({ peerId: 'u8', unreadCount: 2, showName: '小雨', faceUrl: 'https://cdn/a.jpg' })
    expect(conversation.lastMessage?.text).toBe('在吗')
  })

  it('非单聊会话被过滤掉(返回 null)', () => {
    expect(conversationFromTim({ conversationID: 'GROUP123', type: 'GROUP', unreadCount: 0 })).toBeNull()
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/unit/im-map.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现 `im/map.ts`**

```ts
/**
 * 腾讯云 IM(浏览器端 SDK)对象 → 领域模型。
 *
 * ⚠️ 与 App 的关键差异:Flutter 插件把内容平铺成 message.textElem / imageElem / customElem,
 * 而 Web SDK 统一放在 message.payload 里 —— 所以 App 的 chatMessageFromSdk **不能**复用。
 * 字段位置以 2026-10-05 的 spike 实测为准(见计划三「执行记录」)。
 */
import { ChatMessageKind, type ChatMessage, type ImConversation, type TimConversationLike, type TimMessageLike } from './types'

export const SYSTEM_NOTICE_PEER_ID = 'system_notice'

const NOTICE_TYPES = ['ban_notice', 'ban_lifted', 'report_handled', 'post_commented']

function customTypeOf(payload: unknown): string | null {
  const data = (payload as { data?: unknown } | null)?.data
  if (typeof data !== 'string' || data.length === 0) return null
  try {
    const decoded = JSON.parse(data)
    return typeof decoded?.type === 'string' ? decoded.type : null
  } catch {
    return null
  }
}

function customTextOf(payload: unknown): string {
  const data = (payload as { data?: unknown } | null)?.data
  if (typeof data !== 'string') return ''
  try {
    const decoded = JSON.parse(data)
    return typeof decoded?.text === 'string' ? decoded.text : ''
  } catch {
    return ''
  }
}

/** 按 1=原图 / 2=缩略图 / 3=大图 挑 URL(取值来自 spike 实测)。 */
function pickImageUrl(payload: unknown, wanted: number): string | null {
  const list = (payload as { imageInfoArray?: { type?: number; url?: string }[] } | null)?.imageInfoArray
  const hit = (list ?? []).find((item) => item?.type === wanted && typeof item.url === 'string' && item.url)
  return hit?.url ?? null
}

export function chatMessageFromTim(message: TimMessageLike): ChatMessage {
  const isSelf = message.flow === 'out'
  const peerId = isSelf ? message.to : message.from
  const kind = kindOf(message)

  return {
    msgId: message.ID,
    peerId,
    isSelf,
    timestamp: message.time * 1000, // SDK 是秒
    kind,
    text: kind === ChatMessageKind.text ? String((message.payload as { text?: string })?.text ?? '') : kind === ChatMessageKind.matchNotice || kind === ChatMessageKind.banNotice ? customTextOf(message.payload) : '',
    isPending: message.status === 'unSend',
    isFailed: message.status === 'fail',
    imageUrl: kind === ChatMessageKind.image ? (pickImageUrl(message.payload, 2) ?? pickImageUrl(message.payload, 1)) : null,
    imageLargeUrl: kind === ChatMessageKind.image ? (pickImageUrl(message.payload, 1) ?? pickImageUrl(message.payload, 3)) : null,
  }
}

function kindOf(message: TimMessageLike): ChatMessageKind {
  if (message.type === 'TIMTextElem') return ChatMessageKind.text
  if (message.type === 'TIMImageElem') return ChatMessageKind.image
  if (message.type === 'TIMCustomElem') {
    const type = customTypeOf(message.payload)
    if (type === 'match_notice') return ChatMessageKind.matchNotice
    if (type && NOTICE_TYPES.includes(type)) return ChatMessageKind.banNotice
  }
  return ChatMessageKind.other
}

export function conversationFromTim(conversation: TimConversationLike): ImConversation | null {
  // 只处理单聊:C2C${userID}(system_notice 也是单聊账号)
  if (!conversation.conversationID.startsWith('C2C')) return null
  const peerId = conversation.conversationID.slice(3)
  if (!peerId) return null
  return {
    peerId,
    unreadCount: conversation.unreadCount ?? 0,
    showName: conversation.userProfile?.nick || (peerId === SYSTEM_NOTICE_PEER_ID ? '系统通知' : peerId),
    faceUrl: conversation.userProfile?.avatar || null,
    lastMessage: conversation.lastMessage ? chatMessageFromTim(conversation.lastMessage) : null,
  }
}
```

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 5:提交**

```bash
git add web/src/im web/tests/unit
git commit -m "feat(web): IM 消息与会话映射(纯函数)"
```

### Task 6.4:聊天 store(替换 T3 占位)

**Files:**
- Modify: `web/src/stores/chat.ts`(整体替换占位版)
- Test: `web/tests/unit/chat-store.spec.ts`

**Interfaces:**
- Consumes: `createImClient()`、`im/types.ts`、`useSessionStore()`、`sessionEvents`。
- Produces:state `conversations` / `messages`(`Record<peerId, ChatMessage[]>`,按对端缓存)/ `unreadTotal` / `status: 'idle' | 'connecting' | 'ready' | 'reconnecting' | 'error'`;
  actions `connect()`(取 userSig → login)、`loadConversations()`、`loadHistory(peerId)`、`sendText(peerId, text)`、`sendImage(peerId, file)`、`resend(message)`、`deleteMessage(message)`、`openConversation(peerId)`、`close()`、`deleteConversation(peerId)`、`messagesOf(peerId)`

**测试注入方式(重要)**:Pinia 的 `useXxxStore()` **不接受参数**,所以不能写 `useChatStore({ client })`。改为在 `im/client.ts` 里留一个**工厂注入口**:

```ts
// im/client.ts 追加
let factory: () => ImClient = () => createImClient()
/** 仅供测试替换;生产路径不要调用。 */
export function setImClientFactory(fn: () => ImClient): void {
  factory = fn
}
export function getImClient(): ImClient {
  return factory()
}
```

store 在 setup 里 `const client = getImClient()` 取一次(整个应用共用一个实例);测试在 `useChatStore()` **之前**调 `setImClientFactory(() => fake.client)`。
- **踢下线分流(本任务的核心逻辑,speccorrection)**:

| 原因 | 处置 |
|---|---|
| `multiDevice` / `restApi` / `sigExpired` | 视为**真的被别的设备顶掉**:`sessionEvents.emitKickedOffline()`(触发全屏提示 + 清凭证) |
| `multiAccount`(**同端第二个标签页**) | **只重连 IM,绝不清凭证** —— 否则两个标签页会一起被登出(localStorage 是共享的) |

- [ ] **Step 1:写失败的测试**

```ts
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useChatStore } from '@/stores/chat'
import { setImClientFactory } from '@/im/client'
import { sessionEvents } from '@/api/session-events'
import type { ImEvent } from '@/im/types'

function fakeClient() {
  let listener: ((event: ImEvent) => void) | null = null
  return {
    client: {
      onEvent: (fn: (event: ImEvent) => void) => { listener = fn },
      init: vi.fn(),
      login: vi.fn(async () => {}),
      logout: vi.fn(async () => {}),
      fetchConversations: vi.fn(async () => [
        { peerId: 'u8', unreadCount: 2, showName: '小雨', faceUrl: null, lastMessage: null },
        { peerId: 'system_notice', unreadCount: 1, showName: '系统通知', faceUrl: null, lastMessage: null },
      ]),
      fetchHistory: vi.fn(async () => []),
      sendText: vi.fn(async (peerId: string, text: string) => ({
        msgId: 'm1', peerId, isSelf: true, timestamp: 1, kind: 'text' as const, text,
        isPending: false, isFailed: false, imageUrl: null, imageLargeUrl: null,
      })),
      sendImage: vi.fn(),
      deleteMessage: vi.fn(),
      markConversationRead: vi.fn(async () => {}),
      deleteConversation: vi.fn(async () => {}),
    },
    emit: (event: ImEvent) => listener?.(event),
  }
}

describe('chat store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionEvents._reset()
  })

  it('会话列表:未读合计,系统通知置顶', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as never)
    const store = useChatStore()

    await store.loadConversations()

    expect(store.conversations[0].peerId).toBe('system_notice') // 置顶
    expect(store.unreadTotal).toBe(3)
  })

  it('新消息到达时插入对应会话并累加未读', async () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as never)
    const store = useChatStore()
    await store.loadConversations()

    emit({
      type: 'newMessage',
      message: {
        msgId: 'm9', peerId: 'u9', isSelf: false, timestamp: 2, kind: 'text' as const, text: '在吗',
        isPending: false, isFailed: false, imageUrl: null, imageLargeUrl: null,
      },
    })

    expect(store.messagesOf('u9').map((m) => m.msgId)).toEqual(['m9'])
  })

  it('多端被顶 → 触发会话失效(全屏提示)', async () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as never)
    const expired = vi.fn()
    sessionEvents.onKickedOffline(expired)
    useChatStore()

    emit({ type: 'kickedOffline', reason: 'multiDevice' })

    expect(expired).toHaveBeenCalledTimes(1)
  })

  it('同端第二个标签页被顶 → 不清凭证,只重连(否则两个标签页一起掉线)', async () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as never)
    const expired = vi.fn()
    sessionEvents.onKickedOffline(expired)
    const store = useChatStore()

    emit({ type: 'kickedOffline', reason: 'multiAccount' })

    expect(expired).not.toHaveBeenCalled()
    expect(store.status).toBe('reconnecting')
  })

  it('打开会话即清未读', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as never)
    const store = useChatStore()
    await store.loadConversations()

    await store.openConversation('u8')

    expect(client.markConversationRead).toHaveBeenCalledWith('u8')
    expect(store.conversations.find((c) => c.peerId === 'u8')?.unreadCount).toBe(0)
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/unit/chat-store.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现(要点)**

- store 工厂接收可选的 `{ client }` 以便测试注入(生产路径用 `createImClient()`);`defineStore` 的 setup 里读注入或建默认。
- `conversations` 排序:**`system_notice` 永远第一**,其余按 `lastMessage.timestamp` 倒序。
- `unreadTotal` = 所有会话 `unreadCount` 之和。
- `connect()`:调 `POST /im/user_sig` 拿 `{ user_sig, sdkappid, im_user_id }` → `client.init(Number(sdkappid))` → `client.login(im_user_id, user_sig)`;403(重封禁)时**不重试**,交守卫处理。
- `openConversation(peerId)`:加载历史(若未加载)→ `markConversationRead` → 本地把该会话未读清零。
- `close()`:`client.logout()`(退出登录时在 `SettingsPage` 里先调它,兑现 Task 8.1 的 TODO)。

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 5:把 Task 8.1 的 TODO 兑现**

`SettingsPage.vue` 的 `onLogout` 改为先 `await useChatStore().close().catch(() => {})` 再 `session.logout()`,并删掉那行 TODO 注释。

- [ ] **Step 6:提交**

```bash
git add web/src/stores web/src/features/settings web/tests/unit
git commit -m "feat(web): 聊天 store(踢下线分流:同端多实例不清凭证)"
```

### Task 6.5:消息页(会话列表)

**Files:**
- Modify: `web/src/features/chat/ChatsPage.vue`(替换空壳)
- Test: `web/tests/component/chats-page.spec.ts`

**Interfaces:**
- Consumes: `useChatStore()`、`usePresenceStore().track('chats', ids)`、`AppAvatar` / `AppBadge` / `AppSkeleton` / `AppEmpty` / `AppErrorView`。
- Produces:`ChatsPage`(路由 `/home/chats`):四态(骨架/空/错误重试/正常)+ **最近联系人横滑条** + 系统通知行置顶 + 未读角标 + 在线光。

- [ ] **Step 1:写失败的测试**

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ChatsPage from '@/features/chat/ChatsPage.vue'
import { useChatStore } from '@/stores/chat'

function stubChatStore(conversations: unknown[], status = 'ready') {
  const store = useChatStore()
  store.conversations = conversations as never
  store.status = status as never
  return store
}

function mountPage() {
  return mount(ChatsPage, {
    global: { plugins: [createPinia()], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
}

describe('ChatsPage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('没有会话时展示空态', async () => {
    stubChatStore([])
    const w = mountPage()
    await flushPromises()
    expect(w.find('.app-empty').exists()).toBe(true)
  })

  it('系统通知置顶并显示未读角标', async () => {
    stubChatStore([
      { peerId: 'system_notice', unreadCount: 1, showName: '系统通知', faceUrl: null, lastMessage: null },
      { peerId: 'u8', unreadCount: 2, showName: '小雨', faceUrl: null, lastMessage: null },
    ])
    const w = mountPage()
    await flushPromises()

    const rows = w.findAll('.chats__row')
    expect(rows[0].text()).toContain('系统通知')
    expect(rows[0].find('.app-badge').text()).toBe('1')
  })

  it('加载中展示骨架', async () => {
    stubChatStore([], 'loading')
    const w = mountPage()
    await flushPromises()
    expect(w.find('.app-skeleton').exists()).toBe(true)
  })

  it('出错时给出重试入口', async () => {
    const store = stubChatStore([], 'error')
    store.loadConversations = vi.fn(async () => {})
    const w = mountPage()
    await flushPromises()

    expect(w.find('.app-error').exists()).toBe(true)
    await w.find('.app-error button').trigger('click')
    expect(store.loadConversations).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/component/chats-page.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现**

要点:`onMounted` 时 `store.connect()`(幂等)→ `loadConversations()`;`store.status` 驱动四态;列表行显示头像(带在线光)、昵称、最后一条消息摘要、时间与未读角标;顶部横滑条只显示最近 10 个会话。点击行 → `router.push({ name: 'chat', params: { peerId } })`。

> 由于 `store.connect()` 会真的连腾讯云,组件测试里统一 `vi.spyOn(store, 'connect').mockResolvedValue()`。

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 5:提交**

```bash
git add web/src/features/chat web/tests/component
git commit -m "feat(web): 消息页(四态/通知置顶/横滑条/未读)"
```

### Task 6.6:聊天页(历史 / 气泡 / 发送 / 时间条)

**Files:**
- Modify: `web/src/features/chat/ChatPage.vue`(替换空壳)
- Create: `web/src/features/chat/MessageBubble.vue`、`web/src/features/chat/time.ts`
- Test: `web/tests/unit/chat-time.spec.ts`、`web/tests/component/chat-page.spec.ts`

**Interfaces:**
- Consumes: `useChatStore()`、`AppAvatar`、`AppButton`、`AppInput`。
- Produces:
  - `time.ts`:`shouldShowTime(prevMs: number | null, currentMs: number): boolean`(**间隔 > 5 分钟**才插时间条,与 App 一致)+ `formatTime(ms)` —— **纯函数单测**
  - `MessageBubble.vue`:props `{ message: ChatMessage; peerName?: string }`;系统灰条(`matchNotice` / `banNotice`)渲染成居中 pill;自己消息 = brand 实底白字(渐变的**唯一**高音),对方 = 白底;圆角 `--radius-bubble`
  - `ChatPage.vue`(路由 `/chat/:peerId`):按 `peerId` 拉历史、倒序渲染、回车发送、失败重发

- [ ] **Step 1:写失败的时间条测试**

`web/tests/unit/chat-time.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { formatTime, shouldShowTime } from '@/features/chat/time'

const MINUTE = 60_000

describe('shouldShowTime', () => {
  it('第一条消息总是显示时间', () => {
    expect(shouldShowTime(null, 1_700_000_000_000)).toBe(true)
  })

  it('间隔 5 分钟内不插时间条', () => {
    const t = 1_700_000_000_000
    expect(shouldShowTime(t, t + 4 * MINUTE)).toBe(false)
  })

  it('间隔正好 5 分钟不插(严格大于才插)', () => {
    const t = 1_700_000_000_000
    expect(shouldShowTime(t, t + 5 * MINUTE)).toBe(false)
  })

  it('超过 5 分钟插时间条', () => {
    const t = 1_700_000_000_000
    expect(shouldShowTime(t, t + 5 * MINUTE + 1)).toBe(true)
  })
})

describe('formatTime', () => {
  it('当天只显示时分', () => {
    const now = new Date('2026-10-05T20:30:00')
    expect(formatTime(new Date('2026-10-05T09:05:00').getTime(), now)).toBe('09:05')
  })

  it('非当天显示月日时分', () => {
    const now = new Date('2026-10-05T20:30:00')
    expect(formatTime(new Date('2026-10-04T09:05:00').getTime(), now)).toBe('10-04 09:05')
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/unit/chat-time.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现 `time.ts`**

```ts
const FIVE_MINUTES = 5 * 60 * 1000

/** 两条消息间隔 > 5 分钟时插入时间条(与 App 一致)。 */
export function shouldShowTime(prevMs: number | null, currentMs: number): boolean {
  if (prevMs === null) return true
  return currentMs - prevMs > FIVE_MINUTES
}

const pad = (n: number) => String(n).padStart(2, '0')

/** 当天只到分钟;跨天带上月日。 */
export function formatTime(ms: number, now: Date = new Date()): string {
  const date = new Date(ms)
  const hm = `${pad(date.getHours())}:${pad(date.getMinutes())}`
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  return sameDay ? hm : `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${hm}`
}
```

- [ ] **Step 4:写聊天页组件测试**

`web/tests/component/chat-page.spec.ts`:

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ChatPage from '@/features/chat/ChatPage.vue'
import { useChatStore } from '@/stores/chat'

function msg(overrides: Record<string, unknown> = {}) {
  return {
    msgId: 'm1', peerId: 'u8', isSelf: false, timestamp: 1_700_000_000_000, kind: 'text' as const,
    text: '你好', isPending: false, isFailed: false, imageUrl: null, imageLargeUrl: null, ...overrides,
  }
}

function mountPage(messages = [msg()]) {
  const store = useChatStore()
  store.messages = { u8: messages } as never
  store.sendText = vi.fn(async () => {})
  const w = mount(ChatPage, {
    props: { peerId: 'u8' },
    global: { plugins: [createPinia()], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
  return { w, store }
}

describe('ChatPage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('渲染气泡与文本', async () => {
    const { w } = mountPage()
    await flushPromises()
    expect(w.findAll('.message-bubble')).toHaveLength(1)
    expect(w.text()).toContain('你好')
  })

  it('系统灰条渲染成居中 pill', async () => {
    const { w } = mountPage([msg({ kind: 'matchNotice', text: '你们已互相喜欢' })])
    await flushPromises()
    expect(w.find('.message-bubble--notice').exists()).toBe(true)
  })

  it('发送后清空输入框', async () => {
    const { w, store } = mountPage()
    await flushPromises()

    await w.find('input[type="text"]').setValue('在吗')
    await w.find('.chat__send').trigger('click')
    await flushPromises()

    expect(store.sendText).toHaveBeenCalledWith('u8', '在吗')
    expect((w.find('input[type="text"]').element as HTMLInputElement).value).toBe('')
  })

  it('失败的消息可重发', async () => {
    const { w, store } = mountPage([msg({ isFailed: true })])
    store.resend = vi.fn(async () => {})
    await flushPromises()

    await w.find('.message-bubble__retry').trigger('click')
    expect(store.resend).toHaveBeenCalled()
  })
})
```

- [ ] **Step 5:实现 `MessageBubble.vue` 与 `ChatPage.vue`**

实现要点:
- 自己的气泡:背景 `var(--gradient-heart)`、白字、右下角(上角 6px)圆角;对方:白底 `--color-bg-card`、`--radius-bubble`;
- 最大宽 `var(--bubble-max-ratio)`(72%,天然自适应),**不写死像素**;
- `kind === 'other'` 显示「[暂不支持的消息类型]」占位,不渲染空白;
- 图片消息渲染 `<img :src="message.imageUrl">`,点击打开灯箱(Task 6.7);
- 失败消息右下角显示重发按钮(`.message-bubble__retry`);
- 输入框回车发送,空内容不发;发送中禁用。

- [ ] **Step 6:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 7:提交**

```bash
git add web/src/features/chat web/tests
git commit -m "feat(web): 聊天页(历史/气泡/时间条/发送/重发)"
```

### Task 6.7:图片消息与灯箱

**Files:**
- Create: `web/src/features/chat/MessageImage.vue`、`web/src/features/chat/ImageViewer.vue`
- Modify: `web/src/features/chat/ChatPage.vue`(选图发送 + 灯箱接线)
- Test: `web/tests/component/image-viewer.spec.ts`

**Interfaces:**
- Consumes: `useChatStore().sendImage(peerId, file)`、`MessageBubble`。
- Produces:
  - `MessageImage.vue`:props `{ message: ChatMessage }`;发送中显示占位骨架,加载失败显示兜底
  - `ImageViewer.vue`:props `{ urls: string[]; index: number }`;emits `close`;**点遮罩或 `Esc` 关闭**(spec §6.4)

- [ ] **Step 1:写失败的测试**

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ImageViewer from '@/features/chat/ImageViewer.vue'

describe('ImageViewer', () => {
  it('渲染当前图片', () => {
    const w = mount(ImageViewer, { props: { urls: ['https://cos/a.jpg', 'https://cos/b.jpg'], index: 1 } })
    expect(w.find('.image-viewer__img').attributes('src')).toBe('https://cos/b.jpg')
  })

  it('点遮罩关闭', async () => {
    const w = mount(ImageViewer, { props: { urls: ['https://cos/a.jpg'], index: 0 } })
    await w.find('.image-viewer__mask').trigger('click')
    expect(w.emitted('close')).toHaveLength(1)
  })

  it('按 Esc 关闭', async () => {
    const w = mount(ImageViewer, { props: { urls: ['https://cos/a.jpg'], index: 0 }, attachTo: document.body })
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(w.emitted('close')).toHaveLength(1)
    w.unmount()
  })

  it('点图片本身不关闭(避免手滑)', async () => {
    const w = mount(ImageViewer, { props: { urls: ['https://cos/a.jpg'], index: 0 } })
    await w.find('.image-viewer__img').trigger('click')
    expect(w.emitted('close')).toBeUndefined()
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/component/image-viewer.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现**

`ImageViewer.vue` 要点:全屏遮罩 `--color-photo-scrim`;`onMounted` 注册 `keydown`、`onUnmounted` 移除;`.image-viewer__mask` 覆盖整屏且**在图片之下**(`z-index` 分层),这样点图片不会冒泡到遮罩。

`MessageImage.vue` 要点:`isPending` 时用 `URL.createObjectURL(file)` 的本地预览(发送前);发送成功后改用 `message.imageUrl`;**`<img>` 失败时 `@error` 切兜底占位**。

`ChatPage.vue` 接线:`<input type="file" accept="image/*">` 选图 → 立即本地预览上屏 → `store.sendImage(peerId, file)`;点击图片 → `viewer = { urls, index }`。

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 5:真机目检(要两个账号)**

Run: 两个浏览器窗口分别登录不同账号 → 互相配对 → 互发文本与图片
Expected: 图片能发能收能全屏;`Esc` 与点遮罩都能关。

- [ ] **Step 6:提交**

```bash
git add web/src/features/chat web/tests/component
git commit -m "feat(web): 图片消息与灯箱(Esc/点遮罩关闭)"
```

### Task 6.8:表情面板与消息菜单(悬停 ⋯ / 右键)

**Files:**
- Create: `web/src/features/chat/EmojiPanel.vue`、`web/src/features/chat/MessageMenu.vue`
- Modify: `web/src/features/chat/ChatPage.vue`(接线)
- Test: `web/tests/component/message-menu.spec.ts`

**Interfaces:**
- Consumes: `useChatStore().deleteMessage` / `resend`。
- Produces:
  - `EmojiPanel.vue`:固定一组表情(与 App 的面板一致即可,不引入第三方库);点选后插入输入框;`Esc` 或再点按钮收起
  - `MessageMenu.vue`:props `{ message: ChatMessage; x: number; y: number }`;emits `close` / `action: ['copy' | 'delete' | 'retry']`;**悬停 ⋯ 按钮与右键菜单是两个入口、同一个组件**(spec §6.4)

- [ ] **Step 1:写失败的测试**

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MessageMenu from '@/features/chat/MessageMenu.vue'

const message = {
  msgId: 'm1', peerId: 'u8', isSelf: true, timestamp: 1, kind: 'text' as const, text: '你好',
  isPending: false, isFailed: false, imageUrl: null, imageLargeUrl: null,
}

describe('MessageMenu', () => {
  it('自己的文本消息:可复制、可删除', async () => {
    const w = mount(MessageMenu, { props: { message, x: 10, y: 10 } })
    expect(w.text()).toContain('复制')
    expect(w.text()).toContain('删除')

    await w.find('.message-menu__copy').trigger('click')
    expect(w.emitted('action')?.[0]).toEqual(['copy'])
  })

  it('对方的消息:不提供删除', () => {
    const w = mount(MessageMenu, { props: { message: { ...message, isSelf: false }, x: 0, y: 0 } })
    expect(w.find('.message-menu__delete').exists()).toBe(false)
  })

  it('失败的消息:提供重发', () => {
    const w = mount(MessageMenu, { props: { message: { ...message, isFailed: true }, x: 0, y: 0 } })
    expect(w.find('.message-menu__retry').exists()).toBe(true)
  })

  it('按 Esc 关闭', async () => {
    const w = mount(MessageMenu, { props: { message, x: 0, y: 0 }, attachTo: document.body })
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(w.emitted('close')).toHaveLength(1)
    w.unmount()
  })
})
```

- [ ] **Step 2:跑测试确认失败** → Run: `cd web && npm run test:run tests/component/message-menu.spec.ts`;Expected: FAIL

- [ ] **Step 3:实现并接线**

要点:菜单用 `position: fixed` + `left/top`(来自事件坐标),**靠近右/下边缘时向内收**(用 `Math.min(x, window.innerWidth - 160)`);`copy` 用 `navigator.clipboard.writeText(message.text)` 并提示「已复制」;`delete` 调 `store.deleteMessage`;`retry` 调 `store.resend`。聊天页给每条气泡绑定 `@contextmenu.prevent` 与悬停按钮。

- [ ] **Step 4:跑测试确认通过** → Run: `cd web && npm run test:run && npm run type-check`;Expected: 全绿

- [ ] **Step 5:提交**

```bash
git add web/src/features/chat web/tests/component
git commit -m "feat(web): 表情面板与消息菜单(悬停/右键同一组件)"
```

**▶ 组 T6 检查点**:门禁全绿;两个账号真机互发文本与图片;被顶号全屏提示;第二个标签页登录**不会**把第一个标签页登出(踢出类型分流生效)。

---

## 组 T9:测试补齐 / 端到端 / CI(5 个任务)

### Task 9.1:覆盖率门槛与缺口补齐

**Files:**
- Modify: `web/vitest.config.ts`(加 coverage 配置)、`web/package.json`(加 `test:coverage` 脚本)
- Test: 补写缺失用例(按下表)

**Interfaces:**
- Consumes: 全量已有测试。
- Produces:`npm run test:coverage` 可跑,阈值门槛生效。

**先跑一次覆盖率,看缺口在哪**:

```bash
cd web && npm run test:coverage
```

- [ ] **Step 1:装覆盖率依赖并配置**

```bash
cd web && npm install -D @vitest/coverage-v8
```

`vitest.config.ts` 的 `test` 增加:

```ts
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      include: ['src/**/*.{ts,vue}'],
      exclude: ['src/features/dev/**', 'src/main.ts'],
      thresholds: { lines: 70, functions: 70, branches: 60, statements: 70 },
    },
```

`package.json` 脚本加 `"test:coverage": "vitest run --coverage"`。

- [ ] **Step 2:补齐以下必测清单(缺哪补哪)**

| 模块 | 必测行为 |
|---|---|
| `api/http.ts` | 401 刷新重放、并发去重、刷新失败清凭证、40101 不清凭证只提示 |
| `api/error.ts` | 信封解析、非信封降级、网络异常、`Retry-After` |
| `stores/session.ts` | 登录/登出/恢复/被顶 |
| `stores/profile.ts` | 缺项文案、封禁判定、照片增删 |
| `stores/discovery.ts` | 403 停住 / 404 跳过 / 429 提示 / 配对 |
| `stores/feed.ts` | 分页追加、点赞乐观与回滚、发布插入 |
| `stores/presence.ts` | 合并去重、100 分片、45 秒周期、隐藏暂停 |
| `stores/chat.ts` | 未读合计、通知置顶、**踢下线分流** |
| `im/map.ts` | 文本/图片/灰条/坏负载 |
| `features/chat/time.ts` | 5 分钟边界 |
| `features/discovery/swipe.ts` | 阈值边界 |
| `layout.ts` | 默认宽度夹取、拖拽夹取、持久化、复位 |
| `constants.ts` | `APP_NAME`、`DOWNLOADS_ENABLED` |
| token 对照 | Dart ↔ CSS 数值一致;字体哈希一致 |

- [ ] **Step 3:跑到门槛以上并提交**

Run: `cd web && npm run test:coverage`
Expected: 四个阈值全部通过(不通过就把缺口补到通过,**不要**为了过而调低阈值;若确有必要调整,先找用户确认)

```bash
git add web/vitest.config.ts web/package.json web/package-lock.json web/tests
git commit -m "test(web): 覆盖率门槛与缺口补齐"
```

### Task 9.2:Playwright 配置

**Files:**
- Create: `web/playwright.config.ts`
- Modify: `web/vite.config.ts`(**加 `preview.proxy`** —— 关键:`vite preview` 不继承 `server.proxy`,不加就是跨域失败)、`web/package.json`(加 `e2e` 脚本)、`web/.gitignore`(`test-results/`、`playwright-report/`)

**Interfaces:**
- Consumes: `npm run build` 产物。
- Produces:`npm run e2e` 跑端到端;默认打**真后端** `http://127.0.0.1:8000`。

- [ ] **Step 1:补 `preview.proxy`**

`vite.config.ts` 增加(与 `server.proxy` 相同的两条规则):

```ts
  preview: {
    port: 4173,
    proxy: {
      '/api/v1': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/media': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
```

- [ ] **Step 2:写 `playwright.config.ts`**

```ts
import { defineConfig, devices } from '@playwright/test'

const PORT = 4173

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 60_000,
  fullyParallel: false, // 场景之间有账号与配对状态依赖,串行更稳
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'npm run build && npm run preview',
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
})
```

`package.json` 脚本加 `"e2e": "playwright test"`。

- [ ] **Step 3:写账号辅助(两个账号互滑要用)**

`web/tests/e2e/support/account.ts`:

```ts
import { writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { Page } from '@playwright/test'

/** 1×1 PNG(测试用照片,免去往仓库塞二进制)。 */
const PNG_BASE64 =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='

export function fixturePhoto(): string {
  const path = join(tmpdir(), `hb-e2e-${Date.now()}.png`)
  writeFileSync(path, Buffer.from(PNG_BASE64, 'base64'))
  return path
}

/** 用手机号 + 开发期固定验证码登录(未注册自动建号)。 */
export async function login(page: Page, phone: string): Promise<void> {
  await page.goto('/login')
  await page.getByPlaceholder('手机号').fill(phone)
  await page.getByRole('button', { name: /获取验证码/ }).click()
  await page.getByPlaceholder('6 位验证码').fill('123456')
  await page.getByRole('button', { name: '登录' }).click()
}

/** 走完「完善资料」:昵称/性别/生日/城市 + 一张照片。 */
export async function completeProfile(page: Page, nickname: string): Promise<void> {
  await page.getByPlaceholder('昵称').fill(nickname)
  await page.getByRole('button', { name: '女生' }).click()
  await page.locator('input[type="date"]').fill('2000-01-01')
  await page.getByPlaceholder('城市').fill('上海')
  await page.locator('input[type="file"]').setInputFiles(fixturePhoto())
  await page.getByRole('button', { name: '开始使用' }).click()
}

/** 每次运行用不同号段,避免历史数据(划过/配对)干扰。 */
export function freshPhone(suffix: number): string {
  const tail = String(Date.now()).slice(-6)
  return `139${tail}${suffix}`
}
```

- [ ] **Step 4:冒烟一条并提交**

```ts
// web/tests/e2e/smoke.spec.ts
import { expect, test } from '@playwright/test'

test('首屏能打开且是中文界面', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByText('心跳')).toBeVisible()
})
```

Run(先起后端 + Redis + Celery):`cd web && npm run e2e`
Expected: 1 passed

```bash
git add web/playwright.config.ts web/vite.config.ts web/package.json web/tests/e2e
git commit -m "test(web): Playwright 配置与端到端辅助"
```

### Task 9.3:主干场景端到端

**Files:**
- Create: `web/tests/e2e/main-flow.spec.ts`
- Test: 本文件即测试

**Interfaces:**
- Consumes: `support/account.ts`。
- Produces:一条跑通「登录 → 完善资料 → 滑卡 → 互喜配对 → 聊天(文本+图片)→ 广场发布与评论 → 拉黑」的脚本。

- [ ] **Step 1:写脚本**

```ts
import { expect, test } from '@playwright/test'
import { completeProfile, fixturePhoto, freshPhone, login } from './support/account'

test('主干流程:注册 → 配对 → 聊天 → 广场 → 拉黑', async ({ browser }) => {
  const phoneA = freshPhone(1)
  const phoneB = freshPhone(2)

  const contextA = await browser.newContext()
  const contextB = await browser.newContext()
  const pageA = await contextA.newPage()
  const pageB = await contextB.newPage()

  // 1) 两个账号各自登录并完善资料
  await login(pageA, phoneA)
  await completeProfile(pageA, '阿泽')
  await login(pageB, phoneB)
  await completeProfile(pageB, '小雨')

  // 2) B 喜欢 A(先让 B 划一次),A 再喜欢 B → 配对成功
  await pageB.goto('/home/discovery')
  await pageB.locator('.swipe-deck__like').click()
  await expect(pageB.locator('.match-moment')).toBeVisible()

  await pageA.goto('/home/discovery')
  await expect(pageA.getByText('小雨')).toBeVisible({ timeout: 15_000 })
  await pageA.locator('.swipe-deck__like').click()
  await expect(pageA.locator('.match-moment')).toBeVisible()

  // 3) 从配对情感时刻进聊天并发一条文本
  await pageA.getByRole('link', { name: '去聊天' }).click()
  await pageA.locator('input[type="text"]').fill('你好呀')
  await pageA.locator('.chat__send').click()
  await expect(pageA.locator('.message-bubble').last()).toContainText('你好呀')

  // 4) B 能收到
  await pageB.goto('/home/chats')
  await expect(pageB.locator('.chats__row').first()).toContainText('阿泽')
  await pageB.locator('.chats__row').first().click()
  await expect(pageB.locator('.message-bubble').last()).toContainText('你好呀', { timeout: 15_000 })

  // 5) 发图片
  await pageB.locator('input[type="file"]').setInputFiles(fixturePhoto())
  await expect(pageB.locator('.message-image img')).toBeVisible({ timeout: 20_000 })

  // 6) 广场:发一条带图动态并评论
  await pageA.goto('/home/square')
  await pageA.getByRole('button', { name: '发动态' }).click()
  await pageA.locator('textarea').fill('第一条动态')
  await pageA.getByRole('button', { name: '发布' }).click()
  await expect(pageA.locator('.post-card').first()).toContainText('第一条动态')

  // 7) 拉黑 B
  await pageA.locator('.post-card').first().getByText('小雨').click()
  pageA.on('dialog', (d) => d.accept())
  await pageA.locator('.user-profile__block').click()
  await expect(pageA.getByText('已拉黑')).toBeVisible()

  await contextA.close()
  await contextB.close()
})
```

- [ ] **Step 2:跑通并提交**

Run(前置:Redis + `python manage.py runserver` + Celery worker):`cd web && npm run e2e`
Expected: 1 passed。**失败时读 `playwright-report/` 里的 trace**,不要靠猜。

```bash
git add web/tests/e2e
git commit -m "test(web): 主干流程端到端脚本"
```

### Task 9.4:边界场景端到端

**Files:**
- Create: `web/tests/e2e/edge-cases.spec.ts`
- Test: 本文件即测试

**Interfaces:**
- Consumes: `support/account.ts`。
- Produces:覆盖 spec §16 的边界项。

- [ ] **Step 1:写脚本**

```ts
import { expect, test } from '@playwright/test'
import { completeProfile, freshPhone, login } from './support/account'

test('深链直开与 F5 不 404', async ({ page }) => {
  const phone = freshPhone(3)
  await login(page, phone)
  await completeProfile(page, '深链')

  await page.goto('/home/square')
  await page.reload()
  await expect(page.locator('.square__title')).toBeVisible()

  await page.goto('/settings')
  await expect(page.locator('.settings__title')).toBeVisible()
})

test('中文渲染正常(不是空白也不是方块)', async ({ page }) => {
  await page.goto('/legal/privacy')
  const text = await page.locator('.legal__body').innerText()
  expect(text).toMatch(/[\u4e00-\u9fa5]/) // 含中文
  expect(text.length).toBeGreaterThan(200)
})

test('窗口拖窄仍是 PC 壳层(不是移动端引导页)', async ({ page }) => {
  const phone = freshPhone(4)
  await login(page, phone)
  await completeProfile(page, '窄窗')

  await page.setViewportSize({ width: 700, height: 800 })
  await page.goto('/home/discovery')
  await expect(page.locator('.app-sidebar')).toBeVisible()
  await expect(page.getByText('请在电脑上打开网页版')).toHaveCount(0)
})

test('移动端 UA 进引导页,下载按钮为敬请期待', async ({ browser }) => {
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15',
    viewport: { width: 390, height: 844 },
  })
  const page = await context.newPage()
  await page.goto('/home/discovery')

  await expect(page.getByText('请在电脑上打开网页版')).toBeVisible()
  await expect(page.getByRole('button', { name: /敬请期待/ })).toBeDisabled()
  await context.close()
})

test('未同意协议时首启弹窗出现', async ({ page }) => {
  await page.goto('/login')
  await page.evaluate(() => localStorage.clear())
  await page.reload()
  await expect(page.locator('.legal-gate')).toBeVisible()
})

test('第二个标签页登录不会把第一个标签页登出(同端多实例分流)', async ({ context, page }) => {
  const phone = freshPhone(5)
  await login(page, phone)
  await completeProfile(page, '多标签')
  await expect(page.locator('.app-sidebar')).toBeVisible()

  const second = await context.newPage() // 同一 context = 共享 localStorage
  await second.goto('/home/chats')
  await second.waitForTimeout(3_000)

  // 第一个标签页仍应处于登录态:地址栏没有跳回 /login,也没有被顶号浮层
  await expect(page.locator('.kicked-overlay')).toHaveCount(0)
  expect(new URL(page.url()).pathname).not.toBe('/login')
  await second.close()
})
```

- [ ] **Step 2:跑通并提交**

Run: `cd web && npm run e2e`
Expected: 6 passed。**「多标签」这条若失败**:说明踢出类型没分流对,回 Task 6.4 修 `kickReasonOf` 的映射(这是 spec 修正里的关键行为,不能靠放宽断言糊过去)。

```bash
git add web/tests/e2e
git commit -m "test(web): 边界场景端到端(深链/中文/窄窗/UA/多标签)"
```

### Task 9.5:CI

**Files:**
- Create: `.github/workflows/web.yml`
- Test: 推分支后看 Actions 结果

**Interfaces:**
- Consumes: 计划一定义的脚本。
- Produces:前端 CI 四件事:类型检查、lint、单测、构建。

- [ ] **Step 1:写 workflow(照 `.github/workflows/app.yml` 的风格)**

```yaml
name: Web (Vue)

on:
  push:
    branches: [master, main]
    paths:
      - 'web/**'
      - '.github/workflows/web.yml'
  pull_request:
    paths:
      - 'web/**'
      - '.github/workflows/web.yml'
  workflow_dispatch:

jobs:
  # 端到端要真后端 + Redis + 腾讯云,不进 CI;CI 只守类型/规范/单测/构建
  check:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: web
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: npm
          cache-dependency-path: web/package-lock.json

      - name: 拉依赖
        run: npm ci

      - name: 类型检查(必须零错误)
        run: npm run type-check

      - name: 代码规范(必须零错误)
        run: npm run lint

      - name: 单元/组件测试
        run: npm run test:run

      - name: 构建
        run: npm run build
```

- [ ] **Step 2:本地先复现 CI 的四步**

Run: `cd web && npm ci && npm run type-check && npm run lint && npm run test:run && npm run build`
Expected: 四步全过(`npm ci` 需要 `package-lock.json` 已入库)

- [ ] **Step 3:提交并推分支验证**

```bash
git add .github/workflows/web.yml
git commit -m "ci(web): 类型检查 / 规范 / 单测 / 构建四道门禁"
git push -u origin HEAD
```

Expected: GitHub Actions 上 `Web (Vue)` 变绿。

---

## 组 T10:部署与文档(3 个任务)

### Task 10.1:部署手册与上线核对单

**Files:**
- Modify: 服务器运维手册(本地保留,**不入库**)、`README.md`「部署」一节
- Test: 在服务器上按手册走一遍,IP 阶段可访问

**Interfaces:**
- Consumes: `npm run build` 产物 `web/dist`。
- Produces:nginx 站点配置样例 + 上线核对单。

- [ ] **Step 1:写 nginx 配置(静态直出 + 深链回退 + 反代)**

记入本地运维手册:

```nginx
# 网页端站点(备案前用 IP 访问,备案后换域名与证书)
server {
    listen 80;
    server_name _;

    root /www/wwwroot/chatapp-web;      # web/dist 的部署目录(上线时确认)
    index index.html;

    # 深链与 F5:找不到文件就回 index.html(vue-router history 模式必须)
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 带哈希的构建产物可长缓存;index.html 绝不能缓存
    location ~* \.(js|css|woff2?|ttf|png|jpg|svg)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
    location = /index.html {
        add_header Cache-Control "no-store";
    }

    # 接口与照片反代到 gunicorn / 媒体目录(同域,故不需要 CORS)
    location /api/v1/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
    location /media/ {
        alias /www/wwwroot/chatapp/media/;   # 域名站点此前缺这条,一并补上
        expires 7d;
    }
}
```

- [ ] **Step 2:写核对单(记入本地运维手册)**

1. 本地 `npm run build` → 产物拷到服务器部署目录
2. `nginx -t` → 重载
3. 浏览器打开 `http://<SERVER_IP>/` → 登录 → 滑卡 → 聊天发一条 → 广场发一条
4. 深链 `/settings` 直接访问 + F5
5. **手机浏览器打开 → 应为引导页**(不是破版)
6. 后端进程:`python manage.py test` 仍全绿(证明零改动没被破坏)
7. 档案:`.env` 的 `ALLOWED_HOSTS` 含当前访问域名/IP;CORS 保持默认(同域不需要)

- [ ] **Step 3:更新 README 部署一节并提交**

补「网页端」小节:技术栈、启动命令、构建产物、nginx 要求(直出 + try_files + 反代 `/api/v1` 与 `/media/`)、备案前用 IP 访问的说明。

```bash
git add README.md
git commit -m "docs: 部署一节补网页端(nginx 要求与核对单)"
```

### Task 10.2:踩坑分册 `docs/pitfalls/web.md`

**Files:**
- Create: `docs/pitfalls/web.md`
- Modify: `docs/pitfalls/README.md`(导航加一行)

**Interfaces:**
- Produces:Web 端踩坑分册,至少收录本计划已知的 6 条。

- [ ] **Step 1:写分册(照现有分册的格式:现象 / 原因 / 处置 / 出处)**

必须收录:

1. **Flutter Web 走不通**:`tencent_cloud_chat_sdk` 的 models 无条件 import `native_im/` → `dart:ffi`,Flutter 3.47.2 下 5147 条错误;升到 9.1.7818 同样失败;摘掉插件后能构建 → 故改用 Vue(附 spec §2 链接)
2. **wasm 预检是警告不是错误**:`Wasm dry run failed` 那一大段别当成构建失败原因
3. **`.env.test`**:vitest 的 mode 是 `test`,不会读 `.env.development`,漏了会出现「本地能跑、测试里 baseURL 是 undefined」
4. **`vite preview` 不继承 `server.proxy`**:端到端必须单独配 `preview.proxy`,否则跨域
5. **IM 踢下线是 `KICKED_OUT` 且要按原因分流**:`multiAccount`(同端多标签)只重连、**不能清凭证**(localStorage 共享,清了会把所有标签页一起登出)
6. **图片消息要先 `registerPlugin` 上传插件**,否则 `sendImage` 失败

- [ ] **Step 2:接导航**

`docs/pitfalls/README.md` 的主题表加一行:`Web 端(Vue 网页端、构建与部署)→ web.md`。

- [ ] **Step 3:提交**

```bash
git add docs/pitfalls
git commit -m "docs(pitfalls): 新增 web 分册(6 条实测坑)"
```

### Task 10.3:`CLAUDE.md` 与 `README.md` 落纪律

**Files:**
- Modify: `CLAUDE.md`、`README.md`

**Interfaces:**
- Produces:后续任何人在本项目里改视觉/改前端时,都能从 `CLAUDE.md` 看到必须遵守的规则。

- [ ] **Step 1:改 `CLAUDE.md`**

1. 「目录结构」表加一行:
   | `web/` | 网页端(Vue 3 SPA) | `src/{api,stores,im,components,layouts,features}`;开发 `npm run dev`(代理到 :8000),构建 `npm run build`;**只服务 PC 浏览器**,移动端按 UA 进引导页 |
2. 「核心契约与纪律」加一条:
   - **「心跳」token 双份维护**:改任何视觉 token 或字体,**必须在同一次改动内同时改** `app/lib/core/theme/*.dart` 与 `web/src/styles/tokens.css`(`web/public/fonts/*` 与 `app/assets/fonts/*` 保持一致);`web/tests/unit/tokens.spec.ts` 与 `fonts.spec.ts` 会双向比对,漏改即红
3. 「常用命令」加前端网页端三条:
   ```bash
   cd web && npm run dev          # 开发(需后端 runserver)
   cd web && npm run test:run     # 单测/组件测试(vitest)
   cd web && npm run e2e          # 端到端(需后端 + Redis + Celery)
   ```
4. 「文档导航」的行尾补 `docs/pitfalls/web.md`。

- [ ] **Step 2:改 `README.md`**

- 功能一览加「网页端」小节(PC 浏览器可用、与 App 同后端、移动端引导页)
- 目录结构加 `web/`
- 测试策略加前端网页端的门禁(vue-tsc / eslint / vitest / playwright)与用例数
- 徽章与「测试徽章数字」按实测更新(数字必须来自真实运行结果)

- [ ] **Step 3:提交**

```bash
git add CLAUDE.md README.md
git commit -m "docs: 网页端落纪律(token 双份维护)与导航"
```

**▶ 组 T9/T10 检查点**:CI 绿;`npm run e2e` 全过;服务器 IP 阶段按核对单走通;`CLAUDE.md`/`README.md`/`docs/pitfalls/web.md` 更新完毕。

---

## 执行记录

> 执行时在此追加实际偏差,以及 **Task 6.1 的 API 事实清单**(10 条实测结论)。

### 组 T6 执行记录(2026-10-05,分支 `feat/web-frontend`)

**计划自身的疏漏(执行时修正)**

1. **顺序倒置**:6.2 的 `client.ts` 依赖 6.3 的 `map.ts` → 按 T3 的先例**先做 6.3 再做 6.2**。
2. 6.4 的 `SettingsPage` TODO 兑现(Step 5)落空:该页此时还是空壳,`onLogout` 一并挪到 **T8.1** 实现。
3. 6.5 的用例用了 6.4 **未定义**的状态值 `'loading'`(6.4 的状态机是 `idle/connecting/ready/reconnecting/error`)→ 用例改用 `'connecting'`;另为「同端被接管」新增 `inactive` 状态(见下)。
4. 6.6/6.7/6.8 的组件用例同样漏了 `freshPinia()`,且未隔离会打网络的动作(`connect`/`loadConversations`/`openConversation`)→ 统一改为「共享 pinia + 假动作」。
5. 图片映射**按实测重写**(计划原文按 `type` 1/2/3 选图):改为按 `sizeType`、URL 取 `imageUrl || url` 并跳过空值,`type` 仅作回退。

**真机联调抓到的 5 个真 bug(单测全绿也照样存在)**

1. **`login()` 的 Promise 早于 SDK ready**:紧接着调 `getMessageList` 会拿到「未就绪」错误 → 真机上表现为**聊天历史永远空白**。修法:`client.login()` 内 `waitForReady()`(监听 `sdkStateReady` + 10s 兜底)。已补单测(第一版用例用 `await Promise.resolve()` 计数会假绿,改成真实定时器才钉住)。
2. **直接进聊天页(深链)从不连 IM**:`ChatPage.onMounted` 只拉历史没 `connect()` → 房间永远空。修法:页面挂载先 `await store.connect()`;`loadConversations/loadHistory/send*/delete*` 也统一走 `ensureConnected()`。
3. **`connect()` 与 `loadConversations()` 并发时用 SDKAppID=0 建实例** → 消息页整页报 `No SDKAppID`。修法:所有 IM 操作前先 `await connect()`(并发复用同一个 in-flight Promise)。
4. **同端第二个标签页造成「互踢风暴」**:按计划的「multiAccount → 只重连」实现后,两个标签页会互相踢,实测 10 秒内打了 **27 次 `POST /im/user_sig`** 并被 IM 限流(`over rate limit`)。修法:multiAccount 只置 `inactive` 并**停止自动重连**,由消息页给出「账号已在另一个窗口连接 / 在此窗口接管」的手动入口(清凭证仍然绝不发生)。复测:user_sig 只调 1 次。
5. **发送的图片重复一条**(store 已追加 + 页面又 `concat` 一次)、**配对灰条文本为空**(后端 `match_notice` 的自定义消息里本来就没有 text)—— 前者去掉重复 concat,后者按 App 的固定文案兜底(`你们已互相喜欢,开始聊天吧`,出处 `app/lib/features/chat/widgets/message_bubble.dart:34`)。

**另外两处数据/环境问题(不是代码 bug,但会影响观感)**

- 会话列表里对端昵称/头像来自 **IM 资料**,而造数用户从没同步过 → 显示成 `u18`。已跑后端自带的 `python manage.py im_sync_nicknames`(成功 25 个)修正;并在 `client.fetchConversations()` 里补了「昵称未知就拉一次 `getUserProfile`」的兜底(实测 SDK 自己不会补全,等 8 秒也没变)。
- 新建会话的服务端摘要**可能是残缺的**(实测 `lastMessage` 只有 `payload.text`,`from/time/nick` 全空;`userProfile` 也空)→ `loadConversations()` 改为**按 peerId 合并**,不用残缺摘要覆盖本地已知的昵称与完整摘要。遗留:这种情况下会话行的**时间**暂时为空,等下一条消息或 SDK 补全后出现。
- `.env` 里 IM 头像同步用的绝对地址是安卓模拟器地址(`http://10.0.2.2:8000/...`)→ 网页端头像会加载失败。上线前应改成对外可访问的地址(部署阶段处理)。
- **Celery worker 必须起着**(计划 6.1 Step 1 就写了):配对灰条、昵称/头像同步都靠它;本次之前一直没起,导致积压任务在启动瞬间被一次性消费。

**T6 检查点(真机,两个账号)**

- 账号 A=`u41`(小晴)/ B=`u18`(婉婷18,手机号 `13900000007`),用**隔离上下文**登录,避免共享 localStorage。
- 文本:B 发「网页端联调:你好呀」→ A 的消息页**实时**出现该会话与未读角标(侧栏未读合计 4);打开会话后未读清零 ✓
- 图片:A 选图 → 本地 blob 预览 → 上传成功换成 CDN 地址;B 侧历史里也能看到 ✓
- 灰条:配对时排队的 `match_notice` 由 worker 送达,渲染成居中 pill ✓
- 被顶号:另一个会话用同账号登录后,本标签页下一次请求收到 `401 + 40101` → **全屏「账号已在其他设备登录」+ 凭证清空**(运行时路径与刷新路径都验过)✓
- 同端第二个标签页:第一个标签页转 `inactive`、**不自动重连**、**凭证仍在**、无全屏提示 ✓

### Task 6.1:IM 通路 spike 事实清单(2026-10-05,实测于 `http://localhost:5173`)

**环境**:后端 `runserver`(IM 已配 `IM_SDKAPPID=1600161711`)+ Vite dev;登录账号 `u41`;SDK `@tencentcloud/chat` 3.6.7。spike 用的临时模块**已删除**(`web/im-spike.ts`,不提交)。10 条逐条结论如下 —— **后续 7 个任务以本清单为准**。

1. **create**:`TencentCloudChat.create({ SDKAppID })` 可用;接口返回的 `sdkappid` 是**字符串** `"1600161711"`,必须 `Number()` 转换。**实例按 SDKAppID 单例缓存**(SDK 内部 `Ir[n]`):同一页面重复 `create` 拿到的是同一个实例,`destroy()` 才会释放。
2. **login**:`chat.login({ userID: 'u41', userSig })` → **`code: 0`**,`data` 含 `a2Key/tinyID/instanceID/helloInterval/purchaseBits/authKey`。注意 **login 的 Promise resolve 时 `isReady()` 仍是 `false`**,要等 `sdkStateReady`(`SDK_READY`)事件;未就绪时调其它 API 会返回 `{code: getNotReadyReason(), message: '... | <api> | ...'}`(SDK 内部统一守卫)。
3. **收消息事件**:`EVENT.MESSAGE_RECEIVED === 'onMessageReceived'`;**`event.data` 是数组**。Message 字段实测:`ID / type / conversationID / conversationType / time(秒) / sequence / nick / avatar / from / to / flow('in'|'out') / status('success') / isRead / cloudCustomData / payload`。
4. **发文本**:`createTextMessage({ to, conversationType: TYPES.CONV_C2C, payload: { text } })` + `sendMessage` → `code: 0`;返回的 `data.message` 带 `flow:'out'`、`status:'success'`。`TYPES.CONV_C2C === 'C2C'`。
5. **正文位置**:**`payload.text`** ✅(与预期一致)。
6. **图片消息(有坑,详见下)**:
   - `@tencentcloud/upload-plugin` **在 npm 上不存在(404)**;官方包是 **`tim-upload-plugin`**(1.4.3,UMD,默认导出即插件,带 `getVersion()`,且**自带 `index.d.ts`**)→ 已 `npm install tim-upload-plugin`。
   - 注册方式 `chat.registerPlugin({ 'tim-upload-plugin': TIMUploadPlugin })`,**必须在 `login()` 之前调用**:上传模块在构造时就缓存了插件引用,登录后再注册会一直报 `code 2040 未检测到上传插件`(实测踩到过)。
   - `createImageMessage({ to, conversationType, payload: { file } })` + `sendMessage` → `code: 0`,type `TIMImageElem`,payload 键为 `imageFormat / uuid / imageInfoArray`。
   - **收到方向的权威结构**(用后端 REST 发一条 `TIMImageElem` 给 u41 后实测):`payload.imageInfoArray[]`,每项 `{ instanceID, sizeType, type, size, width, height, imageUrl, url }`。**`type` 是 0/1/2 且不可靠**(实测 type=1 那条 URL 为空);原图/缩略/大图的区分在 **`sizeType`:1=原图 / 2=缩略 / 3=大图**。URL **有两个字段**(`imageUrl` 是 https、`url` 是 http)→ 映射必须取 `imageUrl || url` 并**跳过空 URL 的项**。发送侧本地副本的 URL 先是 `blob:`,不能当最终值。
   - ⇒ **Task 6.7 的映射按 `sizeType` 选图,不按 `type`**;这条是对计划原文的修正。
7. **会话列表/历史结构**:`getConversationList()` → `{ code, data: { conversationList, isSyncCompleted } }`;会话项含 `conversationID('C2Cu18') / type('C2C') / unreadCount / lastMessage{ lastTime, lastSequence, fromAccount, messageForShow, payload, type, nick, isPeerRead } / userProfile{ userID, nick, avatar, ... } / remark / isPinned / draftText / subType / markList`。**对端昵称头像要取 `userProfile`**(SDK 会拉 IM 资料),`lastMessage.nick` 不可靠(实测最后一条是我发的,`nick` 仍是对方昵称)。
   `getMessageList({ conversationID })` → `{ code, data: { messageList, nextReqMessageID, isCompleted } }`,**messageList 是最旧 → 最新**(分页要按 `nextReqMessageID` 往前翻)。
8. **未读数**:`getTotalUnreadMessageCount()` **直接 resolve 一个 number**(不是 `{code,data}`)⇒ 类型是 `Promise<number>`;`onTotalUnreadMessageCountUpdated` 事件的 `data` 也是 number。
9. **踢出原因实测**:**同账号在第二个标签页登录** → 第一个标签页收到 `kickedOut { type: 'multipleAccount' }` 紧随 `sdkStateNotReady`,`isReady()` 变 false;后端 REST 踢人(`client.kick_user`)→ `{ type: 'REST_API_Kick' }`。`multipleDevice` / `userSigExpired` 本机无法制造,**未实测**(Web 侧以 JWT `40101` 为主信号,IM 踢出为辅)。
10. **控制台「在线 Web 实例数」**:需要登录腾讯云控制台才能看到,**代码侧读不到**;但行为上「同账号同时只有 1 个实例」已被第 9 条证实。若将来要做多标签页共存,需在控制台确认该配额。

**结论**:登录、收、发、会话列表、未读、图片上传、踢出分流**全部跑通**,Task 6.1 **通过**,继续 T6。


