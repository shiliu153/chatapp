<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import type { ChatMessage } from '@/im/types'

const props = defineProps<{ message: ChatMessage; localFile?: File | null }>()
defineEmits<{ open: [] }>()

const failed = ref(false)
/** 发送中先用本地预览(blob),发送成功后换成服务端 URL */
const objectUrl = ref<string | null>(null)

function revoke() {
  if (objectUrl.value) {
    URL.revokeObjectURL(objectUrl.value)
    objectUrl.value = null
  }
}

watch(
  () => [props.localFile, props.message.imageUrl, props.message.isPending] as const,
  () => {
    revoke()
    if (props.localFile && (props.message.isPending || !props.message.imageUrl)) {
      objectUrl.value = URL.createObjectURL(props.localFile)
    }
  },
  { immediate: true },
)

onUnmounted(revoke)

const src = computed(() => objectUrl.value ?? props.message.imageLargeUrl ?? props.message.imageUrl)
</script>

<template>
  <div class="message-image" :class="{ 'message-image--pending': props.message.isPending }">
    <img
      v-if="src && !failed"
      class="message-image__img"
      :src="src"
      alt="图片消息"
      @error="failed = true"
      @click="$emit('open')"
    />
    <span v-else-if="failed" class="message-image__fallback">图片加载失败</span>
    <span v-else class="message-image__placeholder" aria-hidden="true" />
  </div>
</template>

<style scoped>
.message-image {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 120px;
  min-height: 90px;
  border-radius: var(--radius-image);
  background: var(--color-divider);
  overflow: hidden;
}
.message-image__img {
  max-width: 240px;
  max-height: 240px;
  cursor: zoom-in;
}
.message-image__fallback {
  padding: var(--space-md);
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.message-image__placeholder {
  width: 120px;
  height: 90px;
  background: var(--color-divider);
  animation: message-image-breathe var(--motion-loop) var(--ease-out) infinite;
}
@keyframes message-image-breathe {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.55;
  }
}
</style>
