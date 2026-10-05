<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { parseApiError } from '@/api/error'
import * as moderationApi from '@/api/moderation'
import * as usersApi from '@/api/users'
import AppAvatar from '@/components/AppAvatar.vue'
import AppButton from '@/components/AppButton.vue'
import AppCard from '@/components/AppCard.vue'
import OnlineDot from '@/components/OnlineDot.vue'
import ReportDialog from '@/features/moderation/ReportDialog.vue'
import { usePresenceStore } from '@/stores/presence'
import type { PublicProfile, ReportType } from '@/api/types'

const props = defineProps<{ id: string }>()

const presence = usePresenceStore()
const numericId = computed(() => Number(props.id))
const isOnline = computed(() => presence.isOnline(numericId.value))

const profile = ref<PublicProfile | null>(null)
const error = ref('')
/** 404 = 对方已不可见(拉黑/重封禁),给「重试」没有意义 */
const fatal = ref(false)
const notice = ref('')
const reporting = ref(false)

async function load() {
  error.value = ''
  fatal.value = false
  try {
    profile.value = await usersApi.fetchUserProfile(Number(props.id))
    presence.track('profile', [Number(props.id)])
  } catch (e) {
    const apiError = parseApiError(e)
    error.value = apiError.message
    fatal.value = apiError.status === 404
  }
}

onMounted(load)

async function onReport(type: ReportType, detail: string) {
  reporting.value = false
  try {
    await moderationApi.reportUser(Number(props.id), type, detail)
    notice.value = '已收到举报,我们会尽快核实'
  } catch (e) {
    notice.value = parseApiError(e).message
  }
}

async function onBlock() {
  if (!window.confirm('拉黑后你们将互相看不到对方,确定吗?')) return
  notice.value = ''
  try {
    await moderationApi.blockUser(Number(props.id))
    notice.value = '已拉黑'
  } catch (e) {
    notice.value = parseApiError(e).message
  }
}
</script>

<template>
  <section class="user-profile">
    <AppCard v-if="profile" padding="lg">
      <div class="user-profile__head">
        <AppAvatar :src="profile.photos[0]?.url ?? null" :name="profile.nickname" :size="72" />
        <div>
          <h1 class="user-profile__name">{{ profile.nickname || '神秘人' }}</h1>
          <p class="user-profile__meta">
            {{ profile.age ? `${profile.age} 岁 · ` : '' }}{{ profile.city || '未填城市' }}
          </p>
        </div>
        <OnlineDot class="user-profile__online" :online="isOnline" />
      </div>
      <p v-if="profile.bio" class="user-profile__bio">{{ profile.bio }}</p>
      <div v-if="profile.tags.length" class="user-profile__tags">
        <span v-for="tag in profile.tags" :key="tag.id" class="user-profile__tag">
          {{ tag.name }}
        </span>
      </div>
      <div class="user-profile__photos">
        <img
          v-for="photo in profile.photos"
          :key="photo.id"
          :src="photo.url"
          alt=""
          class="user-profile__photo"
        />
      </div>
      <div class="user-profile__actions">
        <AppButton class="user-profile__report" variant="ghost" @click="reporting = true">
          举报
        </AppButton>
        <AppButton class="user-profile__block" variant="danger" @click="onBlock">拉黑</AppButton>
      </div>
      <p v-if="notice" class="user-profile__notice">{{ notice }}</p>
    </AppCard>

    <p v-else-if="error && fatal" class="user-profile__fatal">{{ error }}</p>

    <ReportDialog
      :open="reporting"
      target="user"
      @close="reporting = false"
      @submitted="onReport"
    />
  </section>
</template>

<style scoped>
.user-profile {
  width: clamp(520px, 52%, 720px);
  max-width: 100%;
  margin: 0 auto;
  padding: var(--space-section-gap) var(--space-page-h);
}
.user-profile__head {
  display: flex;
  align-items: center;
  gap: var(--space-lg);
}
.user-profile__online {
  margin-left: auto;
}
.user-profile__name {
  margin: 0;
  font-size: var(--text-title);
  font-weight: var(--weight-bold);
}
.user-profile__meta {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.user-profile__bio {
  margin: var(--space-md) 0 0;
  font-size: var(--text-body);
}
.user-profile__tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-sm);
  margin-top: var(--space-md);
}
.user-profile__tag {
  padding: 2px var(--space-md);
  border-radius: var(--radius-full);
  background: var(--color-bg-page);
  font-size: var(--text-caption);
}
.user-profile__photos {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-sm);
  margin-top: var(--space-lg);
}
.user-profile__photo {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  border-radius: var(--radius-image);
}
.user-profile__actions {
  display: flex;
  gap: var(--space-md);
  margin-top: var(--space-lg);
}
.user-profile__notice {
  margin: var(--space-md) 0 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.user-profile__fatal {
  margin: 0;
  text-align: center;
  color: var(--color-text2);
}
</style>
