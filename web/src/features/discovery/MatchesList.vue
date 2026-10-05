<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppAvatar from '@/components/AppAvatar.vue'
import { useDiscoveryStore } from '@/stores/discovery'

const store = useDiscoveryStore()
const busy = ref(false)

const hasMore = computed(() => store.matches.length < store.matchesCount)

onMounted(() => {
  store.loadMatches().catch(() => {})
})

async function loadMore() {
  busy.value = true
  try {
    await store.loadMatches()
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section v-if="store.matches.length" class="matches-list">
    <h2 class="matches-list__title">我的配对 · {{ store.matchesCount }}</h2>
    <div class="matches-list__row">
      <!-- peerId 用 im_user_id(u9 形式),与 App 的会话主键一致 -->
      <RouterLink
        v-for="match in store.matches"
        :key="match.user_id"
        class="matches-list__item"
        :to="{ name: 'chat', params: { peerId: match.im_user_id } }"
      >
        <AppAvatar :src="match.avatar_url" :name="match.nickname" :size="48" />
        <span class="matches-list__name">{{ match.nickname || '神秘人' }}</span>
      </RouterLink>
      <button
        v-if="hasMore"
        type="button"
        class="matches-list__more"
        :disabled="busy"
        @click="loadMore"
      >
        加载更多
      </button>
    </div>
  </section>
</template>

<style scoped>
.matches-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}
.matches-list__title {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.matches-list__row {
  display: flex;
  gap: var(--space-md);
  overflow-x: auto;
  padding-bottom: var(--space-xs);
}
.matches-list__item {
  display: flex;
  flex: none;
  flex-direction: column;
  align-items: center;
  gap: var(--space-xs);
  width: 64px;
}
.matches-list__name {
  max-width: 64px;
  overflow: hidden;
  font-size: var(--text-badge);
  color: var(--color-text2);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.matches-list__more {
  flex: none;
  align-self: center;
  height: 32px;
  padding: 0 var(--space-md);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  font-size: var(--text-caption);
  cursor: pointer;
}
</style>
