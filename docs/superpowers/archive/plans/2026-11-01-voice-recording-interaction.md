# 语音录音交互打磨 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 把 Web 录音改成点击式并补齐全部错误路径，把 App 录音逻辑从 UI 抽成可单测 controller，两端共用一份状态机契约，修掉 4 个已知缺陷。

**Architecture:** 两端各自实现一份 4 状态录音机（`idle / requesting / recording / sending`），状态名、转移规则、文案键逐条对应；Web 用 Vue composable + 组件，App 用 `ChangeNotifier` + 现有 `VoiceRecorder` 抽象。Web 语音发送改为 store 内乐观插入，失败留可重试气泡。

**Tech Stack:** Vue 3 + TypeScript + Vitest（Web）、Flutter + Riverpod + flutter_test（App）。无新增依赖。

## Global Constraints

- **禁止裸值**：新增 CSS 只能用 `web/src/styles/tokens.css` 里的 token（`--color-*` / `--space-*` / `--radius-*` / `--text-*` / `--motion-*` / `--ease-*`），不写裸 hex、裸字号、裸间距。
- **文案逐字**（两端一致）：
  - `需要麦克风权限才能发语音`
  - `未检测到麦克风`
  - `当前浏览器不支持录音（需 HTTPS）`
  - `录音启动失败，请重试`
  - `说话时间太短`
  - `语音发送失败，点击重试`
- **时长**：最短 1000ms（低于则不发送）；上限 60000ms（到点自动发送）。
- **离开页面一律取消，绝不发送。**
- **Web 门槛**：`npm run type-check` 零错误、`npm run lint` 零告警、`npm run test:run` 全绿。
- **App 门槛**：`../flutter/bin/flutter.bat analyze` 零告警、`flutter test` 全绿。
- 不改后端、不改 `imserver`、不动图片发送路径。

---

### Task 1: Web 提示组件（useToast + AppToast）

**Files:**
- Create: `web/src/composables/useToast.ts`
- Create: `web/src/components/AppToast.vue`
- Test: `web/tests/unit/use-toast.spec.ts`

**Interfaces:**
- Produces: `useToast(durationMs?: number): { text: Ref<string>; show(message: string): void; clear(): void }`
- Produces: `<AppToast :text="string" />`（`text` 为空时不渲染）

- [x] **Step 1: 写失败测试**

创建 `web/tests/unit/use-toast.spec.ts`：

```ts
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { useToast } from '@/composables/useToast'

describe('useToast', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('show 之后 1.5 秒自动清空', () => {
    const toast = useToast()
    toast.show('已复制')
    expect(toast.text.value).toBe('已复制')
    vi.advanceTimersByTime(1500)
    expect(toast.text.value).toBe('')
  })

  it('连续 show 会重置计时，不会提前消失', () => {
    const toast = useToast()
    toast.show('第一条')
    vi.advanceTimersByTime(1000)
    toast.show('第二条')
    vi.advanceTimersByTime(1000)
    expect(toast.text.value).toBe('第二条')
    vi.advanceTimersByTime(500)
    expect(toast.text.value).toBe('')
  })

  it('clear 立即清空', () => {
    const toast = useToast()
    toast.show('x')
    toast.clear()
    expect(toast.text.value).toBe('')
  })
})
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd web && npm run test:run -- tests/unit/use-toast.spec.ts`
Expected: FAIL —— 找不到 `@/composables/useToast`。

- [x] **Step 3: 实现 useToast**

创建 `web/src/composables/useToast.ts`：

```ts
import { ref } from 'vue'
import type { Ref } from 'vue'

/** 轻量提示:show() 显示文案并在 [durationMs] 后自动清空;连续 show 重置计时。 */
export function useToast(durationMs = 1500): {
  text: Ref<string>
  show: (message: string) => void
  clear: () => void
} {
  const text = ref('')
  let timer: ReturnType<typeof setTimeout> | undefined

  function clear(): void {
    if (timer) clearTimeout(timer)
    timer = undefined
    text.value = ''
  }

  function show(message: string): void {
    clear()
    text.value = message
    timer = setTimeout(() => {
      text.value = ''
      timer = undefined
    }, durationMs)
  }

  return { text, show, clear }
}
```

- [x] **Step 4: 实现 AppToast 组件**

创建 `web/src/components/AppToast.vue`：

```vue
<script setup lang="ts">
/** 底部居中轻提示;文案由调用方用 useToast 控制,空串不渲染。 */
defineProps<{ text: string }>()
</script>

<template>
  <p v-if="text" class="app-toast" role="status">{{ text }}</p>
</template>

<style scoped>
.app-toast {
  position: fixed;
  bottom: 96px;
  left: 50%;
  z-index: 20;
  margin: 0;
  padding: var(--space-xs) var(--space-md);
  border-radius: var(--radius-full);
  background: var(--color-text1);
  color: var(--color-bg-card);
  font-size: var(--text-badge);
  transform: translateX(-50%);
  animation: app-toast-in var(--motion-fast) var(--ease-out);
}

@keyframes app-toast-in {
  from {
    opacity: 0;
    transform: translate(-50%, var(--space-xs));
  }
}

@media (prefers-reduced-motion: reduce) {
  .app-toast {
    animation: none;
  }
}
</style>
```

- [x] **Step 5: 跑测试确认通过**

Run: `cd web && npm run test:run -- tests/unit/use-toast.spec.ts`
Expected: PASS（3 个用例）。

- [x] **Step 6: 提交**

```bash
git add web/src/composables/useToast.ts web/src/components/AppToast.vue web/tests/unit/use-toast.spec.ts
git commit -m "feat(web): 抽 AppToast + useToast,统一轻提示"
```

---

### Task 2: Web 录音状态机（useVoiceRecorder）

**Files:**
- Create: `web/src/features/chat/useVoiceRecorder.ts`
- Test: `web/tests/unit/use-voice-recorder.spec.ts`

**Interfaces:**
- Consumes: `pickMimeType`（`@/im/self/voice`，已存在）
- Produces:
  - `type VoicePhase = 'idle' | 'requesting' | 'recording' | 'sending'`
  - `const VOICE_TEXT: { permissionDenied: string; noDevice: string; unsupported: string; startFailed: string; tooShort: string; sendFailed: string }`
  - `useVoiceRecorder(options: { enabled: () => boolean; onSend: (blob: Blob, durationMs: number) => Promise<void>; onNotice: (text: string) => void }): { phase: Ref<VoicePhase>; seconds: Ref<number>; start(): Promise<void>; stopAndSend(): Promise<void>; cancel(): Promise<void>; dispose(): void }`

- [x] **Step 1: 写失败测试**

创建 `web/tests/unit/use-voice-recorder.spec.ts`：

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { VOICE_TEXT, useVoiceRecorder } from '@/features/chat/useVoiceRecorder'

/** 假 MediaRecorder:start 后 state 变 recording,stop 触发 onstop。 */
class FakeRecorder {
  static supported = ['audio/webm;codecs=opus']
  static isTypeSupported = (type: string) => FakeRecorder.supported.includes(type)

  state = 'inactive'
  mimeType = 'audio/webm;codecs=opus'
  ondataavailable: ((event: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null

  start(): void {
    this.state = 'recording'
  }

  stop(): void {
    this.state = 'inactive'
    this.ondataavailable?.({ data: new Blob(['chunk'], { type: this.mimeType }) })
    this.onstop?.()
  }
}

function installRecorder(): void {
  vi.stubGlobal('MediaRecorder', FakeRecorder)
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: vi.fn() }] })),
    },
  })
}

function setup(overrides: Partial<{ enabled: () => boolean }> = {}) {
  const onSend = vi.fn(async () => {})
  const onNotice = vi.fn()
  const voice = useVoiceRecorder({
    enabled: overrides.enabled ?? (() => true),
    onSend,
    onNotice,
  })
  return { voice, onSend, onNotice }
}

describe('useVoiceRecorder', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(0)
    installRecorder()
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('start 后进入 recording 并开始计时', async () => {
    const { voice } = setup()
    await voice.start()
    expect(voice.phase.value).toBe('recording')
    vi.advanceTimersByTime(2000)
    expect(voice.seconds.value).toBe(2)
  })

  it('不足 1 秒不发送，提示太短', async () => {
    const { voice, onSend, onNotice } = setup()
    await voice.start()
    vi.advanceTimersByTime(500)
    await voice.stopAndSend()
    expect(onSend).not.toHaveBeenCalled()
    expect(onNotice).toHaveBeenCalledWith(VOICE_TEXT.tooShort)
    expect(voice.phase.value).toBe('idle')
  })

  it('满 1 秒正常发送并回到 idle', async () => {
    const { voice, onSend } = setup()
    await voice.start()
    vi.advanceTimersByTime(2500)
    await voice.stopAndSend()
    expect(onSend).toHaveBeenCalledTimes(1)
    expect(voice.phase.value).toBe('idle')
  })

  it('60 秒自动发送', async () => {
    const { voice, onSend } = setup()
    await voice.start()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(onSend).toHaveBeenCalledTimes(1)
  })

  it('取消不发任何消息', async () => {
    const { voice, onSend } = setup()
    await voice.start()
    vi.advanceTimersByTime(3000)
    await voice.cancel()
    expect(onSend).not.toHaveBeenCalled()
    expect(voice.phase.value).toBe('idle')
  })

  it('dispose 等价取消，绝不发送', async () => {
    const { voice, onSend } = setup()
    await voice.start()
    vi.advanceTimersByTime(3000)
    voice.dispose()
    expect(onSend).not.toHaveBeenCalled()
    expect(voice.phase.value).toBe('idle')
  })

  it('权限被拒映射成对应文案', async () => {
    const denied = Object.assign(new Error('denied'), { name: 'NotAllowedError' })
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn(async () => Promise.reject(denied)) },
    })
    const { voice, onNotice } = setup()
    await voice.start()
    expect(onNotice).toHaveBeenCalledWith(VOICE_TEXT.permissionDenied)
    expect(voice.phase.value).toBe('idle')
  })

  it('enabled 为假时直接提示不支持', async () => {
    const { voice, onNotice } = setup({ enabled: () => false })
    await voice.start()
    expect(onNotice).toHaveBeenCalledWith(VOICE_TEXT.unsupported)
    expect(voice.phase.value).toBe('idle')
  })
})
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd web && npm run test:run -- tests/unit/use-voice-recorder.spec.ts`
Expected: FAIL —— 模块不存在。

- [x] **Step 3: 实现 useVoiceRecorder**

创建 `web/src/features/chat/useVoiceRecorder.ts`：

```ts
/**
 * 聊天语音录制状态机(契约见 specs/2026-11-01-voice-recording-interaction-design.md §4)。
 *
 * 状态:idle → requesting → recording → sending → idle
 * 关键约束:不足 1 秒不发、60 秒自动发、离开页面只取消不发送。
 */

import { ref } from 'vue'
import type { Ref } from 'vue'
import { pickMimeType } from '@/im/self/voice'

export type VoicePhase = 'idle' | 'requesting' | 'recording' | 'sending'

/** 与 App 端 voice_record_controller.dart 的常量逐字对应,改一边必须改另一边。 */
export const VOICE_TEXT = {
  permissionDenied: '需要麦克风权限才能发语音',
  noDevice: '未检测到麦克风',
  unsupported: '当前浏览器不支持录音（需 HTTPS）',
  startFailed: '录音启动失败，请重试',
  tooShort: '说话时间太短',
  sendFailed: '语音发送失败，点击重试',
} as const

const MIN_DURATION_MS = 1000
const MAX_DURATION_MS = 60_000

export interface VoiceRecorderOptions {
  /** 能力位 + 浏览器支持,任一不满足都进不了录音 */
  enabled: () => boolean
  /** 发送一段录音;失败时调用方必须已经落了可重试气泡,这里静默 */
  onSend: (blob: Blob, durationMs: number) => Promise<void>
  /** 需要提示用户的话术(权限/设备/太短/启动失败) */
  onNotice: (text: string) => void
}

export interface VoiceRecorderHandle {
  phase: Ref<VoicePhase>
  seconds: Ref<number>
  start: () => Promise<void>
  stopAndSend: () => Promise<void>
  cancel: () => Promise<void>
  dispose: () => void
}

export function useVoiceRecorder(options: VoiceRecorderOptions): VoiceRecorderHandle {
  const phase = ref<VoicePhase>('idle')
  const seconds = ref(0)

  let recorder: MediaRecorder | null = null
  let stream: MediaStream | null = null
  let chunks: Blob[] = []
  let startedAt = 0
  let ticker: ReturnType<typeof setInterval> | undefined
  let timeout: ReturnType<typeof setTimeout> | undefined

  function clearTimers(): void {
    if (ticker) clearInterval(ticker)
    ticker = undefined
    if (timeout) clearTimeout(timeout)
    timeout = undefined
  }

  function stopTracks(): void {
    stream?.getTracks().forEach((track) => track.stop())
    stream = null
  }

  function toIdle(): void {
    clearTimers()
    stopTracks()
    recorder = null
    chunks = []
    seconds.value = 0
    phase.value = 'idle'
  }

  /** getUserMedia 的异常名 → 文案;浏览器各家名字不一致,多认几个。 */
  function noticeFor(error: unknown): string {
    const name = (error as { name?: string } | null)?.name ?? ''
    if (name === 'NotAllowedError' || name === 'SecurityError') return VOICE_TEXT.permissionDenied
    if (name === 'NotFoundError' || name === 'DevicesNotFoundError') return VOICE_TEXT.noDevice
    return VOICE_TEXT.startFailed
  }

  async function start(): Promise<void> {
    if (phase.value !== 'idle') return
    if (!options.enabled()) {
      options.onNotice(VOICE_TEXT.unsupported)
      return
    }
    const mime = pickMimeType()
    if (!mime) {
      options.onNotice(VOICE_TEXT.unsupported)
      return
    }
    phase.value = 'requesting'
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (error) {
      toIdle()
      options.onNotice(noticeFor(error))
      return
    }
    recorder = new MediaRecorder(stream, { mimeType: mime })
    chunks = []
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data)
    }
    recorder.start()
    startedAt = performance.now()
    seconds.value = 0
    phase.value = 'recording'
    ticker = setInterval(() => {
      seconds.value = Math.min(60, Math.ceil((performance.now() - startedAt) / 1000))
    }, 200)
    timeout = setTimeout(() => void stopAndSend(), MAX_DURATION_MS)
  }

  async function stopAndSend(): Promise<void> {
    if (phase.value !== 'recording') return
    const duration = performance.now() - startedAt
    clearTimers()
    const current = recorder
    recorder = null
    phase.value = 'sending'

    let blob: Blob | null = null
    if (current && current.state !== 'inactive') {
      blob = await new Promise<Blob | null>((resolve) => {
        current.onstop = () => {
          // Blob.type 会带 `;codecs=opus`;去掉参数,服务端白名单按主类型匹配
          const type = current.mimeType.split(';')[0] || 'audio/webm'
          resolve(new Blob(chunks, { type }))
        }
        current.stop()
      })
    }
    stopTracks()
    chunks = []

    if (duration < MIN_DURATION_MS) {
      seconds.value = 0
      phase.value = 'idle'
      options.onNotice(VOICE_TEXT.tooShort)
      return
    }
    if (!blob) {
      seconds.value = 0
      phase.value = 'idle'
      options.onNotice(VOICE_TEXT.startFailed)
      return
    }
    try {
      await options.onSend(blob, duration)
    } catch {
      // 失败态由 onSend 的调用方落气泡(store.sendVoice 内部已标 isFailed)
    } finally {
      seconds.value = 0
      phase.value = 'idle'
    }
  }

  async function cancel(): Promise<void> {
    if (phase.value === 'idle') return
    const current = recorder
    recorder = null
    if (current && current.state !== 'inactive') {
      current.onstop = null
      current.stop()
    }
    toIdle()
  }

  /** 组件卸载时调用:一律取消,绝不把没录完的话发出去。 */
  function dispose(): void {
    void cancel()
  }

  return { phase, seconds, start, stopAndSend, cancel, dispose }
}
```

- [x] **Step 4: 跑测试确认通过**

Run: `cd web && npm run test:run -- tests/unit/use-voice-recorder.spec.ts`
Expected: PASS（8 个用例）。

- [x] **Step 5: 提交**

```bash
git add web/src/features/chat/useVoiceRecorder.ts web/tests/unit/use-voice-recorder.spec.ts
git commit -m "feat(web): 录音状态机 useVoiceRecorder(修拖出不停/静默失败/离开即发送)"
```

---

### Task 3: Web 录音条组件

**Files:**
- Create: `web/src/features/chat/VoiceRecordBar.vue`
- Test: `web/tests/component/voice-record-bar.spec.ts`

**Interfaces:**
- Consumes: `VoicePhase`（Task 2）
- Produces: `<VoiceRecordBar :phase="VoicePhase" :seconds="number" @cancel @send />`

- [x] **Step 1: 写失败测试**

创建 `web/tests/component/voice-record-bar.spec.ts`：

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import VoiceRecordBar from '@/features/chat/VoiceRecordBar.vue'

function mountBar(phase: 'recording' | 'sending' = 'recording', seconds = 5) {
  return mount(VoiceRecordBar, { props: { phase, seconds } })
}

describe('VoiceRecordBar', () => {
  it('渲染取消 / 计时 / 发送三段', () => {
    const w = mountBar('recording', 65)
    expect(w.text()).toContain('取消')
    expect(w.text()).toContain('01:05')
    expect(w.text()).toContain('发送')
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
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd web && npm run test:run -- tests/component/voice-record-bar.spec.ts`
Expected: FAIL —— 组件不存在。

- [x] **Step 3: 实现组件**

创建 `web/src/features/chat/VoiceRecordBar.vue`：

```vue
<script setup lang="ts">
import type { VoicePhase } from './useVoiceRecorder'

/** 录音时替换整个输入栏的三段式:取消 | 计时 | 发送。 */
const props = defineProps<{ phase: VoicePhase; seconds: number }>()
defineEmits<{ cancel: []; send: [] }>()

function clock(total: number): string {
  const safe = Math.max(0, Math.min(60, total))
  return `${String(Math.floor(safe / 60)).padStart(2, '0')}:${String(safe % 60).padStart(2, '0')}`
}
</script>

<template>
  <div class="voice-bar" role="group" aria-label="录音中">
    <button
      type="button"
      class="voice-bar__cancel"
      :disabled="props.phase === 'sending'"
      @click="$emit('cancel')"
    >
      取消
    </button>

    <span class="voice-bar__clock">
      <span class="voice-bar__dot" :class="{ 'voice-bar__dot--still': props.phase === 'sending' }" />
      <span class="voice-bar__seconds">{{ clock(props.seconds) }}</span>
    </span>

    <button
      type="button"
      class="voice-bar__send"
      :disabled="props.phase === 'sending'"
      @click="$emit('send')"
    >
      {{ props.phase === 'sending' ? '发送中…' : '发送' }}
    </button>
  </div>
</template>

<style scoped>
.voice-bar {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
}

.voice-bar__cancel,
.voice-bar__send {
  flex: none;
  height: 40px;
  padding: 0 var(--space-lg);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-input);
  background: var(--color-bg-card);
  color: var(--color-text1);
  font-size: var(--text-caption);
  cursor: pointer;
}

.voice-bar__cancel:disabled,
.voice-bar__send:disabled {
  color: var(--color-text3);
  cursor: default;
}

.voice-bar__send {
  border-color: var(--color-brand);
  background: var(--color-brand);
  color: var(--color-bg-card);
}

.voice-bar__send:disabled {
  border-color: var(--color-divider);
  background: var(--color-divider);
}

.voice-bar__clock {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  color: var(--color-text1);
}

.voice-bar__dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--color-brand);
  animation: voice-bar-pulse var(--motion-loop) var(--ease-out) infinite;
}

.voice-bar__dot--still {
  animation: none;
}

.voice-bar__seconds {
  font-size: var(--text-subtitle);
  font-variant-numeric: tabular-nums;
}

@keyframes voice-bar-pulse {
  50% {
    opacity: 0.35;
  }
}

@media (prefers-reduced-motion: reduce) {
  .voice-bar__dot {
    animation: none;
  }
}
</style>
```

- [x] **Step 4: 跑测试确认通过**

Run: `cd web && npm run test:run -- tests/component/voice-record-bar.spec.ts`
Expected: PASS（3 个用例）。

- [x] **Step 5: 提交**

```bash
git add web/src/features/chat/VoiceRecordBar.vue web/tests/component/voice-record-bar.spec.ts
git commit -m "feat(web): 录音条三段式组件"
```

---

### Task 4: Web store 乐观发送与重试

**Files:**
- Modify: `web/src/stores/chat.ts`（`sendVoice` / `resend` / 新增 `replaceMessage`）
- Test: `web/tests/unit/chat-store.spec.ts`（追加用例）

**Interfaces:**
- Produces: `store.sendVoice(peerId, blob, durationMs): Promise<ChatMessage>` —— 先插入 `isPending` 占位，成功就地替换，失败标 `isFailed` 并抛出。
- Produces: `store.resend(message): Promise<void>` —— 语音失败消息可用缓存 blob 重发。

- [x] **Step 1: 读现有测试的 store 搭建方式**

Run: `sed -n '1,60p' web/tests/unit/chat-store.spec.ts`（Windows 用 `Get-Content -TotalCount 60`）
确认 `useChatStore` 的初始化与假 client 注入方式，后续用例照抄。

- [x] **Step 2: 写失败测试（追加到 `chat-store.spec.ts` 末尾的 describe 内）**

```ts
describe('sendVoice 乐观发送', () => {
  it('发送前先插入 isPending 占位,成功后替换成真实消息', async () => {
    const { store, client } = await setupStore()
    const real = message({ msgId: 'real-1', kind: ChatMessageKind.voice, isSelf: true })
    client.sendVoice = vi.fn(async () => real)

    const pending = store.sendVoice('u8', new Blob(['a']), 3000)
    expect(store.messagesOf('u8').some((item) => item.isPending)).toBe(true)
    await pending
    expect(store.messagesOf('u8').filter((item) => item.kind === ChatMessageKind.voice)).toHaveLength(1)
    expect(store.messagesOf('u8')[0].msgId).toBe('real-1')
  })

  it('发送失败把占位标成 isFailed 并抛出', async () => {
    const { store, client } = await setupStore()
    client.sendVoice = vi.fn(async () => Promise.reject(new Error('boom')))

    await expect(store.sendVoice('u8', new Blob(['a']), 3000)).rejects.toThrow('boom')
    const failed = store.messagesOf('u8').find((item) => item.kind === ChatMessageKind.voice)
    expect(failed?.isFailed).toBe(true)
    expect(failed?.isPending).toBe(false)
  })

  it('resend 用缓存 blob 重发失败语音', async () => {
    const { store, client } = await setupStore()
    client.sendVoice = vi.fn(async () => Promise.reject(new Error('boom')))
    await expect(store.sendVoice('u8', new Blob(['a']), 3000)).rejects.toThrow()

    const failed = store.messagesOf('u8').find((item) => item.isFailed)!
    client.sendVoice = vi.fn(async () => message({ msgId: 'real-2', kind: ChatMessageKind.voice }))
    await store.resend(failed)
    expect(client.sendVoice).toHaveBeenCalledTimes(1)
    expect(store.messagesOf('u8').some((item) => item.msgId === 'real-2')).toBe(true)
  })
})
```

> 注：`setupStore()` / `message()` 用该文件已有的辅助函数；若命名不同，按文件内现有写法调整，语义不变。

- [x] **Step 3: 跑测试确认失败**

Run: `cd web && npm run test:run -- tests/unit/chat-store.spec.ts`
Expected: FAIL —— 占位消息不存在。

- [x] **Step 4: 改 store**

在 `web/src/stores/chat.ts` 内新增私有工具（放在 `appendMessage` 附近）：

```ts
  /** 就地替换一条消息(乐观占位 → 真实消息 / 失败态),不改变顺序。 */
  function replaceMessage(msgId: string, next: ChatMessage): void {
    const current = messages.value
    for (const [peerId, list] of Object.entries(current)) {
      if (!list.some((item) => item.msgId === msgId)) continue
      messages.value = {
        ...current,
        [peerId]: list.map((item) => (item.msgId === msgId ? next : item)),
      }
      return
    }
  }
```

把 `sendVoice` 整体替换为：

```ts
  /** 乐观发送:先上屏占位(失败可重试),成功后就地替换成真实消息。 */
  async function sendVoice(peerId: string, blob: Blob, durationMs: number): Promise<ChatMessage> {
    const placeholder: ChatMessage = {
      msgId: `local-${Date.now()}`,
      peerId,
      isSelf: true,
      seq: 0,
      timestamp: Date.now(),
      kind: ChatMessageKind.voice,
      text: '',
      senderName: '',
      senderAvatar: null,
      isPending: true,
      isFailed: false,
      imageUrl: null,
      imageLargeUrl: null,
      voiceUrl: null,
      voiceDurationMs: durationMs,
      isRevoked: false,
    }
    appendMessage(peerId, placeholder)
    pendingVoices.set(placeholder.msgId, { blob, durationMs })
    try {
      await ensureConnected()
      const sent = await client.sendVoice(peerId, blob, durationMs)
      replaceMessage(placeholder.msgId, sent)
      pendingVoices.delete(placeholder.msgId)
      pendingVoices.set(sent.msgId, { blob, durationMs })
      upsertConversation({ ...sent, isSelf: true })
      return sent
    } catch (error) {
      replaceMessage(placeholder.msgId, { ...placeholder, isPending: false, isFailed: true })
      throw error
    }
  }
```

`resend` 的语音分支改为：

```ts
    if (message.kind === 'voice') {
      const voice = pendingVoices.get(message.msgId)
      if (!voice) return
      pendingVoices.delete(message.msgId)
      messages.value = {
        ...messages.value,
        [message.peerId]: messagesOf(message.peerId).filter((item) => item.msgId !== message.msgId),
      }
      await sendVoice(message.peerId, voice.blob, voice.durationMs)
      return
    }
```

（`resend` 开头已有的"先移除旧消息"对文本/图片仍适用；语音分支自己再移除一次是幂等的。）

- [x] **Step 5: 跑测试确认通过**

Run: `cd web && npm run test:run -- tests/unit/chat-store.spec.ts`
Expected: PASS（原有用例 + 新增 3 个）。

- [x] **Step 6: 提交**

```bash
git add web/src/stores/chat.ts web/tests/unit/chat-store.spec.ts
git commit -m "feat(web): 语音乐观发送与失败重试"
```

---

### Task 5: Web 聊天页接线

**Files:**
- Modify: `web/src/features/chat/ChatPage.vue`
- Test: `web/tests/component/chat-page.spec.ts`（追加用例）

**Interfaces:**
- Consumes: `useVoiceRecorder`（Task 2）、`VoiceRecordBar`（Task 3）、`useToast`/`AppToast`（Task 1）、`store.sendVoice`（Task 4）

- [x] **Step 1: 写失败测试（追加到 `chat-page.spec.ts`）**

```ts
  it('能力不支持时麦克风仍渲染但置灰,点击给出原因', async () => {
    const { w } = await mountPage()
    await flushPromises()
    const mic = w.find('[aria-label="按住说话"]')
    expect(mic.exists()).toBe(true)
    expect(mic.attributes('disabled')).toBeDefined()

    await mic.trigger('click')
    await flushPromises()
    expect(w.text()).toContain('当前浏览器不支持录音')
  })

  it('能力支持时点麦克风进入录音条', async () => {
    const { w, store } = await mountPage()
    await flushPromises()
    store.capabilities = { image: true, search: false, voice: true }
    await flushPromises()

    // jsdom 没有 MediaRecorder,先把浏览器能力桩上
    vi.stubGlobal('MediaRecorder', class {
      static isTypeSupported = () => true
      state = 'inactive'
      mimeType = 'audio/webm'
      ondataavailable = null
      onstop = null
      start() { this.state = 'recording' }
      stop() { this.state = 'inactive'; this.onstop?.() }
    })
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: vi.fn() }] })) },
    })

    await w.find('[aria-label="按住说话"]').trigger('click')
    await flushPromises()
    expect(w.find('.voice-bar').exists()).toBe(true)
  })
```

> 说明：第二个用例依赖 `voiceEnabled` 里的 `canRecordVoice()`，桩必须在挂载后、点击前生效（该函数每次点击时才调用）。

- [x] **Step 2: 跑测试确认失败**

Run: `cd web && npm run test:run -- tests/component/chat-page.spec.ts`
Expected: FAIL —— 麦克风在能力为 false 时不存在 / 点完没有 `.voice-bar`。

- [x] **Step 3: 改 ChatPage**

1）删除脚本里的录音实现（`recording / cancelArmed / recordSeconds / mediaRecorder / mediaStream / chunks / recordStartedAt / recordStartY / recordTimer` 与 `startRecording / onVoiceMove / finishRecording`），改为：

```ts
import { canRecordVoice } from '@/im/self/voice'
import { useToast } from '@/composables/useToast'
import AppToast from '@/components/AppToast.vue'
import VoiceRecordBar from './VoiceRecordBar.vue'
import { VOICE_TEXT, useVoiceRecorder } from './useVoiceRecorder'

const toast = useToast()

const voiceEnabled = computed(() => store.capabilities.voice && canRecordVoice())

const voice = useVoiceRecorder({
  enabled: () => voiceEnabled.value,
  onSend: (blob, durationMs) => store.sendVoice(props.peerId, blob, durationMs).then(() => {}),
  onNotice: (text) => toast.show(text),
})

function onMicClick(): void {
  if (!voiceEnabled.value) {
    toast.show(VOICE_TEXT.unsupported)
    return
  }
  void voice.start()
}

function onEscape(event: KeyboardEvent): void {
  if (event.key === 'Escape' && voice.phase.value === 'recording') void voice.cancel()
}
```

2）`onMounted` 里 `document.addEventListener('keydown', onEscape)`；`onUnmounted` 里 `document.removeEventListener('keydown', onEscape)`、`voice.dispose()`，并删掉原来的 `if (recording.value) void finishRecording()` 与 `clearInterval(recordTimer)`。

3）模板：`<footer class="chat__composer">` 内首行插入

```vue
      <VoiceRecordBar
        v-if="voice.phase.value !== 'idle'"
        :phase="voice.phase.value"
        :seconds="voice.seconds.value"
        @cancel="voice.cancel()"
        @send="voice.stopAndSend()"
      />
```

其余输入控件包进 `<template v-else>`。

4）麦克风按钮改为（**始终渲染**，去掉 `v-if`）：

```vue
      <button
        type="button"
        class="chat__image"
        aria-label="按住说话"
        :disabled="!voiceEnabled || unmatched"
        @click="onMicClick"
      >
        🎤
      </button>
```

5）删除模板里原来的 `chat__recording` 提示块，以及样式表里的 `.chat__recording` / `.chat__recording-time` / `.chat__recording-hint` / `.chat__toast`。

6）把原来的 `已复制` 内联提示换成 `<AppToast :text="toast.text.value" />`，`copied` 相关代码删掉，复制成功改调 `toast.show('已复制')`。

- [x] **Step 4: 跑测试确认通过**

Run: `cd web && npm run test:run -- tests/component/chat-page.spec.ts`
Expected: PASS。

- [x] **Step 5: 全量回归 + 类型与 lint**

Run: `cd web && npm run type-check && npm run lint && npm run test:run`
Expected: 全绿。

- [x] **Step 6: 提交**

```bash
git add web/src/features/chat/ChatPage.vue web/tests/component/chat-page.spec.ts
git commit -m "feat(web): 聊天页接点击式录音(入口常驻/置灰可解释/Esc 取消/离开即取消)"
```

---

### Task 6: Web 语音气泡空地址兜底

**Files:**
- Modify: `web/src/features/chat/MessageVoice.vue`
- Test: `web/tests/component/message-voice.spec.ts`（追加用例）

**Interfaces:**
- Consumes: `ChatMessage.voiceUrl`（可为 null）
- Produces: 无 URL 时渲染 `.voice--empty` 且不可点击

- [x] **Step 1: 写失败测试**

```ts
  it('没有地址时渲染不可播放的占位,不调播放器', async () => {
    const { playVoice } = await import('@/im/voicePlayer')
    const w = mount(MessageVoice, { props: { message: message({ voiceUrl: null }) } })
    expect(w.find('.voice--empty').exists()).toBe(true)
    await w.find('.voice').trigger('click')
    expect(playVoice).not.toHaveBeenCalled()
  })
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd web && npm run test:run -- tests/component/message-voice.spec.ts`
Expected: FAIL —— 无 `.voice--empty`。

- [x] **Step 3: 改组件**

`MessageVoice.vue` 里：

- 新增 `const playable = computed(() => Boolean(props.message.voiceUrl))`
- `toggle()` 开头加 `if (!playable.value) return`
- 根元素 class 绑定 `{ 'voice--empty': !playable }`
- 图标在不可播放时显示 `🎙`，并加 `aria-disabled="true"`

- [x] **Step 4: 跑测试确认通过**

Run: `cd web && npm run test:run -- tests/component/message-voice.spec.ts`
Expected: PASS。

- [x] **Step 5: 提交**

```bash
git add web/src/features/chat/MessageVoice.vue web/tests/component/message-voice.spec.ts
git commit -m "fix(web): 语音气泡无地址时渲染占位,不再把空串丢给播放器"
```

---

### Task 7: App 录音控制器

**Files:**
- Create: `app/lib/features/chat/voice_record_controller.dart`
- Test: `app/test/features/chat/voice_record_controller_test.dart`

**Interfaces:**
- Consumes: `VoiceRecorder`（`app/lib/im/voice_recorder.dart`：`hasPermission() / start(path) / stop() / cancel()`）
- Produces:
  - `enum VoicePhase { idle, requesting, recording, sending }`
  - `class VoiceRecordController extends ChangeNotifier`，含 `phase / seconds / cancelArmed / start() / stopAndSend() / cancel() / updateCancelArm(bool)`
  - 顶层常量 `voiceTextPermissionDenied` 等 6 个（与 Web `VOICE_TEXT` 逐字对应）

- [x] **Step 1: 写失败测试**

创建 `app/test/features/chat/voice_record_controller_test.dart`：

```dart
import 'package:chatapp_app/features/chat/voice_record_controller.dart';
import 'package:chatapp_app/im/voice_recorder.dart';
import 'package:fake_async/fake_async.dart';
import 'package:flutter_test/flutter_test.dart';

/// 假录音器:记录调用次数,stop 返回固定路径。
class _FakeRecorder implements VoiceRecorder {
  bool permission = true;
  bool started = false;
  int cancelCalls = 0;
  int stopCalls = 0;

  @override
  Future<bool> hasPermission() async => permission;

  @override
  Future<void> start(String path) async => started = true;

  @override
  Future<String?> stop() async {
    stopCalls++;
    return '/tmp/voice-1.m4a';
  }

  @override
  Future<void> cancel() async => cancelCalls++;
}

void main() {
  late _FakeRecorder recorder;
  late List<String> notices;
  late List<({String path, int durationMs})> sent;

  VoiceRecordController build() => VoiceRecordController(
        recorder: recorder,
        tempPath: () async => '/tmp/voice-1.m4a',
        onNotice: notices.add,
        onSend: (path, durationMs) async => sent.add((path: path, durationMs: durationMs)),
      );

  setUp(() {
    recorder = _FakeRecorder();
    notices = [];
    sent = [];
  });

  test('start 后进入 recording', () async {
    final c = build();
    await c.start();
    expect(c.phase, VoicePhase.recording);
    c.dispose();
  });

  test('无权限提示且不进入录音', () async {
    recorder.permission = false;
    final c = build();
    await c.start();
    expect(c.phase, VoicePhase.idle);
    expect(notices, contains(voiceTextPermissionDenied));
    c.dispose();
  });

  test('不足 1 秒不发送并提示太短', () async {
    final c = build();
    await c.start();
    await c.stopAndSend();
    expect(sent, isEmpty);
    expect(notices, contains(voiceTextTooShort));
    c.dispose();
  });

  test('满 1 秒发送一次', () async {
    fakeAsync((async) {
      final c = build();
      c.start();
      async.flushMicrotasks();
      async.elapse(const Duration(seconds: 2));
      c.stopAndSend();
      async.flushMicrotasks();
      expect(sent, hasLength(1));
      c.dispose();
    });
  });

  test('60 秒自动发送', () async {
    fakeAsync((async) {
      final c = build();
      c.start();
      async.flushMicrotasks();
      async.elapse(const Duration(seconds: 61));
      async.flushMicrotasks();
      expect(sent, hasLength(1));
      c.dispose();
    });
  });

  test('dispose 时录音中会取消录音,不发送', () async {
    final c = build();
    await c.start();
    c.dispose();
    expect(recorder.cancelCalls, greaterThanOrEqualTo(1));
    expect(sent, isEmpty);
  });
}
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/chat/voice_record_controller_test.dart`
Expected: FAIL —— 文件不存在。

- [x] **Step 3: 实现 controller**

创建 `app/lib/features/chat/voice_record_controller.dart`：

```dart
import 'dart:async';

import 'package:flutter/foundation.dart';

import '../../im/voice_recorder.dart';

/// 录音状态(契约见 docs/superpowers/archive/specs/2026-11-01-voice-recording-interaction-design.md §4)。
enum VoicePhase { idle, requesting, recording, sending }

/// 提示文案:与 Web 端 useVoiceRecorder.ts 的 VOICE_TEXT 逐字对应。
const String voiceTextPermissionDenied = '需要麦克风权限才能发语音';
const String voiceTextNoDevice = '未检测到麦克风';
const String voiceTextUnsupported = '当前浏览器不支持录音（需 HTTPS）';
const String voiceTextStartFailed = '录音启动失败，请重试';
const String voiceTextTooShort = '说话时间太短';
const String voiceTextSendFailed = '语音发送失败，点击重试';

const int _minDurationMs = 1000;
const int _maxDurationMs = 60000;

/// 录音控制器:把原来埋在输入栏里的录音逻辑收拢成可单测的状态机。
class VoiceRecordController extends ChangeNotifier {
  VoiceRecordController({
    required VoiceRecorder recorder,
    required Future<String> Function() tempPath,
    required void Function(String message) onNotice,
    required Future<void> Function(String path, int durationMs) onSend,
  })  : _recorder = recorder,
        _tempPath = tempPath,
        _onNotice = onNotice,
        _onSend = onSend;

  final VoiceRecorder _recorder;
  final Future<String> Function() _tempPath;
  final void Function(String message) _onNotice;
  final Future<void> Function(String path, int durationMs) _onSend;

  VoicePhase _phase = VoicePhase.idle;
  VoicePhase get phase => _phase;

  bool _cancelArmed = false;
  bool get cancelArmed => _cancelArmed;

  final Stopwatch _stopwatch = Stopwatch();
  Timer? _ticker;
  Timer? _autoStop;

  /// 已录秒数(向上取整,0–60)。
  int get seconds => (_stopwatch.elapsedMilliseconds / 1000).ceil().clamp(0, 60);

  /// 开始录音:申请权限 → 启动设备 → 起计时与 60 秒上限。
  Future<void> start() async {
    if (_phase != VoicePhase.idle) return;
    _phase = VoicePhase.requesting;
    notifyListeners();
    if (!await _recorder.hasPermission()) {
      _phase = VoicePhase.idle;
      notifyListeners();
      _onNotice(voiceTextPermissionDenied);
      return;
    }
    final path = await _tempPath();
    try {
      await _recorder.start(path);
    } catch (_) {
      _phase = VoicePhase.idle;
      notifyListeners();
      _onNotice(voiceTextStartFailed);
      return;
    }
    _phase = VoicePhase.recording;
    _cancelArmed = false;
    _stopwatch
      ..reset()
      ..start();
    _ticker = Timer.periodic(const Duration(milliseconds: 200), (_) => notifyListeners());
    _autoStop = Timer(const Duration(milliseconds: _maxDurationMs), () {
      unawaited(stopAndSend());
    });
    notifyListeners();
  }

  /// 上滑取消态:由手势层把「是否已滑入取消区」告诉控制器。
  void updateCancelArm(bool armed) {
    if (_cancelArmed == armed) return;
    _cancelArmed = armed;
    notifyListeners();
  }

  /// 结束并发送;不足 1 秒只提示不发送。
  Future<void> stopAndSend() async {
    if (_phase != VoicePhase.recording) return;
    _autoStop?.cancel();
    _ticker?.cancel();
    _stopwatch.stop();
    final durationMs = _stopwatch.elapsedMilliseconds;
    final cancelled = _cancelArmed;
    _phase = VoicePhase.sending;
    _cancelArmed = false;
    notifyListeners();

    if (cancelled) {
      await cancel();
      return;
    }
    final path = await _recorder.stop();
    if (path == null || durationMs < _minDurationMs) {
      try {
        await _recorder.cancel();
      } catch (_) {}
      _phase = VoicePhase.idle;
      notifyListeners();
      _onNotice(path == null ? voiceTextStartFailed : voiceTextTooShort);
      return;
    }
    try {
      await _onSend(path, durationMs);
    } catch (_) {
      _onNotice(voiceTextSendFailed);
    } finally {
      _phase = VoicePhase.idle;
      notifyListeners();
    }
  }

  /// 丢弃当前录音(取消按钮 / 页面离开)。
  Future<void> cancel() async {
    if (_phase == VoicePhase.idle) return;
    _autoStop?.cancel();
    _ticker?.cancel();
    _stopwatch.stop();
    _cancelArmed = false;
    _phase = VoicePhase.idle;
    try {
      await _recorder.cancel();
    } catch (_) {}
    notifyListeners();
  }

  @override
  void dispose() {
    _autoStop?.cancel();
    _ticker?.cancel();
    if (_phase == VoicePhase.recording || _phase == VoicePhase.sending) {
      unawaited(_recorder.cancel().catchError((_) {}));
    }
    super.dispose();
  }
}
```

> `unawaited` 需要 `import 'dart:async';`（已含）。

- [x] **Step 4: 跑测试确认通过**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/chat/voice_record_controller_test.dart`
Expected: PASS（6 个用例）。

- [x] **Step 5: 提交**

```bash
git add app/lib/features/chat/voice_record_controller.dart app/test/features/chat/voice_record_controller_test.dart
git commit -m "feat(app): 抽 VoiceRecordController(修 dispose 不停录音的泄漏)"
```

---

### Task 8: App 输入栏接入控制器

**Files:**
- Modify: `app/lib/features/chat/chat_page.dart`（`_InputBar` / `_InputBarState`）
- Test: `app/test/features/chat/chat_page_test.dart`（按现有用例调整）

**Interfaces:**
- Consumes: `VoiceRecordController`（Task 7）
- Produces: 输入栏行为不变（长按录音 / 上滑取消 / 松开发送），但状态由 controller 持有

- [x] **Step 1: 跑现有测试确认基线**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/chat/chat_page_test.dart`
Expected: PASS（记录当前用例数）。

- [x] **Step 2: 改造 `_InputBarState`**

- 删掉 `_recording / _cancelArmed / _stopwatch / _ticker / _autoStop` 与 `_startRecording / _finishRecording`。
- `initState` 里创建：

```dart
  late final VoiceRecordController _voice;

  @override
  void initState() {
    super.initState();
    _voice = VoiceRecordController(
      recorder: ref.read(voiceRecorderProvider),
      tempPath: ref.read(voiceTempPathProvider),
      onNotice: (message) {
        if (mounted) AppToast.show(context, message);
      },
      onSend: widget.onSendVoice,
    )..addListener(_onVoiceChanged);
  }

  void _onVoiceChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _voice
      ..removeListener(_onVoiceChanged)
      ..dispose();
    super.dispose();
  }
```

- 手势块改为：

```dart
                    GestureDetector(
                      key: const Key('chat.mic'),
                      behavior: HitTestBehavior.opaque,
                      onLongPressStart: (_) => _voice.start(),
                      onLongPressMoveUpdate: (details) =>
                          _voice.updateCancelArm(details.localOffsetFromOrigin.dy < -60),
                      onLongPressEnd: (_) => _voice.stopAndSend(),
                      child: SizedBox(
                        width: 44,
                        height: 44,
                        child: Icon(
                          Icons.mic_rounded,
                          size: 24,
                          color: widget.enabled ? AppColors.text2 : AppColors.text3,
                        ),
                      ),
                    ),
```

- `build` 里 `seconds` 改 `_voice.seconds`，`if (_recording)` 改 `if (_voice.phase == VoicePhase.recording)`，浮层参数改 `cancelArmed: _voice.cancelArmed`。
- 补 import：`voice_record_controller.dart`。

- [x] **Step 3: 跑测试确认通过**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/chat/chat_page_test.dart`
Expected: PASS（用例数与 Step 1 一致或更多）。

- [x] **Step 4: 全量回归 + analyze**

Run: `cd app && ../flutter/bin/flutter.bat analyze && ../flutter/bin/flutter.bat test`
Expected: 零告警、全绿。

- [x] **Step 5: 提交**

```bash
git add app/lib/features/chat/chat_page.dart app/test/features/chat/chat_page_test.dart
git commit -m "refactor(app): 输入栏接入 VoiceRecordController,UI 与手势保持不变"
```

---

### Task 9: 文档与收尾

**Files:**
- Modify: `CLAUDE.md`（「下一步」第 3 条）
- Modify: `docs/pitfalls/web.md`（新增一条：录音状态机与离开页面的语义）
- Modify: `docs/pitfalls/frontend.md`（新增一条：dispose 必须停录音）

**Interfaces:** 无

- [x] **Step 1: 更新 CLAUDE.md**

把「下一步」第 3 条整段替换为：

```markdown
3. **Web 语音已可用(2026-11-01 打磨)**:入口自 2026-10-27 起就存在,本期改为点击式录音(点开始 → 再点发送,可取消/Esc),补齐权限被拒、无设备、太短、发送失败四条错误路径;App 保留按住说话,录音逻辑抽成 `VoiceRecordController`。修掉四个缺陷:指针拖出后录音停不下来、失败静默、入口凭空消失、离开页面把没录完的语音发出去。
```

- [x] **Step 2: 补 web 踩坑**

在 `docs/pitfalls/web.md` 末尾追加：

```markdown
## N. 录音这类"有副作用的状态机"不要写在组件里

`ChatPage.vue` 原来把 MediaRecorder 生命周期写在组件里，结果 `onUnmounted` 顺手调了 `finishRecording()` —— 离开聊天页会把正在录的语音发给对方。

**规则**：凡是「开始/结束/取消 + 超时自动结束」的状态机，抽成 composable 并显式提供 `dispose()`；`dispose()` 的语义固定是「取消」，不是「完成」。测试里必须有一条断言 `dispose` 之后没有发送。
```

- [x] **Step 3: 补 frontend 踩坑**

在 `docs/pitfalls/frontend.md` 末尾追加：

```markdown
## N. `dispose()` 里必须停掉录音/摄像头

`_InputBarState.dispose()` 原来只取消计时器，没有调 `recorder.cancel()`。页面被弹出后麦克风仍在采集，临时文件也不会回收。

**规则**：任何持有设备句柄的 State，`dispose()` 第一件事就是释放句柄；录音统一交给 `VoiceRecordController.dispose()` 处理。
```

- [x] **Step 4: 全量验证**

Run:
```
cd web && npm run type-check && npm run lint && npm run test:run
cd app && ../flutter/bin/flutter.bat analyze && ../flutter/bin/flutter.bat test
```
Expected: 全绿。

- [x] **Step 5: 提交**

```bash
git add CLAUDE.md docs/pitfalls/web.md docs/pitfalls/frontend.md
git commit -m "docs: 更新 Web 语音现状与两条踩坑记录"
```

---

## Self-Review

**1. Spec coverage**

| Spec 章节 | 覆盖任务 |
|---|---|
| §4 状态机契约 | Task 2（Web）、Task 7（App） |
| §4.3 约束 1/2/3/4 | Task 2、Task 7（1/2/4）、Task 5（3：录音中隐藏输入栏） |
| §4.4 文案表 | Task 2（`VOICE_TEXT`）、Task 7（Dart 常量） |
| §5.1 useVoiceRecorder | Task 2 |
| §5.2 VoiceRecordBar | Task 3 |
| §5.3 ChatPage 接线 | Task 5 |
| §5.4 store 乐观发送 | Task 4 |
| §5.5 AppToast | Task 1 |
| §5.6 降级 | Task 5（置灰 + 提示） |
| §6 App controller | Task 7、Task 8 |
| §7 失败与重试 | Task 4（Web 气泡）、Task 7（App 提示） |
| §8 测试计划 | 每个 Task 的 Step 1/Step 4 |
| §9 兼容 | Task 5、Task 6 |
| §10 风险 | Task 8 Step 4 全量回归、Task 4 就地替换 |
| §11 上线清单 | Task 9（文档部分）；构建/手测留待用户执行 |

**2. Placeholder scan**：无 TBD/TODO；每个代码步骤都给了完整实现；测试断言都是具体值。

**3. Type consistency**

- Web：`VoicePhase` / `VOICE_TEXT` / `useVoiceRecorder` 返回的 `phase / seconds / start / stopAndSend / cancel / dispose` 在 Task 2 定义，Task 3（`VoicePhase` 类型）与 Task 5（全部方法）引用一致。
- `store.sendVoice(peerId, blob, durationMs)` 签名在 Task 4 定义，Task 5 按同一签名调用。
- App：`VoicePhase` / `VoiceRecordController` 的构造参数（`recorder / tempPath / onNotice / onSend`）在 Task 7 定义，Task 8 按同一命名注入；`voiceTextPermissionDenied` 等常量名一致。
- `VoiceRecorder` 接口方法名（`hasPermission / start / stop / cancel`）取自 `app/lib/im/voice_recorder.dart`，Task 7 的假实现与真实实现同名。
