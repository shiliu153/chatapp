<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { parseApiError } from '@/api/error'
import * as moderationApi from '@/api/moderation'
import * as usersApi from '@/api/users'
import AppAvatar from '@/components/AppAvatar.vue'
import AppButton from '@/components/AppButton.vue'
import AppCard from '@/components/AppCard.vue'
import OnlineDot from '@/components/OnlineDot.vue'
import MessageVoice from '@/features/chat/MessageVoice.vue'
import ReportDialog from '@/features/moderation/ReportDialog.vue'
import { useFollowingFeedStore } from '@/stores/feed'
import { usePresenceStore } from '@/stores/presence'
import type { PublicProfile, ReportType } from '@/api/types'
import { PROFILE_VOICE_MAX_SECONDS } from './voiceIntro'

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

/** 关注态本地副本:乐观更新用(请求失败再回滚),以服务端响应为初始值 */
const following = ref(false)
const followerCount = ref(0)
const followBusy = ref(false)

async function load() {
  error.value = ''
  fatal.value = false
  try {
    profile.value = await usersApi.fetchUserProfile(Number(props.id))
    following.value = profile.value.is_followed
    followerCount.value = profile.value.follower_count
    presence.track('profile', [Number(props.id)])
  } catch (e) {
    const apiError = parseApiError(e)
    error.value = apiError.message
    fatal.value = apiError.status === 404
  }
}

onMounted(load)

/**
 * 关注/取消关注:乐观更新(点下去立刻切态与改粉丝数),失败回滚并提示。
 * 关注是低风险动作,等网络往返再变灰会让整页像卡住。
 */
async function onToggleFollow() {
  if (followBusy.value) return
  const target = !following.value
  following.value = target
  followerCount.value += target ? 1 : -1
  followBusy.value = true
  notice.value = ''
  try {
    if (target) await usersApi.followUser(numericId.value)
    else await usersApi.unfollowUser(numericId.value)
    // 关注关系变了 → 广场「关注」tab 的列表必须失效,否则切回去还是旧列表
    // (1.0.9 记录的已知限制,批次 J 顺手补掉)
    useFollowingFeedStore().load(true).catch(() => {})
  } catch (e) {
    following.value = !target
    followerCount.value += target ? -1 : 1
    notice.value = parseApiError(e).message
  } finally {
    followBusy.value = false
  }
}

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
      <div class="user-profile__follow">
        <span class="user-profile__count">
          <b>{{ profile.following_count }}</b> 关注
        </span>
        <span class="user-profile__count">
          <b>{{ followerCount }}</b> 粉丝
        </span>
        <AppButton
          class="user-profile__follow-button"
          :variant="following ? 'ghost' : 'primary'"
          :loading="followBusy"
          @click="onToggleFollow"
        >
          {{ following ? '已关注' : '关注' }}
        </AppButton>
      </div>
      <p v-if="profile.bio" class="user-profile__bio">{{ profile.bio }}</p>
      <div v-if="profile.tags.length" class="user-profile__tags">
        <span v-for="tag in profile.tags" :key="tag.id" class="user-profile__tag">
          {{ tag.name }}
        </span>
      </div>
      <!-- 语音自我介绍是公开的;没录过(voice == null)时整块不渲染,不留空占位 -->
      <div v-if="profile.voice" class="user-profile__voice">
        <span class="user-profile__voice-label">语音自我介绍</span>
        <MessageVoice
          :url="profile.voice.url"
          :duration-ms="profile.voice.duration_ms"
          :max-seconds="PROFILE_VOICE_MAX_SECONDS"
        />
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
.user-profile__follow {
  display: flex;
  align-items: center;
  gap: var(--space-lg);
  margin-top: var(--space-md);
}
.user-profile__count {
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.user-profile__count b {
  font-size: var(--text-body);
  color: var(--color-text1);
}
.user-profile__follow-button {
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
.user-profile__voice {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  margin-top: var(--space-md);
  padding: var(--space-md) var(--space-lg);
  border-radius: var(--radius-input);
  background: var(--color-bg-page);
}
.user-profile__voice-label {
  font-size: var(--text-caption);
  color: var(--color-text2);
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
