<script setup lang="ts">
import { onMounted } from 'vue'
import AppAvatar from '@/components/AppAvatar.vue'
import AppButton from '@/components/AppButton.vue'
import AppCard from '@/components/AppCard.vue'
import PhotoGrid from './PhotoGrid.vue'
import { useProfileStore } from '@/stores/profile'

const store = useProfileStore()

onMounted(() => {
  if (!store.profile) store.load().catch(() => {})
})
</script>

<template>
  <section class="my-profile">
    <AppCard padding="lg">
      <div class="my-profile__head">
        <AppAvatar
          :src="store.profile?.photos[0]?.url ?? null"
          :name="store.profile?.nickname"
          :size="64"
        />
        <div class="my-profile__meta">
          <h1 class="my-profile__name">{{ store.profile?.nickname || '未设置昵称' }}</h1>
          <p class="my-profile__sub">
            {{ store.profile?.age ?? '—' }} 岁 · {{ store.profile?.city || '未填城市' }}
          </p>
        </div>
      </div>
      <p v-if="store.profile?.bio" class="my-profile__bio">{{ store.profile.bio }}</p>

      <div v-if="store.isIncomplete" class="my-profile__complete">
        <span>还差:{{ store.missingFieldsText }}</span>
        <RouterLink :to="{ name: 'onboarding' }">
          <AppButton size="md">去完善</AppButton>
        </RouterLink>
      </div>
    </AppCard>

    <AppCard padding="lg">
      <h2 class="my-profile__section">我的照片</h2>
      <PhotoGrid :editable="false" />
    </AppCard>

    <div class="my-profile__links">
      <RouterLink :to="{ name: 'profile-edit' }">
        <AppButton variant="ghost" block>编辑资料</AppButton>
      </RouterLink>
      <RouterLink :to="{ name: 'preference' }">
        <AppButton variant="ghost" block>想找的人</AppButton>
      </RouterLink>
      <RouterLink :to="{ name: 'settings' }">
        <AppButton variant="ghost" block>设置</AppButton>
      </RouterLink>
    </div>
  </section>
</template>

<style scoped>
.my-profile {
  display: flex;
  flex-direction: column;
  gap: var(--space-card-gap);
  width: clamp(560px, 56%, 760px);
  max-width: 100%;
  margin: 0 auto;
  padding: var(--space-section-gap) var(--space-page-h);
}
.my-profile__head {
  display: flex;
  align-items: center;
  gap: var(--space-lg);
}
.my-profile__meta {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
}
.my-profile__name {
  margin: 0;
  font-size: var(--text-title);
  font-weight: var(--weight-bold);
}
.my-profile__sub {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.my-profile__bio {
  margin: var(--space-md) 0 0;
  font-size: var(--text-body);
}
.my-profile__complete {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
  margin-top: var(--space-lg);
  padding: var(--space-md);
  border-radius: var(--radius-chip);
  background: var(--tint-brand);
  color: var(--color-brand);
  font-size: var(--text-caption);
}
.my-profile__section {
  margin: 0 0 var(--space-md);
  font-size: var(--text-subtitle);
  font-weight: var(--weight-semibold);
}
.my-profile__links {
  display: flex;
  gap: var(--space-md);
}
</style>
