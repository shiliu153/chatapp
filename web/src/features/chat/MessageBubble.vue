<script setup lang="ts">
import { computed } from 'vue'
import AppAvatar from '@/components/AppAvatar.vue'
import { ChatMessageKind } from '@/im/types'
import type { ChatMessage } from '@/im/types'

const props = withDefaults(
  defineProps<{ message: ChatMessage; peerName?: string; peerAvatar?: string | null }>(),
  { peerName: '', peerAvatar: null },
)
defineEmits<{ retry: []; openImage: [ChatMessage] }>()

const isNotice = computed(
  () =>
    props.message.kind === ChatMessageKind.matchNotice ||
    props.message.kind === ChatMessageKind.banNotice,
)
const isImage = computed(() => props.message.kind === ChatMessageKind.image)
const isUnsupported = computed(() => props.message.kind === ChatMessageKind.other)
</script>

<template>
  <!-- 系统灰条:居中 pill,不属于任何一方 -->
  <p v-if="isNotice" class="message-bubble message-bubble--notice">{{ props.message.text }}</p>

  <div
    v-else
    class="message-bubble"
    :class="props.message.isSelf ? 'message-bubble--self' : 'message-bubble--peer'"
  >
    <AppAvatar
      v-if="!props.message.isSelf"
      :src="props.peerAvatar"
      :name="props.peerName"
      :size="36"
    />

    <div class="message-bubble__body">
      <img
        v-if="isImage && props.message.imageUrl"
        class="message-bubble__image"
        :src="props.message.imageUrl"
        alt="图片消息"
        @click="$emit('openImage', props.message)"
      />
      <span v-else-if="isImage" class="message-bubble__text">[图片]</span>
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
.message-bubble__text {
  white-space: pre-wrap;
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
