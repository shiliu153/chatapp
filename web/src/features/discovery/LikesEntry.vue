<script setup lang="ts">
import { onMounted } from 'vue'
import { useLikesStore } from '@/stores/likes'
import TopEntry from './TopEntry.vue'

const store = useLikesStore()

onMounted(() => {
  store.loadCount().catch(() => {})
})
</script>

<template>
  <TopEntry
    icon="♥"
    label="喜欢我的人"
    :to="{ name: 'likes' }"
    :count="store.count"
  />
</template>
