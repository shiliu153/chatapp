<script setup lang="ts">
import AppKickedOverlay from '@/components/AppKickedOverlay.vue'
import LegalGate from '@/features/legal/LegalGate.vue'
</script>

<template>
  <RouterView />
  <LegalGate />
  <AppKickedOverlay />
</template>
