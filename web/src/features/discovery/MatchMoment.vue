<script setup lang="ts">
import { computed } from 'vue'
import type { Candidate, Tag } from '@/api/types'
import { matchIcebreaker } from './icebreaker'

const props = withDefaults(
  defineProps<{
    candidate: Candidate
    /** 配对那一刻的共同标签(滑卡响应直接带回) */
    sharedTags?: Tag[]
    /** 我的城市:与对方同城才会展示「你们都在 X」 */
    myCity?: string
  }>(),
  { sharedTags: () => [], myCity: '' },
)
defineEmits<{ close: []; chat: [] }>()

// 共同点只在「配对那一刻」说一句:有共同标签说标签,否则只在同城时说城市。
const icebreaker = computed(() =>
  matchIcebreaker({
    sharedTagNames: props.sharedTags.map((tag) => tag.name),
    myCity: props.myCity,
    peerCity: props.candidate.city,
  }),
)
</script>

<template>
  <div class="match-moment" role="dialog" aria-modal="true">
    <div class="match-moment__panel">
      <span class="match-moment__heart">♥</span>
      <h2 class="match-moment__title">你们互相喜欢</h2>
      <p class="match-moment__desc">和 {{ props.candidate.nickname || '对方' }} 打个招呼吧</p>
      <p v-if="icebreaker" class="match-moment__icebreaker">{{ icebreaker }}</p>
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
.match-moment__icebreaker {
  margin: 0;
  padding: var(--space-sm) var(--space-md);
  border-radius: var(--radius-input);
  background: var(--color-divider);
  font-size: var(--text-caption);
  color: var(--color-text1);
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
