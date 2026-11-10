<script setup lang="ts">
import { computed } from 'vue'
import { useDiscoveryStore } from '@/stores/discovery'
import type { Candidate } from '@/api/types'

/**
 * 「今日精选」区块(批次 S,discovery.md §3.11)。
 *
 * 横向排列的 6 张迷你卡,点一张进对方资料页。数据来自 store 里已经拉好的
 * `daily`(**包装对象** `{date, candidates}`);为空 / 拉取失败就整块不渲染 ——
 * 它是滑卡主流程之上的加餐,不该抢注意力,也不该把滑卡挡住。
 */
const store = useDiscoveryStore()

const cards = computed<Candidate[]>(() => store.dailyCandidates)

function photoOf(candidate: Candidate): string | null {
  return candidate.photos[0]?.url ?? null
}

/** 「昵称,年龄」;没年龄就只显示昵称(与 App 的精选卡文案一致) */
function titleOf(candidate: Candidate): string {
  return candidate.age === null ? candidate.nickname : `${candidate.nickname},${candidate.age}`
}
</script>

<template>
  <section v-if="cards.length" class="daily-strip">
    <h2 class="daily-strip__title">
      <span class="daily-strip__icon" aria-hidden="true">✦</span>
      今日精选
    </h2>
    <ul class="daily-strip__list">
      <li v-for="card in cards" :key="card.user_id" class="daily-strip__item">
        <RouterLink
          class="daily-strip__card"
          :to="{ name: 'user-profile', params: { id: card.user_id } }"
          :aria-label="`${titleOf(card)},今日精选`"
        >
          <img
            v-if="photoOf(card)"
            class="daily-strip__photo"
            :src="photoOf(card) ?? ''"
            alt=""
          />
          <span v-else class="daily-strip__fallback">{{ card.nickname.charAt(0) || '♥' }}</span>
          <span class="daily-strip__scrim">
            <span class="daily-strip__name">{{ titleOf(card) }}</span>
            <span v-if="card.city" class="daily-strip__meta">{{ card.city }}</span>
          </span>
        </RouterLink>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.daily-strip {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}
.daily-strip__title {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  margin: 0;
  font-size: var(--text-subtitle);
  font-weight: var(--weight-semibold);
  color: var(--color-text1);
}
.daily-strip__icon {
  color: var(--color-brand);
  font-size: var(--text-caption);
  line-height: 1;
}
.daily-strip__list {
  display: flex;
  gap: var(--space-sm);
  margin: 0;
  padding: 0 0 var(--space-xs);
  overflow-x: auto;
  list-style: none;
}
.daily-strip__item {
  flex: none;
}
.daily-strip__card {
  position: relative;
  display: block;
  width: 112px;
  height: 156px;
  overflow: hidden;
  border-radius: var(--radius-card);
  background: var(--color-divider);
  box-shadow: var(--shadow-card);
  transition: transform var(--motion-base) var(--ease-out);
}
.daily-strip__card:hover {
  transform: translateY(-2px);
}
.daily-strip__photo {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.daily-strip__fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  background: var(--gradient-heart);
  color: var(--color-bg-card);
  font-size: var(--text-display);
}
.daily-strip__scrim {
  position: absolute;
  inset: auto 0 0 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-xl) var(--space-sm) var(--space-sm);
  background: linear-gradient(to bottom, transparent, var(--color-photo-scrim));
  color: var(--color-bg-card);
}
.daily-strip__name {
  overflow: hidden;
  font-size: var(--text-caption);
  font-weight: var(--weight-semibold);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.daily-strip__meta {
  overflow: hidden;
  font-size: var(--text-badge);
  opacity: 0.9;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
