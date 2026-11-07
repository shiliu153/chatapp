<script setup lang="ts">
/**
 * 输入框下方的面板(批次 J):两个 tab —— **表情** 与 **贴纸**。
 *
 * - 表情:点选把 emoji 回给页面,由页面插进输入框(纯文本消息,零协议改动);
 * - 贴纸:点选**直接发送**(`kind=custom`,载荷 `{type:'sticker', id}`),
 *   资源是打包进 `public/stickers/` 的 PNG,消息里只传 id。
 *
 * 默认停在表情 tab:表情是高频操作,贴纸是「额外一步」。
 */
import { onMounted, onUnmounted, ref } from 'vue'
import { CHAT_STICKERS } from './stickers'

const emit = defineEmits<{ pick: [string]; sticker: [string]; close: [] }>()

/** 与 App 的表情面板保持同一组,不引第三方库 */
const EMOJIS = [
  '😀', '😄', '😁', '😊', '🥰', '😍', '😘', '😜',
  '🤔', '😅', '😂', '🥲', '😭', '😢', '😳', '😴',
  '👍', '👏', '🙏', '🤝', '💪', '🎉', '❤️', '💔',
  '🌹', '🍀', '☀️', '🌙', '🍜', '☕', '🎬', '🎵',
]

const tab = ref<'emoji' | 'sticker'>('emoji')

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="emoji-panel">
    <div class="emoji-panel__tabs">
      <button
        type="button"
        class="emoji-panel__tab"
        :class="{ 'emoji-panel__tab--active': tab === 'emoji' }"
        data-testid="panel-tab-emoji"
        @click="tab = 'emoji'"
      >
        表情
      </button>
      <button
        type="button"
        class="emoji-panel__tab"
        :class="{ 'emoji-panel__tab--active': tab === 'sticker' }"
        data-testid="panel-tab-sticker"
        @click="tab = 'sticker'"
      >
        贴纸
      </button>
    </div>

    <div v-if="tab === 'emoji'" class="emoji-panel__grid">
      <button
        v-for="emoji in EMOJIS"
        :key="emoji"
        type="button"
        class="emoji-panel__item"
        @click="emit('pick', emoji)"
      >
        {{ emoji }}
      </button>
    </div>

    <div v-else class="emoji-panel__stickers">
      <button
        v-for="sticker in CHAT_STICKERS"
        :key="sticker.id"
        type="button"
        class="emoji-panel__sticker"
        :title="sticker.label"
        :data-testid="`sticker-${sticker.id}`"
        @click="emit('sticker', sticker.id)"
      >
        <img class="emoji-panel__sticker-img" :src="sticker.src" :alt="sticker.label" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.emoji-panel {
  border-top: 1px solid var(--color-divider);
  background: var(--color-bg-card);
}
.emoji-panel__tabs {
  display: flex;
  border-bottom: 1px solid var(--color-divider);
}
.emoji-panel__tab {
  flex: 1;
  height: 36px;
  border: none;
  border-bottom: 2px solid transparent;
  background: none;
  color: var(--color-text2);
  font-size: var(--text-badge);
  cursor: pointer;
}
.emoji-panel__tab--active {
  border-bottom-color: var(--color-brand);
  color: var(--color-text1);
}
.emoji-panel__grid {
  display: grid;
  grid-template-columns: repeat(8, 1fr);
  gap: var(--space-xs);
  padding: var(--space-md);
}
.emoji-panel__item {
  height: 36px;
  border: none;
  border-radius: var(--radius-chip);
  background: none;
  font-size: var(--text-subtitle);
  cursor: pointer;
}
.emoji-panel__item:hover {
  background: var(--hover-overlay);
}
.emoji-panel__stickers {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-sm);
  padding: var(--space-md);
}
.emoji-panel__sticker {
  border: none;
  border-radius: var(--radius-image);
  background: none;
  padding: 2px;
  cursor: pointer;
}
.emoji-panel__sticker:hover {
  background: var(--hover-overlay);
}
.emoji-panel__sticker-img {
  width: 100%;
  aspect-ratio: 1;
  object-fit: contain;
}
</style>
