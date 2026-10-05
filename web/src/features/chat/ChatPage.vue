<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import AppAvatar from '@/components/AppAvatar.vue'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import { useChatStore } from '@/stores/chat'
import ImageViewer from './ImageViewer.vue'
import MessageBubble from './MessageBubble.vue'
import { formatTime, shouldShowTime } from './time'
import { ChatMessageKind } from '@/im/types'
import type { ChatMessage } from '@/im/types'

const props = defineProps<{ peerId: string }>()

const store = useChatStore()
const draft = ref('')
const sending = ref(false)
const scroller = ref<HTMLElement | null>(null)
const picker = ref<HTMLInputElement | null>(null)
/** 发送中的图片本地预览(blob 还没变成服务端 URL) */
const localFiles = ref<Record<string, File>>({})
const viewer = ref<{ urls: string[]; index: number } | null>(null)

const messages = computed(() => store.messagesOf(props.peerId))
const conversation = computed(() =>
  store.conversations.find((item) => item.peerId === props.peerId),
)
const peerName = computed(() => conversation.value?.showName ?? '')
const peerAvatar = computed(() => conversation.value?.faceUrl ?? null)
const title = computed(() => peerName.value || (props.peerId === 'system_notice' ? '系统通知' : props.peerId))

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

onMounted(async () => {
  await store.openConversation(props.peerId).catch(() => {})
  await scrollToBottom()
})

watch(
  () => props.peerId,
  async () => {
    await store.openConversation(props.peerId).catch(() => {})
    await scrollToBottom()
  },
)

watch(
  () => messages.value.length,
  () => void scrollToBottom(),
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
    timestamp: Date.now(),
    kind: ChatMessageKind.image,
    text: '',
    isPending: true,
    isFailed: false,
    imageUrl: null,
    imageLargeUrl: null,
  }
  localFiles.value = { ...localFiles.value, [placeholderId]: file }
  store.messages[props.peerId] = [...messages.value, message]

  try {
    const sent = await store.sendImage(props.peerId, file)
    // 用真实消息替换占位
    store.messages[props.peerId] = messages.value
      .filter((item) => item.msgId !== placeholderId)
      .concat(sent)
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
    </header>

    <div ref="scroller" class="chat__scroll">
      <template v-for="row in rows" :key="row.message.msgId">
        <p v-if="row.time" class="chat__time">{{ row.time }}</p>
        <MessageBubble
          :message="row.message"
          :peer-name="peerName"
          :peer-avatar="peerAvatar"
          :local-file="localFiles[row.message.msgId] ?? null"
          @retry="onRetry(row.message)"
          @open-image="onOpenImage"
        />
      </template>
    </div>

    <footer class="chat__composer">
      <input
        ref="picker"
        type="file"
        accept="image/*"
        class="chat__picker"
        @change="onPickImage"
      />
      <button
        type="button"
        class="chat__image"
        aria-label="发送图片"
        @click="picker?.click()"
      >
        🖼️
      </button>
      <AppInput
        v-model="draft"
        placeholder="说点什么…"
        :maxlength="2000"
        @enter="onSend"
      />
      <AppButton class="chat__send" :loading="sending" @click="onSend">发送</AppButton>
    </footer>

    <ImageViewer
      v-if="viewer"
      :urls="viewer.urls"
      :index="viewer.index"
      @close="viewer = null"
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
</style>
