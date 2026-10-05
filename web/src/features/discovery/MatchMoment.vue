<script setup lang="ts">
import type { Candidate } from '@/api/types'

const props = defineProps<{ candidate: Candidate }>()
defineEmits<{ close: []; chat: [] }>()
</script>

<template>
  <div class="match-moment" role="dialog" aria-modal="true">
    <div class="match-moment__panel">
      <span class="match-moment__heart">♥</span>
      <h2 class="match-moment__title">你们互相喜欢</h2>
      <p class="match-moment__desc">和 {{ props.candidate.nickname || '对方' }} 打个招呼吧</p>
      <RouterLink
        class="match-moment__chat"
        :to="{ name: 'chat', params: { peerId: `u${props.candidate.user_id}` } }"
      >
        去聊天
      </RouterLink>
      <button type="button" class="match-moment__close" @click="$emit('close')">继续滑</button>
    </div>
  </div>
</template>

<style scoped>
.match-moment {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gradient-heart);
}
.match-moment__panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-md);
  width: clamp(320px, 40%, var(--form-card-max));
  padding: var(--space-xxl);
  border-radius: var(--radius-sheet);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-floating-bar);
  text-align: center;
}
.match-moment__heart {
  font-size: var(--text-emoji);
  color: var(--color-brand);
}
.match-moment__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
}
.match-moment__desc {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.match-moment__chat {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 52px;
  border-radius: var(--radius-input);
  background: var(--gradient-heart);
  color: var(--color-bg-card);
  font-weight: var(--weight-semibold);
  box-shadow: var(--shadow-primary-button);
}
.match-moment__close {
  border: none;
  background: none;
  color: var(--color-text2);
  font-size: var(--text-caption);
  cursor: pointer;
}
</style>
