<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { APP_ICP, APP_NAME, APP_VERSION } from './appInfo'
</script>

<template>
  <section class="about">
    <header class="about__header">
      <RouterLink class="about__back" :to="{ name: 'settings' }">← 返回</RouterLink>
      <h1 class="about__title">关于</h1>
    </header>

    <div class="about__brand">
      <span class="about__mark" aria-hidden="true">♥</span>
      <span class="about__name">{{ APP_NAME }}</span>
      <span class="about__version">版本 {{ APP_VERSION }}</span>
    </div>

    <ul class="about__links">
      <li>
        <RouterLink class="about__agreement" :to="{ name: 'legal-agreement' }">用户协议</RouterLink>
      </li>
      <li>
        <RouterLink class="about__privacy" :to="{ name: 'legal-privacy' }">隐私政策</RouterLink>
      </li>
    </ul>

    <p v-if="APP_ICP" class="about__icp">{{ APP_ICP }}</p>
    <p class="about__copyright">© 2026 {{ APP_NAME }}</p>
  </section>
</template>

<style scoped>
.about {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  max-width: var(--form-card-max);
  margin: 0 auto;
  padding: var(--space-xl) var(--space-section-gap);
}
.about__header {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}
.about__back {
  align-self: flex-start;
  color: var(--color-text2);
  font-size: var(--text-caption);
  text-decoration: none;
}
.about__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
}
.about__brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-xl) 0;
}
.about__mark {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 72px;
  height: 72px;
  border-radius: var(--radius-sheet);
  background: var(--gradient-heart);
  color: var(--color-bg-card);
  font-size: 32px;
}
.about__name {
  color: var(--color-text1);
  font-size: var(--text-title);
  font-weight: var(--weight-bold);
}
.about__version {
  color: var(--color-text3);
  font-size: var(--text-caption);
}
.about__links {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-card);
}
.about__links li {
  border-bottom: 1px solid var(--color-divider);
}
.about__links li:last-child {
  border-bottom: none;
}
.about__agreement,
.about__privacy {
  display: flex;
  align-items: center;
  height: 48px;
  padding: 0 var(--space-lg);
  color: var(--color-text1);
  text-decoration: none;
}
.about__icp,
.about__copyright {
  margin: 0;
  color: var(--color-text3);
  font-size: var(--text-micro);
  text-align: center;
}
</style>
