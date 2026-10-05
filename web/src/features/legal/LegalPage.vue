<script setup lang="ts">
import { computed } from 'vue'
import { agreementText } from './agreement'
import { privacyText } from './privacy'

const props = defineProps<{ kind: 'agreement' | 'privacy' }>()

const title = computed(() => (props.kind === 'agreement' ? '用户协议' : '隐私政策'))
const body = computed(() => (props.kind === 'agreement' ? agreementText : privacyText))
</script>

<template>
  <main class="legal">
    <article class="legal__doc">
      <h1 class="legal__title">{{ title }}</h1>
      <pre class="legal__body">{{ body }}</pre>
    </article>
  </main>
</template>

<style scoped>
.legal {
  display: flex;
  justify-content: center;
  padding: var(--space-section-gap) var(--space-page-h);
}
.legal__doc {
  width: clamp(var(--form-card-min), 56%, 760px);
  max-width: 100%;
  padding: var(--space-xxl);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-card);
}
.legal__title {
  margin: 0 0 var(--space-lg);
  font-size: var(--text-title);
  font-weight: var(--weight-bold);
}
.legal__body {
  margin: 0;
  font-family: var(--font-latin);
  font-size: var(--text-caption);
  line-height: var(--leading-body);
  white-space: pre-wrap;
  color: var(--color-text1);
}
</style>
