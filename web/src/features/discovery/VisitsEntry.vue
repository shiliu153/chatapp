<script setup lang="ts">
import { onMounted } from 'vue'
import { useVisitsStore } from '@/stores/visits'
import TopEntry from './TopEntry.vue'

const store = useVisitsStore()

onMounted(() => {
  store.loadCount().catch(() => {})
})
</script>

<template>
  <TopEntry
    icon="👁"
    label="谁看过我"
    :to="{ name: 'visits' }"
    :count="store.count"
  />
</template>
