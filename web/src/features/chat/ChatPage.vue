<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppAvatar from '@/components/AppAvatar.vue'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import { useChatStore } from '@/stores/chat'
import { useDiscoveryStore } from '@/stores/discovery'
import ChatMoreMenu from './ChatMoreMenu.vue'
import EmojiPanel from './EmojiPanel.vue'
import ImageViewer from './ImageViewer.vue'
import MessageBubble from './MessageBubble.vue'
import MessageMenu from './MessageMenu.vue'
import UnmatchDialog from './UnmatchDialog.vue'
import { formatTime, shouldShowTime } from './time'
import { ChatMessageKind } from '@/im/types'
import type { ChatMessage } from '@/im/types'
import { canRecordVoice, pickMimeType } from '@/im/self/voice'

const props = defineProps<{ peerId: string }>()

const store = useChatStore()
const discovery = useDiscoveryStore()
const router = useRouter()
const route = useRoute()
/** 搜索命中带过来的定位目标(见 SearchPage) */
const focusId = typeof route.query.focus === 'string' ? route.query.focus : ''
const hitId = ref('')
let highlightTimer: ReturnType<typeof setTimeout> | undefined
/** 定位过程中禁止「自动滚到底」,否则刚滚到的位置会被拉回最新一条 */
let focusing = false
// 能力位取 store(连上之后才有真值);直接读 getImClient().capabilities 会永远是兜底 false
const imageEnabled = computed(() => store.capabilities.image)
/** 语音入口:后端能力 + 浏览器能录音(需 HTTPS 或 localhost) */
const voiceEnabled = computed(() => store.capabilities.voice && canRecordVoice())
const draft = ref('')
const sending = ref(false)
const scroller = ref<HTMLElement | null>(null)
const picker = ref<HTMLInputElement | null>(null)
/** 发送中的图片本地预览(blob 还没变成服务端 URL) */
const localFiles = ref<Record<string, File>>({})
const viewer = ref<{ urls: string[]; index: number } | null>(null)
const menu = ref<{ message: ChatMessage; x: number; y: number } | null>(null)
const showEmoji = ref(false)
const copied = ref(false)
const moreOpen = ref(false)
const unmatchOpen = ref(false)
const unmatching = ref(false)
const unmatchError = ref('')

// --- 按住说话 ---
const recording = ref(false)
const cancelArmed = ref(false)
const recordSeconds = ref(0)
let mediaRecorder: MediaRecorder | null = null
let mediaStream: MediaStream | null = null
let chunks: Blob[] = []
let recordStartedAt = 0
let recordStartY = 0
let recordTimer: ReturnType<typeof setInterval> | undefined

async function startRecording(event: PointerEvent): Promise<void> {
  if (!voiceEnabled.value || recording.value || unmatched.value) return
  const mime = pickMimeType()
  if (!mime) return
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true })
  } catch {
    return
  }
  chunks = []
  mediaRecorder = new MediaRecorder(mediaStream, { mimeType: mime })
  mediaRecorder.ondataavailable = (event) => {
    if (event.data.size > 0) chunks.push(event.data)
  }
  mediaRecorder.start()
  recordStartedAt = performance.now()
  recordStartY = event.clientY
  recording.value = true
  cancelArmed.value = false
  recordSeconds.value = 0
  recordTimer = setInterval(() => {
    recordSeconds.value = Math.min(60, Math.ceil((performance.now() - recordStartedAt) / 1000))
    if (recordSeconds.value >= 60) void finishRecording()
  }, 200)
}

function onVoiceMove(event: PointerEvent): void {
  if (!recording.value) return
  cancelArmed.value = event.clientY - recordStartY < -60
}

async function finishRecording(): Promise<void> {
  if (!recording.value) return
  const cancelled = cancelArmed.value
  const duration = performance.now() - recordStartedAt
  recording.value = false
  cancelArmed.value = false
  if (recordTimer) {
    clearInterval(recordTimer)
    recordTimer = undefined
  }
  const current = mediaRecorder
  mediaRecorder = null
  mediaStream?.getTracks().forEach((track) => track.stop())
  mediaStream = null
  if (!current) return
  const blob = await new Promise<Blob>((resolve) => {
    current.onstop = () => resolve(new Blob(chunks, { type: current.mimeType }))
    current.stop()
  })
  if (cancelled || duration < 1000) return
  await store.sendVoice(props.peerId, blob, duration).catch(() => {})
}

function openMenu(message: ChatMessage, event: MouseEvent) {
  menu.value = { message, x: event.clientX, y: event.clientY }
}

async function onMenuAction(action: 'copy' | 'delete' | 'retry' | 'recall') {
  const target = menu.value?.message
  menu.value = null
  if (!target) return
  if (action === 'copy') {
    await navigator.clipboard?.writeText(target.text).catch(() => {})
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
    return
  }
  if (action === 'recall') {
    await store.revokeMessage(target).catch(() => {})
    return
  }
  if (action === 'delete') {
    await store.deleteMessage(target).catch(() => {})
    return
  }
  await store.resend(target).catch(() => {})
}

function pickEmoji(emoji: string) {
  draft.value += emoji
}

const messages = computed(() => store.messagesOf(props.peerId))
const conversation = computed(() =>
  store.conversations.find((item) => item.peerId === props.peerId),
)
const peerName = computed(() => conversation.value?.showName ?? '')
const peerAvatar = computed(() => conversation.value?.faceUrl ?? null)
const title = computed(() => peerName.value || (props.peerId === 'system_notice' ? '系统通知' : props.peerId))

/** 配对列表已加载且没有这个人 → 已被对方解除(系统通知不是配对,排除)。 */
const unmatched = computed(
  () =>
    props.peerId !== 'system_notice' &&
    discovery.matchesLoaded &&
    !discovery.matches.some((item) => item.im_user_id === props.peerId),
)

function openUnmatch(): void {
  moreOpen.value = false
  unmatchOpen.value = true
}

async function onUnmatch(): Promise<void> {  if (unmatching.value) return
  unmatching.value = true
  unmatchError.value = ''
  try {
    await discovery.unmatch(Number(props.peerId.replace('u', '')))
    await store.deleteConversation(props.peerId).catch(() => {})
    unmatchOpen.value = false
    await router.push({ name: 'chats' })
  } catch {
    unmatchError.value = '解除失败,请稍后重试'
  } finally {
    unmatching.value = false
  }
}

/** 时间条:第一条、以及与前一条间隔 > 5 分钟时插 */
const rows = computed(() =>
  messages.value.map((message, index) => ({
    message,
    time:
      shouldShowTime(index === 0 ? null : messages.value[index - 1].timestamp, message.timestamp) &&
      // 系统灰条不单独插时间条,避免刷屏
      message.kind !== 'matchNotice' &&
      message.kind !== 'banNotice'
        ? formatTime(message.timestamp)
        : null,
  })),
)

async function scrollToBottom() {
  await nextTick()
  const element = scroller.value
  if (element) element.scrollTop = element.scrollHeight
}

/** 在已渲染的气泡里按 msgId 找元素(不用 CSS.escape,msgId 里可能有特殊字符)。 */
function messageElement(msgId: string): HTMLElement | null {
  const root = scroller.value
  if (!root) return null
  return (
    Array.from(root.querySelectorAll<HTMLElement>('[data-msg-id]')).find(
      (item) => item.dataset.msgId === msgId,
    ) ?? null
  )
}

/** 从搜索结果进聊天页:往前翻到目标消息 → 滚到中间 → 高亮 1.5s。 */
async function focusMessage(msgId: string): Promise<void> {
  focusing = true
  try {
    await store.loadOlder(props.peerId, msgId).catch(() => {})
    await nextTick()
    const element = messageElement(msgId)
    if (!element) return
    element.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
    hitId.value = msgId
    clearTimeout(highlightTimer)
    highlightTimer = setTimeout(() => (hitId.value = ''), 1500)
  } finally {
    focusing = false
  }
}

onMounted(async () => {
  // 深链直接进聊天页时,IM 可能还没连(connect 幂等,已在连/已连会直接返回)
  await store.connect().catch(() => {})
  // 配对列表没加载过就拉一次:否则「已被解除」永远发现不了
  if (!discovery.matchesLoaded) await discovery.loadMatches(true).catch(() => {})
  // 会话列表里没有这个人(例如从配对列表点进来)→ 先拉一次,免得标题只剩 u41
  if (!conversation.value) await store.loadConversations().catch(() => {})
  await store.openConversation(props.peerId).catch(() => {})
  // 带 focus 时不滚到底:直接定位到命中的那条
  if (focusId) await focusMessage(focusId)
  else await scrollToBottom()
})

onUnmounted(() => {
  clearTimeout(highlightTimer)
  if (recordTimer) clearInterval(recordTimer)
  if (recording.value) void finishRecording()
  mediaStream?.getTracks().forEach((track) => track.stop())
})

watch(
  () => props.peerId,
  async () => {
    if (!conversation.value) await store.loadConversations().catch(() => {})
    await store.openConversation(props.peerId).catch(() => {})
    await scrollToBottom()
  },
)

watch(
  () => messages.value.length,
  () => {
    if (!focusing) void scrollToBottom()
  },
)

async function onSend() {
  const text = draft.value.trim()
  if (!text || sending.value) return
  sending.value = true
  try {
    await store.sendText(props.peerId, text)
    draft.value = ''
  } finally {
    sending.value = false
  }
}

async function onRetry(message: ChatMessage) {
  await store.resend(message).catch(() => {})
}

function onOpenImage(message: ChatMessage) {
  const urls = messages.value
    .filter((item) => item.kind === ChatMessageKind.image)
    .map((item) => item.imageLargeUrl ?? item.imageUrl ?? '')
    .filter(Boolean)
  const target = message.imageLargeUrl ?? message.imageUrl ?? ''
  viewer.value = { urls: urls.length ? urls : [target], index: Math.max(urls.indexOf(target), 0) }
}

/** 选图 → 本地立刻上屏(blob 预览)→ 发送 */
async function onPickImage(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // 允许重复选同一张
  if (!file) return

  const placeholderId = `local-${Date.now()}`
  const message: ChatMessage = {
    msgId: placeholderId,
    peerId: props.peerId,
    isSelf: true,
    seq: 0,
    timestamp: Date.now(),
    kind: ChatMessageKind.image,
    text: '',
    senderName: '',
    senderAvatar: null,
    isPending: true,
    isFailed: false,
    imageUrl: null,
    imageLargeUrl: null,
    isRevoked: false,
  }
  localFiles.value = { ...localFiles.value, [placeholderId]: file }
  store.messages[props.peerId] = [...messages.value, message]

  try {
    const sent = await store.sendImage(props.peerId, file)
    // store.sendImage 已经把真实消息追加进列表了,这里只把占位删掉(别再 concat,会重复一条)
    store.messages[props.peerId] = messages.value.filter((item) => item.msgId !== placeholderId)
    void sent
  } catch {
    store.messages[props.peerId] = messages.value.map((item) =>
      item.msgId === placeholderId ? { ...item, isPending: false, isFailed: true } : item,
    )
  }
}
</script>

<template>
  <section class="chat">
    <header class="chat__head">
      <RouterLink class="chat__back" :to="{ name: 'chats' }">←</RouterLink>
      <AppAvatar :src="peerAvatar" :name="peerName || title" :size="32" />
      <h1 class="chat__title">{{ title }}</h1>
      <button
        type="button"
        class="chat__more"
        aria-label="更多"
        @click="moreOpen = !moreOpen"
      >
        ⋯
      </button>
    </header>

    <p v-if="unmatched" class="chat__unmatched">你们已解除配对</p>

    <div ref="scroller" class="chat__scroll">
      <template v-for="row in rows" :key="row.message.msgId">
        <p v-if="row.time" class="chat__time">{{ row.time }}</p>
        <MessageBubble
          :message="row.message"
          :peer-name="peerName"
          :peer-avatar="peerAvatar"
          :local-file="localFiles[row.message.msgId] ?? null"
          :hit="row.message.msgId === hitId"
          @retry="onRetry(row.message)"
          @open-image="onOpenImage"
          @menu="openMenu(row.message, $event)"
        />
      </template>
    </div>

    <div v-if="recording" class="chat__recording" role="status">
      <p class="chat__recording-time">{{ recordSeconds }}″</p>
      <p class="chat__recording-hint">
        {{ cancelArmed ? '松开取消' : '松开发送,上滑取消' }}
      </p>
    </div>

    <footer class="chat__composer">
      <input
        v-if="imageEnabled"
        ref="picker"
        type="file"
        accept="image/*"
        class="chat__picker"
        @change="onPickImage"
      />
      <button
        v-if="imageEnabled"
        type="button"
        class="chat__image"
        aria-label="发送图片"
        :disabled="unmatched"
        @click="picker?.click()"
      >
        🖼️
      </button>
      <button
        v-if="voiceEnabled"
        type="button"
        class="chat__image"
        aria-label="按住说话"
        :disabled="unmatched"
        @pointerdown.prevent="startRecording"
        @pointermove="onVoiceMove"
        @pointerup="finishRecording"
        @pointercancel="finishRecording"
      >
        🎤
      </button>
      <button
        type="button"
        class="chat__image"
        aria-label="表情"
        :disabled="unmatched"
        @click="showEmoji = !showEmoji"
      >
        😊
      </button>
      <AppInput
        v-model="draft"
        placeholder="说点什么…"
        :maxlength="2000"
        :disabled="unmatched"
        @enter="onSend"
      />
      <AppButton
        class="chat__send"
        :loading="sending"
        :disabled="unmatched"
        @click="onSend"
      >
        发送
      </AppButton>
    </footer>

    <EmojiPanel v-if="showEmoji" @pick="pickEmoji" @close="showEmoji = false" />

    <p v-if="copied" class="chat__toast">已复制</p>

    <MessageMenu
      v-if="menu"
      :message="menu.message"
      :x="menu.x"
      :y="menu.y"
      @close="menu = null"
      @action="onMenuAction"
    />

    <ImageViewer
      v-if="viewer"
      :urls="viewer.urls"
      :index="viewer.index"
      @close="viewer = null"
    />

    <ChatMoreMenu v-if="moreOpen" @close="moreOpen = false" @unmatch="openUnmatch" />

    <UnmatchDialog
      :open="unmatchOpen"
      :busy="unmatching"
      :error="unmatchError"
      @close="unmatchOpen = false"
      @confirm="onUnmatch"
    />
  </section>
</template>

<style scoped>
.chat {
  display: flex;
  flex-direction: column;
  height: 100vh;
  min-height: 0;
}
.chat__head {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  height: 62px;
  padding: 0 var(--space-section-gap);
  border-bottom: 1px solid var(--color-divider);
  background: var(--color-bg-card);
}
.chat__back {
  font-size: var(--text-title);
  color: var(--color-text2);
}
.chat__title {
  margin: 0;
  font-size: var(--text-subtitle);
  font-weight: var(--weight-semibold);
}
.chat__more {
  margin-left: auto;
  border: none;
  background: none;
  font-size: var(--text-title);
  color: var(--color-text2);
  cursor: pointer;
}
.chat__unmatched {
  margin: 0;
  padding: var(--space-xs) var(--space-section-gap);
  background: var(--color-divider);
  color: var(--color-text2);
  font-size: var(--text-badge);
  text-align: center;
}
.chat__scroll {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  gap: var(--space-md);
  overflow-y: auto;
  padding: var(--space-lg) var(--space-section-gap);
}
.chat__time {
  align-self: center;
  margin: 0;
  font-size: var(--text-badge);
  color: var(--color-text3);
}
.chat__composer {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-md) var(--space-section-gap);
  border-top: 1px solid var(--color-divider);
  background: var(--color-bg-card);
}
.chat__send {
  flex: none;
}
.chat__picker {
  display: none;
}
.chat__image {
  flex: none;
  width: 40px;
  height: 40px;
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-input);
  background: var(--color-bg-card);
  font-size: var(--text-subtitle);
  cursor: pointer;
}
.chat__image:hover {
  background: var(--hover-overlay);
}
.chat__toast {
  position: fixed;
  bottom: 88px;
  left: 50%;
  transform: translateX(-50%);
  margin: 0;
  padding: var(--space-xs) var(--space-md);
  border-radius: var(--radius-full);
  background: var(--color-text1);
  color: var(--color-bg-card);
  font-size: var(--text-badge);
}
.chat__recording {
  position: fixed;
  bottom: 120px;
  left: 50%;
  transform: translateX(-50%);
  margin: 0;
  padding: var(--space-md) var(--space-lg);
  border-radius: var(--radius-card);
  background: var(--color-text1);
  color: var(--color-bg-card);
  text-align: center;
  box-shadow: var(--shadow-card);
  z-index: 10;
}
.chat__recording-time {
  margin: 0;
  font-size: var(--text-title);
}
.chat__recording-hint {
  margin: var(--space-xs) 0 0;
  font-size: var(--text-badge);
  opacity: 0.8;
}
</style>




