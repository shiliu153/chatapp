<script setup lang="ts">
import { computed } from 'vue'
import AppAvatar from '@/components/AppAvatar.vue'
import MessageImage from './MessageImage.vue'
import MessageVoice from './MessageVoice.vue'
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
  }>(),
  { peerName: '', peerAvatar: null, localFile: null, hit: false },
)
defineEmits<{ retry: []; openImage: [ChatMessage]; menu: [MouseEvent] }>()

const isNotice = computed(
  () =>
    props.message.kind === ChatMessageKind.matchNotice ||
    props.message.kind === ChatMessageKind.banNotice,
)
const isImage = computed(() => props.message.kind === ChatMessageKind.image)
const isVoice = computed(() => props.message.kind === ChatMessageKind.voice)
const isUnsupported = computed(() => props.message.kind === ChatMessageKind.other)
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

    <div class="message-bubble__body">
      <MessageImage
        v-if="isImage"
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
