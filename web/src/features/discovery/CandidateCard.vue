<script setup lang="ts">
import { computed } from 'vue'
import type { Candidate } from '@/api/types'

const props = withDefaults(defineProps<{ candidate: Candidate; online?: boolean }>(), {
  online: false,
})

const photoUrl = computed(() => props.candidate.photos[0]?.url ?? null)
const tags = computed(() => props.candidate.tags.slice(0, 3))
const meta = computed(() =>
  [props.candidate.age ? `${props.candidate.age} 岁` : '', props.candidate.city]
    .filter(Boolean)
    .join(' · '),
)
</script>

<template>
  <article class="candidate-card">
    <img
      v-if="photoUrl"
      class="candidate-card__photo"
      :src="photoUrl"
      alt=""
    />
    <div v-else class="candidate-card__fallback">{{ props.candidate.nickname.charAt(0) || '♥' }}</div>

    <span v-if="props.online" class="candidate-card__online" aria-label="在线" />

    <div class="candidate-card__scrim">
      <h2 class="candidate-card__name">
        {{ props.candidate.nickname || '这个人很神秘' }}
      </h2>
      <p v-if="meta" class="candidate-card__meta">{{ meta }}</p>
      <p v-if="props.candidate.bio" class="candidate-card__bio">{{ props.candidate.bio }}</p>
      <div v-if="tags.length" class="candidate-card__tags">
        <span v-for="tag in tags" :key="tag.id" class="candidate-card__tag">{{ tag.name }}</span>
      </div>
    </div>
  </article>
</template>

<style scoped>
.candidate-card {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  border-radius: var(--radius-discovery-card);
  background: var(--color-divider);
}
.candidate-card__photo {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.candidate-card__fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  background: var(--gradient-heart);
  color: var(--color-bg-card);
  font-size: var(--text-emoji);
}
.candidate-card__online {
  position: absolute;
  top: var(--space-lg);
  right: var(--space-lg);
  width: 12px;
  height: 12px;
  border: 2px solid var(--color-bg-card);
  border-radius: var(--radius-full);
  background: var(--color-green);
  box-shadow: 0 0 0 4px var(--glow-online);
}
/* 照片叠字:透明 → photoScrim 的底部渐变(心跳附录 A.2) */
.candidate-card__scrim {
  position: absolute;
  inset: auto 0 0 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  padding: var(--space-xl) var(--space-lg) var(--space-lg);
  background: linear-gradient(to bottom, transparent, var(--color-photo-scrim));
  color: var(--color-bg-card);
}
.candidate-card__name {
  margin: 0;
  font-size: var(--text-title);
  font-weight: var(--weight-bold);
}
.candidate-card__meta {
  margin: 0;
  font-size: var(--text-caption);
  opacity: 0.9;
}
.candidate-card__bio {
  margin: 0;
  font-size: var(--text-caption);
  opacity: 0.85;
}
.candidate-card__tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-xs);
  margin-top: var(--space-xs);
}
.candidate-card__tag {
  padding: 2px var(--space-sm);
  border-radius: var(--radius-full);
  background: var(--overlay-on-photo);
  font-size: var(--text-badge);
}
</style>
