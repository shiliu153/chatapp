<script setup lang="ts">
import { computed } from 'vue'
import AppAvatar from '@/components/AppAvatar.vue'
import MessageImage from './MessageImage.vue'
import MessageVoice from './MessageVoice.vue'
import { stickerById, UNKNOWN_STICKER_LABEL } from './stickers'
import { ChatMessageKind } from '@/im/types'
import type { ChatMessage } from '@/im/types'

const props = withDefaults(
  defineProps<{
    message: ChatMessage
    peerName?: string
    peerAvatar?: string | null
    localFile?: File | null
    /** 搜索定位命中:短暂高亮(见 ChatPage focusMessage) */
    hit?: boolean
    /** 对端已读这条(只对我方消息有意义,由 ChatPage 用 peerReadSeq 比较得出) */
    isRead?: boolean
    /** 是否支持已读回执(不支持时宁可不显示,也不要假状态) */
    readReceiptEnabled?: boolean
  }>(),
  {
    peerName: '',
    peerAvatar: null,
    localFile: null,
    hit: false,
    isRead: false,
    readReceiptEnabled: false,
  },
)
defineEmits<{
  retry: []
  openImage: [ChatMessage]
  menu: [MouseEvent]
  /** 点了气泡上方的引用块:跳到被引用的原消息(批次 L-2) */
  jumpQuote: [number]
}>()

/**
 * 我方消息的已读标记。
 *
 * 口径与 App 一致:
 * - 失败交给「重发」按钮,发送中显示「发送中…」,这两种情况不显示已读;
 * - **未读不写字**(微信口径):一屏十几条都挂「未读」是纯噪声,而且区分不了
 *   「已送达未读 / 没送达」;有没有「已读」两个字本身就是未读的信号;
 * - 不支持已读回执时一律不显示。
 */
const showRead = computed(
  () =>
    props.readReceiptEnabled &&
    props.isRead &&
    props.message.isSelf &&
    !props.message.isPending &&
    !props.message.isFailed &&
    !props.message.isRevoked,
)

const isNotice = computed(
  () =>
    props.message.kind === ChatMessageKind.matchNotice ||
    props.message.kind === ChatMessageKind.banNotice,
)
const isImage = computed(() => props.message.kind === ChatMessageKind.image)
const isVoice = computed(() => props.message.kind === ChatMessageKind.voice)
const isUnsupported = computed(() => props.message.kind === ChatMessageKind.other)
/** 贴纸(批次 J):资源在本地,未知 id 降级成「[贴纸]」文本 */
const isSticker = computed(() => props.message.kind === ChatMessageKind.sticker)
const sticker = computed(() => stickerById(props.message.stickerId))

/**
 * 引用块(批次 L-2):摘要来自**服务端快照**(`message.ref`),客户端不自己拼。
 *
 * 没有引用时服务端根本不下发 `ref` 键,所以这里整块都不渲染 —— 老消息、
 * 老服务端都不会因此多出一个空框。
 */
const quote = computed(() => props.message.ref ?? null)
/** 引用块的署名:同一会话只有两个人,不是对端就是我。 */
const quoteSender = computed(() => {
  const current = quote.value
  if (!current) return ''
  return current.from === props.message.peerId ? props.peerName || '对方' : '我'
})
/** 引用块的摘要:已撤回只显示「消息已撤回」,不显示原文。 */
const quoteText = computed(() => {
  const current = quote.value
  if (!current) return ''
  if (current.revoked) return '消息已撤回'
  return current.text || '[消息]'
})
</script>

<template>
  <!-- 撤回:居中弱化,不显示原内容 -->
  <p
    v-if="props.message.isRevoked"
    class="message-bubble message-bubble--notice"
    :class="{ 'message-bubble--hit': props.hit }"
    :data-msg-id="props.message.msgId"
  >
    {{ props.message.isSelf ? '你撤回了一条消息' : '对方撤回了一条消息' }}
  </p>

  <!-- 系统灰条:居中 pill,不属于任何一方 -->
  <p
    v-else-if="isNotice"
    class="message-bubble message-bubble--notice"
    :class="{ 'message-bubble--hit': props.hit }"
    :data-msg-id="props.message.msgId"
  >
    {{ props.message.text }}
  </p>

  <div
    v-else
    class="message-bubble"
    :class="[
      props.message.isSelf ? 'message-bubble--self' : 'message-bubble--peer',
      { 'message-bubble--hit': props.hit },
    ]"
    :data-msg-id="props.message.msgId"
    @contextmenu.prevent="$emit('menu', $event)"
  >
    <AppAvatar
      v-if="!props.message.isSelf"
      :src="props.peerAvatar"
      :name="props.peerName"
      :size="36"
    />

    <!-- 悬停出现的 ⋯:与右键菜单是同一组件、同一入口函数(spec §6.4) -->
    <button
      type="button"
      class="message-bubble__more"
      aria-label="消息操作"
      @click="$emit('menu', $event)"
    >
      ⋯
    </button>

    <div class="message-bubble__stack">
      <!-- 引用块在气泡**上方**:它是「我在回应什么」,不该抢正文的视线 -->
      <button
        v-if="quote"
        type="button"
        class="message-bubble__quote"
        data-testid="quote-block"
        @click="$emit('jumpQuote', quote.msgId)"
      >
        <span class="message-bubble__quote-name">{{ quoteSender }}</span>
        <span
          class="message-bubble__quote-text"
          :data-testid="quote.revoked ? 'quote-revoked' : undefined"
        >
          {{ quoteText }}
        </span>
      </button>
      <div
        class="message-bubble__body"
        :class="{ 'message-bubble__body--sticker': isSticker }"
      >
        <img
          v-if="isSticker && sticker"
          class="message-bubble__sticker"
          :src="sticker.src"
          :alt="sticker.label"
          :data-testid="`sticker-${sticker.id}`"
        />
        <span v-else-if="isSticker" class="message-bubble__text" data-testid="sticker-unknown">
          {{ UNKNOWN_STICKER_LABEL }}
        </span>
        <MessageImage
          v-else-if="isImage"
          :message="props.message"
          :local-file="props.localFile"
          @open="$emit('openImage', props.message)"
        />
        <MessageVoice v-else-if="isVoice" :message="props.message" />
        <span v-else-if="isUnsupported" class="message-bubble__text">[暂不支持的消息类型]</span>
        <span v-else class="message-bubble__text">{{ props.message.text }}</span>

        <button
          v-if="props.message.isFailed"
          type="button"
          class="message-bubble__retry"
          @click="$emit('retry')"
        >
          重发
        </button>
        <span v-else-if="props.message.isPending" class="message-bubble__pending">发送中…</span>
        <span v-else-if="showRead" class="message-bubble__read" data-testid="chat-read">已读</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.message-bubble {
  display: flex;
  align-items: flex-end;
  gap: var(--space-sm);
  max-width: var(--bubble-max-ratio);
}
.message-bubble--peer {
  align-self: flex-start;
}
.message-bubble--self {
  align-self: flex-end;
  flex-direction: row-reverse;
}
/* 引用块 + 气泡:竖排,自己的消息靠右对齐 */
.message-bubble__stack {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-xs);
  min-width: 0;
}
.message-bubble--self .message-bubble__stack {
  align-items: flex-end;
}
/* 引用块:左侧一条主色竖条 + 弱化底,点击跳回原消息 */
.message-bubble__quote {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  max-width: 100%;
  padding: var(--space-xs) var(--space-sm);
  border: none;
  border-left: 3px solid var(--color-brand);
  border-radius: var(--radius-chip);
  background: var(--color-divider);
  text-align: left;
  cursor: pointer;
}
.message-bubble__quote-name {
  font-size: var(--text-badge);
  color: var(--color-brand);
}
.message-bubble__quote-text {
  font-size: var(--text-badge);
  color: var(--color-text2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.message-bubble__body {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-md);
  border-radius: var(--radius-bubble);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-card);
  font-size: var(--text-body);
  line-height: var(--leading-body);
  word-break: break-word;
}
/* 自己的消息 = brand 实底白字:一屏只留这一个高音 */
.message-bubble--self .message-bubble__body {
  background: var(--gradient-heart);
  color: var(--color-bg-card);
}
/* 贴纸:不画气泡底色/阴影(贴纸自带描边与圆角),文字降级时用正文色 */
.message-bubble__body--sticker,
.message-bubble--self .message-bubble__body--sticker {
  padding: 0;
  background: none;
  box-shadow: none;
  color: var(--color-text1);
}
.message-bubble__sticker {
  width: 132px;
  height: 132px;
  border-radius: var(--radius-image);
  object-fit: contain;
}
/* 搜索定位命中:用外扩阴影做淡底,不改变布局(避免滚动位置跳动) */
.message-bubble--hit {
  border-radius: var(--radius-bubble);
  background: var(--tint-brand);
  box-shadow: 0 0 0 var(--space-sm) var(--tint-brand);
  transition:
    background 300ms var(--ease-out),
    box-shadow 300ms var(--ease-out);
}
.message-bubble__text {
  white-space: pre-wrap;
}
.message-bubble__image {
  max-width: 240px;
  max-height: 240px;
  border-radius: var(--radius-image);
  cursor: zoom-in;
}
.message-bubble__image {
  max-width: 240px;
  max-height: 240px;
  border-radius: var(--radius-image);
  cursor: zoom-in;
}
.message-bubble__retry {
  flex: none;
  border: none;
  border-radius: var(--radius-full);
  padding: 0 var(--space-sm);
  background: var(--color-danger);
  color: var(--color-bg-card);
  font-size: var(--text-badge);
  cursor: pointer;
}
/* 只有悬停/聚焦时才露出,平时不干扰阅读 */
.message-bubble__more {
  flex: none;
  align-self: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: var(--radius-full);
  background: none;
  color: var(--color-text3);
  opacity: 0;
  cursor: pointer;
  transition: opacity var(--motion-fast) var(--ease-out);
}
.message-bubble:hover .message-bubble__more,
.message-bubble__more:focus-visible {
  opacity: 1;
}
.message-bubble__pending {
  flex: none;
  font-size: var(--text-badge);
  opacity: 0.8;
}
/* 已读:与「发送中」同尺寸同位置,弱化处理(不抢内容的视线,不加动效) */
.message-bubble__read {
  flex: none;
  font-size: var(--text-badge);
  opacity: 0.8;
}
/* 系统灰条:居中、弱化,不抢视线 */
.message-bubble--notice {
  align-self: center;
  max-width: var(--bubble-max-ratio);
  margin: 0;
  padding: 2px var(--space-md);
  border-radius: var(--radius-full);
  background: var(--color-divider);
  color: var(--color-text2);
  font-size: var(--text-badge);
  text-align: center;
}
</style>
