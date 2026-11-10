<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppAvatar from '@/components/AppAvatar.vue'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import { useChatStore } from '@/stores/chat'
import { useDiscoveryStore } from '@/stores/discovery'
import { parseApiError } from '@/api/error'
import ChatMoreMenu from './ChatMoreMenu.vue'
import DeleteMessagesDialog from './DeleteMessagesDialog.vue'
import EmojiPanel from './EmojiPanel.vue'
import ImageViewer from './ImageViewer.vue'
import MessageBubble from './MessageBubble.vue'
import MessageMenu from './MessageMenu.vue'
import UnmatchDialog from './UnmatchDialog.vue'
import { clearDraft, readDraft, saveDraft } from './draft'
import { canQuote, quoteSummaryOf } from './quote'
import { canSelectMessage } from './select'
import { formatTime, shouldShowTime } from './time'
import { ChatMessageKind } from '@/im/types'
import type { ChatMessage } from '@/im/types'
import { canRecordVoice } from '@/im/self/voice'
import AppToast from '@/components/AppToast.vue'
import { useToast } from '@/composables/useToast'
import VoiceRecordBar from './VoiceRecordBar.vue'
import { VOICE_TEXT, useVoiceRecorder } from './useVoiceRecorder'

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
/** 已读回执:实现支持才显示 */
const readReceiptEnabled = computed(() => store.capabilities.readReceipt)
/**
 * 这条我方消息是否已被对端读过:`seq <= 对端已读位置`。
 *
 * `seq = 0` 是本地乐观消息(还没拿到服务端序号),不能算已读。
 */
function isReadByPeer(message: ChatMessage): boolean {
  return message.seq > 0 && message.seq <= (store.peerReadSeq[props.peerId] ?? 0)
}
const draft = ref(readDraft(props.peerId))
const sending = ref(false)
const scroller = ref<HTMLElement | null>(null)
const picker = ref<HTMLInputElement | null>(null)
const viewer = ref<{ urls: string[]; index: number } | null>(null)
const menu = ref<{ message: ChatMessage; x: number; y: number } | null>(null)
const showEmoji = ref(false)
const moreOpen = ref(false)
const unmatchOpen = ref(false)
const unmatching = ref(false)
const unmatchError = ref('')

// --- 多选删除(批次 T) ---
/** 多选模式开关:顶栏换成「已选 N 条」+「取消」,点气泡本体 = 切换勾选 */
const selecting = ref(false)
/** 已勾选的消息 id;每次替换成**新 Set**,让模板与 computed 的依赖稳定触发 */
const selected = ref<Set<string>>(new Set())
/** 删除确认框与进行中标志(失败时不关框里的选中,只关框 + toast) */
const bulkDeleteOpen = ref(false)
const bulkDeleting = ref(false)
/** 一次最多删 50 条:服务端上限就是这个数(`docs/ops/imserver.md` §21.6),超了直接 42201 */
const BULK_DELETE_LIMIT = 50
/** 草稿防抖窗口(批次 T):边打字边写 localStorage 没必要,停顿 300ms 落一次 */
const DRAFT_SAVE_DELAY_MS = 300

// --- 录音(状态机见 useVoiceRecorder;手势按 PC 适配为点击式) ---
const toast = useToast()

const voice = useVoiceRecorder({
  enabled: () => voiceEnabled.value,
  onSend: (blob, durationMs) => store.sendVoice(props.peerId, blob, durationMs).then(() => {}),
  onNotice: (text) => toast.show(text),
})

/** 麦克风常驻:能力不满足时置灰,点击给出原因,不让入口凭空消失。 */
function onMicClick(): void {
  if (!voiceEnabled.value) {
    toast.show(VOICE_TEXT.unsupported)
    return
  }
  void voice.start()
}

/** 录音中按 Esc 取消(PC 上的肌肉记忆);多选模式下按 Esc 退出多选。 */
function onEscape(event: KeyboardEvent): void {
  if (event.key !== 'Escape') return
  if (voice.phase.value === 'recording') {
    void voice.cancel()
    return
  }
  if (selecting.value) exitMulti()
}

function openMenu(message: ChatMessage, event: MouseEvent) {
  // 多选模式下长按/右键菜单一律失效:点消息只切换勾选(与 App 同口径)
  if (selecting.value) return
  menu.value = { message, x: event.clientX, y: event.clientY }
}

async function onMenuAction(
  action: 'copy' | 'delete' | 'multi' | 'retry' | 'recall' | 'quote',
) {
  const target = menu.value?.message
  menu.value = null
  if (!target) return
  if (action === 'multi') {
    enterMulti(target)
    return
  }
  if (action === 'quote') {
    if (canQuote(target)) startQuote(target)
    return
  }
  if (action === 'copy') {
    await navigator.clipboard?.writeText(target.text).catch(() => {})
    toast.show('已复制')
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

// --- 多选删除(批次 T)---

/**
 * 进多选模式。
 *
 * 从「多选」菜单进,顺手把**触发它的那条**勾上 —— 否则用户点了菜单里那一项之后
 * 还要再点一次同一条,是多余的一步。
 */
function enterMulti(message: ChatMessage): void {
  selecting.value = true
  selected.value = canSelectMessage(message) ? new Set([message.msgId]) : new Set()
  showEmoji.value = false
}

function exitMulti(): void {
  selecting.value = false
  selected.value = new Set()
  bulkDeleteOpen.value = false
}

function isSelected(message: ChatMessage): boolean {
  return selected.value.has(message.msgId)
}

/** 点气泡本体:切换勾选。不可勾的消息(发送中/已撤回/灰条)点了没有任何反应。 */
function toggleSelect(message: ChatMessage): void {
  if (!canSelectMessage(message)) return
  const next = new Set(selected.value)
  if (next.has(message.msgId)) {
    next.delete(message.msgId)
  } else {
    if (next.size >= BULK_DELETE_LIMIT) {
      toast.show(`一次最多删除 ${BULK_DELETE_LIMIT} 条`)
      return
    }
    next.add(message.msgId)
  }
  selected.value = next
}

/**
 * 已选的消息(按会话顺序,只算还在列表里的)。
 *
 * 用「按 id 过滤 messages」而不是直接看 `selected` 集合:消息被删掉/被服务端撤回后
 * 集合里会留下已不存在的 id,直接数 `size` 会让「已选 3 条」与眼前的气泡对不上。
 */
const selectedMessages = computed(() =>
  messages.value.filter((item) => selected.value.has(item.msgId)),
)

/** 复制文本:选中里至少有一条非空文本消息才有内容可复制 */
const copyableText = computed(() =>
  selectedMessages.value
    .filter((item) => item.kind === ChatMessageKind.text && item.text.length > 0)
    .map((item) => item.text)
    .join('\n'),
)

async function onBulkCopy(): Promise<void> {
  if (!copyableText.value) return
  await navigator.clipboard?.writeText(copyableText.value).catch(() => {})
  toast.show('已复制')
}

function openBulkDelete(): void {
  if (!selectedMessages.value.length) return
  bulkDeleteOpen.value = true
}

/**
 * 确认删除:成功 → 退出多选;失败 → **保留选中**并提示。
 *
 * 顺序在 store 里是「先服务端、后本地」,所以失败时列表与选中都还完整,
 * 用户可以原地重试(而不是先看见消息消失、再看见它回来)。
 */
async function confirmBulkDelete(): Promise<void> {
  if (bulkDeleting.value) return
  const ids = selectedMessages.value.map((item) => item.msgId)
  if (!ids.length) {
    bulkDeleteOpen.value = false
    return
  }
  bulkDeleting.value = true
  try {
    await store.deleteMessages(props.peerId, ids)
    bulkDeleteOpen.value = false
    exitMulti()
  } catch (error) {
    bulkDeleteOpen.value = false
    toast.show(parseApiError(error).message || '删除失败,请稍后再试')
  } finally {
    bulkDeleting.value = false
  }
}

// --- 草稿(批次 T)---

let draftTimer: ReturnType<typeof setTimeout> | undefined

function cancelDraftTimer(): void {
  if (draftTimer) clearTimeout(draftTimer)
  draftTimer = undefined
}

/**
 * 防抖落草稿:停顿 300ms 才写一次 `localStorage`。
 *
 * 键绑定的是**排期那一刻**的 peerId(而不是定时器触发时的 `props.peerId`):
 * 否则在 300ms 内切走会话,最后敲的几个字会写到下一个人的草稿里。
 */
function scheduleDraftSave(peerId: string, text: string): void {
  cancelDraftTimer()
  draftTimer = setTimeout(() => {
    draftTimer = undefined
    saveDraft(peerId, text)
  }, DRAFT_SAVE_DELAY_MS)
}

/**
 * 对端是否正在输入(批次 L-1)。
 *
 * 只在 store 为这个会话记着 true 时显示;store 收到 `typing` 帧置真,
 * 5 秒没有新帧自动清掉(typing 是可丢信号,服务端不补发,「停手」只能靠超时)。
 */
const peerTyping = computed(() => store.peerTyping[props.peerId] === true)

// 输入框有变化就按 3 秒节流发一次 typing;清空输入框不发(那意味着「不打了」)。
// 同一处顺手落草稿(防抖 300ms):typing 与草稿都只关心「用户刚敲了什么」。
watch(draft, (value) => {
  if (value) store.notifyTyping(props.peerId)
  scheduleDraftSave(props.peerId, value)
})

/**
 * 当前引用目标(批次 L-2)。只显示「引用谁 + 摘要」;**上行只发 id**,
 * 真正发给对端的快照由服务端回库查后生成。
 */
const quoteTarget = computed(() => store.quoteTarget)
const quoteSender = computed(() => {
  const target = quoteTarget.value
  if (!target) return ''
  return target.from === props.peerId ? peerName.value || '对方' : '我'
})

/** 选中一条消息作为引用目标:输入栏上方出现引用条。 */
function startQuote(message: ChatMessage): void {
  store.setQuoteTarget({
    msgId: Number(message.msgId),
    // 自己的消息用当前登录的 IM id 署名;对端的就是会话对端
    from: message.isSelf ? store.selfImId : props.peerId,
    text: quoteSummaryOf(message),
  })
}

/**
 * 点引用块:跳到被引用的原消息。
 *
 * 原消息不在当前已加载的记录里(翻页翻出去了 / 被删除)时只提示,不假装跳过去。
 */
function jumpToQuote(msgId: number): void {
  // 多选模式下引用块不响应:此时点气泡的任何部位都只切换勾选
  if (selecting.value) return
  const id = String(msgId)
  if (!messages.value.some((item) => item.msgId === id)) {
    toast.show('原消息不在当前记录中')
    return
  }
  void focusMessage(id)
}

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
  document.addEventListener('keydown', onEscape)
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
  document.removeEventListener('keydown', onEscape)
  // 离开聊天页立即清掉「正在输入…」(批次 L-1):不能把上一个人的提示留到下次进来
  store.clearPeerTyping(props.peerId)
  // 草稿:把没落盘的那 300ms 立刻补上,否则「打完最后一个字就走」会丢字
  cancelDraftTimer()
  saveDraft(props.peerId, draft.value)
  // 离开页面一律取消:绝不把没录完的话发出去
  voice.dispose()
})

watch(
  () => props.peerId,
  async (_next, previous) => {
    // 切会话:先把上一个会话的草稿落盘,再把新会话的草稿回填进输入框(批次 T)
    cancelDraftTimer()
    if (previous) saveDraft(previous, draft.value)
    draft.value = readDraft(props.peerId)
    // 多选是当前会话的临时状态:换人必须退出,否则会拿着 A 的勾选去删 B 的消息
    exitMulti()
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

/**
 * 跨端删除(多端在线 K-3):我在另一台设备上删了这个会话后,store 会把它从列表移除。
 * 正停在这一页就退回会话列表 —— 否则会停在一个已经不存在的会话里继续发消息。
 *
 * `hadConversation` 兜住「深链进来、列表还没拉到」的情况:那种时候 conversation
 * 本来就为空,不是被删了,不能跳走。所以初值要按挂载那一刻的状态取。
 */
let hadConversation = conversation.value !== undefined
watch(conversation, (current) => {
  if (current) {
    hadConversation = true
    return
  }
  if (!hadConversation) return
  hadConversation = false
  void router.push({ name: 'chats' })
})

async function onSend() {
  const text = draft.value.trim()
  if (!text || sending.value) return
  sending.value = true
  try {
    await store.sendText(props.peerId, text)
    draft.value = ''
    // 发出去了就不该再有草稿(批次 T):先撤掉排期中的落盘,再清键
    cancelDraftTimer()
    clearDraft(props.peerId)
  } finally {
    sending.value = false
  }
}

async function onRetry(message: ChatMessage) {
  await store.resend(message).catch(() => {})
}

/** 贴纸是**直接发送**(不插输入框):点一下就是一条消息(批次 J)。 */
async function onSendSticker(stickerId: string) {
  await store.sendSticker(props.peerId, stickerId).catch(() => {})
}

function onOpenImage(message: ChatMessage) {
  // 多选模式下点图片 = 勾选,不打开大图
  if (selecting.value) return
  const urls = messages.value
    .filter((item) => item.kind === ChatMessageKind.image)
    .map((item) => item.imageLargeUrl ?? item.imageUrl ?? '')
    .filter(Boolean)
  const target = message.imageLargeUrl ?? message.imageUrl ?? ''
  viewer.value = { urls: urls.length ? urls : [target], index: Math.max(urls.indexOf(target), 0) }
}

/** 选图 → 交给 store 乐观上屏(占位 + 本地预览 + 失败可重发) */
async function onPickImage(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // 允许重复选同一张
  if (!file) return
  await store.sendImage(props.peerId, file).catch(() => {})
}
</script>

<template>
  <section class="chat">
    <header class="chat__head">
      <!-- 多选模式(批次 T):顶栏只剩「取消」与已选条数,其它入口一律让位 -->
      <template v-if="selecting">
        <button
          type="button"
          class="chat__cancel"
          data-test="chat-multi-cancel"
          @click="exitMulti"
        >
          取消
        </button>
        <h1 class="chat__title" data-test="chat-multi-count">已选 {{ selectedMessages.length }} 条</h1>
      </template>
      <template v-else>
        <RouterLink class="chat__back" :to="{ name: 'chats' }">←</RouterLink>
        <AppAvatar :src="peerAvatar" :name="peerName || title" :size="32" />
        <div class="chat__head-text">
          <h1 class="chat__title">{{ title }}</h1>
          <p v-if="peerTyping" class="chat__typing" data-test="chat-typing">对方正在输入…</p>
        </div>
        <button
          type="button"
          class="chat__more"
          aria-label="更多"
          @click="moreOpen = !moreOpen"
        >
          ⋯
        </button>
      </template>
    </header>

    <p v-if="unmatched" class="chat__unmatched">你们已解除配对</p>

    <div ref="scroller" class="chat__scroll">
      <template v-for="row in rows" :key="row.message.msgId">
        <p v-if="row.time" class="chat__time">{{ row.time }}</p>
        <MessageBubble
          :message="row.message"
          :peer-name="peerName"
          :peer-avatar="peerAvatar"
          :local-file="store.pendingFiles[row.message.msgId] ?? null"
          :hit="row.message.msgId === hitId"
          :read-receipt-enabled="readReceiptEnabled"
          :is-read="isReadByPeer(row.message)"
          :selecting="selecting"
          :selectable="canSelectMessage(row.message)"
          :selected="isSelected(row.message)"
          @retry="onRetry(row.message)"
          @open-image="onOpenImage"
          @menu="openMenu(row.message, $event)"
          @jump-quote="jumpToQuote"
          @select="toggleSelect(row.message)"
        />
      </template>
    </div>

    <!-- 引用条(批次 L-2):长按/右键「引用」后出现在输入栏**上方**,可点 × 取消 -->
    <div v-if="quoteTarget && !selecting" class="chat__quote-bar" data-test="chat-quote-bar">
      <div class="chat__quote-main">
        <span class="chat__quote-name">引用 {{ quoteSender }}</span>
        <span class="chat__quote-text">{{ quoteTarget.text }}</span>
      </div>
      <button
        type="button"
        class="chat__quote-close"
        aria-label="取消引用"
        data-test="chat-quote-close"
        @click="store.clearQuoteTarget()"
      >
        ×
      </button>
    </div>

    <!-- 多选底部操作条(批次 T):删除是单方删除,复制只在有文本消息时可用 -->
    <footer v-if="selecting" class="chat__bulk" data-test="chat-bulk-bar">
      <span class="chat__bulk-hint">点消息选中,再选择要做的操作</span>
      <AppButton
        class="chat__bulk-copy"
        variant="ghost"
        data-test="chat-multi-copy"
        :disabled="!copyableText"
        @click="onBulkCopy"
      >
        复制文本
      </AppButton>
      <AppButton
        class="chat__bulk-delete"
        variant="danger"
        data-test="chat-multi-delete"
        :disabled="selectedMessages.length === 0"
        @click="openBulkDelete"
      >
        删除
      </AppButton>
    </footer>

    <footer v-else class="chat__composer">
      <VoiceRecordBar
        v-if="voice.phase.value !== 'idle'"
        :phase="voice.phase.value"
        :seconds="voice.seconds.value"
        @cancel="voice.cancel()"
        @send="voice.stopAndSend()"
      />
      <template v-else>
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
          type="button"
          class="chat__image"
          :class="{ 'chat__image--off': !voiceEnabled }"
          aria-label="语音消息"
          title="点击开始录音"
          :aria-disabled="!voiceEnabled || unmatched"
          :disabled="unmatched"
          @click="onMicClick"
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
      </template>
    </footer>

    <EmojiPanel
      v-if="showEmoji"
      @pick="pickEmoji"
      @sticker="onSendSticker"
      @close="showEmoji = false"
    />

    <AppToast :text="toast.text.value" />

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

    <DeleteMessagesDialog
      :open="bulkDeleteOpen"
      :count="selectedMessages.length"
      :busy="bulkDeleting"
      @close="bulkDeleteOpen = false"
      @confirm="confirmBulkDelete"
    />

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
/* 多选模式顶栏的「取消」:文字按钮,与返回箭头同一视觉重量 */
.chat__cancel {
  flex: none;
  border: none;
  background: none;
  color: var(--color-brand);
  font: inherit;
  font-size: var(--text-body);
  cursor: pointer;
}
.chat__cancel:hover {
  opacity: 0.8;
}
/* 多选底部操作条:左侧提示、右侧两个动作(删除是危险色) */
.chat__bulk {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-md) var(--space-section-gap);
  border-top: 1px solid var(--color-divider);
  background: var(--color-bg-card);
}
.chat__bulk-hint {
  flex: 1;
  min-width: 0;
  color: var(--color-text3);
  font-size: var(--text-badge);
}
.chat__title {
  margin: 0;
  font-size: var(--text-subtitle);
  font-weight: var(--weight-semibold);
}
/* 标题块:昵称 + 「对方正在输入…」(批次 L-1),两行紧凑排列,不挤压头像 */
.chat__head-text {
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-width: 0;
}
.chat__typing {
  margin: 0;
  font-size: var(--text-micro);
  line-height: 1.2;
  color: var(--color-brand);
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
/* 引用条:输入栏上方的窄条,显示「引用谁 + 摘要」 */
.chat__quote-bar {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-section-gap) 0;
  background: var(--color-bg-card);
}
.chat__quote-main {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  padding: var(--space-xs) var(--space-sm);
  border-left: 3px solid var(--color-brand);
  border-radius: var(--radius-chip);
  background: var(--color-divider);
}
.chat__quote-name {
  font-size: var(--text-badge);
  color: var(--color-brand);
}
.chat__quote-text {
  font-size: var(--text-badge);
  color: var(--color-text2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chat__quote-close {
  flex: none;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: var(--radius-full);
  background: none;
  color: var(--color-text2);
  font-size: var(--text-subtitle);
  cursor: pointer;
}
.chat__quote-close:hover {
  background: var(--hover-overlay);
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
/* 置灰但仍可点击:点了要能告诉用户为什么不能用,disabled 会吞掉 click */
.chat__image--off {
  color: var(--color-text3);
  cursor: default;
}
</style>




