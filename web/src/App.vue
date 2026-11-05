<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import AppKickedOverlay from '@/components/AppKickedOverlay.vue'
import LegalGate from '@/features/legal/LegalGate.vue'
import { useThemeStore } from '@/stores/theme'

// 外观(F-3):挂载后按存储的模式生效,并跟随系统明暗变化。
// 首屏那次生效发生在 main.ts 的 applyStoredTheme()(避免闪白),这里只负责后续联动。
const theme = useThemeStore()
let query: MediaQueryList | null = null

function onSystemChange(): void {
  theme.refresh()
}

onMounted(() => {
  theme.refresh()
  if (typeof window.matchMedia !== 'function') return
  query = window.matchMedia('(prefers-color-scheme: dark)')
  query.addEventListener('change', onSystemChange)
})

onUnmounted(() => {
  query?.removeEventListener('change', onSystemChange)
})
</script>

<template>
  <RouterView />
  <LegalGate />
  <AppKickedOverlay />
</template>
