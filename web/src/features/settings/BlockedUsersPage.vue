<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppAvatar from '@/components/AppAvatar.vue'
import AppButton from '@/components/AppButton.vue'
import AppEmpty from '@/components/AppEmpty.vue'
import { parseApiError } from '@/api/error'
import { useBlocksStore } from '@/stores/blocks'

const store = useBlocksStore()
const error = ref('')
const busyId = ref<number | null>(null)
const loading = ref(true)

const hasMore = computed(() => store.blocks.length < store.count)

onMounted(async () => {
  try {
    await store.load(true)
  } catch (e) {
    error.value = parseApiError(e).message
  } finally {
    loading.value = false
  }
})

async function onUnblock(userId: number) {
  error.value = ''
  busyId.value = userId
  try {
    await store.unblock(userId)
  } catch (e) {
    error.value = parseApiError(e).message
  } finally {
    busyId.value = null
  }
}

async function loadMore() {
  try {
    await store.load()
  } catch (e) {
    error.value = parseApiError(e).message
  }
}
</script>

<template>
  <section class="blocks">
    <h1 class="blocks__title">黑名单</h1>
    <p class="blocks__desc">被拉黑的人看不到你,也不能给你发消息</p>
    <p v-if="error" class="blocks__error">{{ error }}</p>

    <AppEmpty
      v-if="!loading && store.blocks.length === 0"
      emoji="🚫"
      title="黑名单是空的"
      description="在对方资料页可以拉黑"
    />

    <ul v-else class="blocks__list">
      <li v-for="item in store.blocks" :key="item.user_id" class="blocks__item">
        <AppAvatar :src="item.avatar_url" :name="item.nickname" :size="40" />
        <span class="blocks__name">{{ item.nickname || `用户${item.user_id}` }}</span>
        <AppButton
          class="blocks__unblock"
          variant="ghost"
          :loading="busyId === item.user_id"
          @click="onUnblock(item.user_id)"
        >
          解除
        </AppButton>
      </li>
    </ul>

    <div v-if="hasMore" class="blocks__footer">
      <AppButton
        class="blocks__more"
        variant="ghost"
        block
        @click="loadMore"
      >
        加载更多
      </AppButton>
    </div>
  </section>
</template>

<style scoped>
.blocks {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  width: clamp(480px, 48%, 640px);
  max-width: 100%;
  margin: 0 auto;
  padding: var(--space-section-gap) var(--space-page-h);
}
.blocks__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
}
.blocks__desc {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.blocks__error {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-danger);
}
.blocks__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  margin: 0;
  padding: 0;
  list-style: none;
}
.blocks__item {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-md);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-card);
}
.blocks__name {
  flex: 1;
  font-size: var(--text-body);
  font-weight: var(--weight-semibold);
}
.blocks__unblock {
  flex: none;
}
.blocks__footer {
  display: flex;
  justify-content: center;
}
</style>
