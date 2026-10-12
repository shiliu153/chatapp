<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { parseApiError } from '@/api/error'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import FormCard from '@/features/auth/FormCard.vue'
import PhotoGrid from '@/features/profile/PhotoGrid.vue'
import TagPicker from '@/features/profile/TagPicker.vue'
import { useProfileStore } from '@/stores/profile'

const router = useRouter()
const store = useProfileStore()

const nickname = ref('')
const gender = ref<'' | 'male' | 'female'>('')
const birthday = ref('')
const city = ref('')
const bio = ref('')
const tagIds = ref<number[]>([])
const error = ref('')
const submitting = ref(false)

onMounted(async () => {
  if (!store.profile) await store.load()
  const p = store.profile
  if (!p) return
  nickname.value = p.nickname
  gender.value = p.gender
  birthday.value = p.birthday ?? ''
  city.value = p.city
  bio.value = p.bio
  tagIds.value = p.tags.map((t) => t.id)
})

async function onSubmit() {
  error.value = ''
  submitting.value = true
  try {
    await store.save({
      nickname: nickname.value,
      gender: gender.value || undefined,
      birthday: birthday.value || undefined,
      city: city.value,
      bio: bio.value,
      tag_ids: tagIds.value,
    })
    await router.push({ name: 'discovery' })
  } catch (e) {
    error.value = parseApiError(e).message
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <FormCard title="完善资料" description="填完这些就可以开始滑卡了">
    <AppInput
      v-model="nickname"
      placeholder="昵称"
      :maxlength="20"
      :error="error"
    />
    <div class="onboarding__gender">
      <button
        v-for="option in [
          { v: 'female', label: '女生' },
          { v: 'male', label: '男生' },
        ]"
        :key="option.v"
        type="button"
        class="onboarding__chip"
        :class="{ 'onboarding__chip--active': gender === option.v }"
        @click="gender = option.v as 'male' | 'female'"
      >
        {{ option.label }}
      </button>
    </div>
    <AppInput v-model="birthday" type="date" placeholder="生日" />
    <AppInput v-model="city" placeholder="城市" :maxlength="50" />
    <AppInput v-model="bio" placeholder="一句话介绍自己" :maxlength="200" />
    <TagPicker v-model="tagIds" />
    <PhotoGrid />
    <AppButton
      block
      size="lg"
      :loading="submitting"
      @click="onSubmit"
    >
      开始使用
    </AppButton>
  </FormCard>
</template>

<style scoped>
.onboarding__gender {
  display: flex;
  gap: var(--space-sm);
}
.onboarding__chip {
  flex: 1;
  height: 44px;
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-input);
  background: var(--color-bg-card);
  cursor: pointer;
  transition:
    border-color var(--motion-fast) var(--ease-out),
    color var(--motion-fast) var(--ease-out);
}
.onboarding__chip--active {
  border-color: var(--color-brand);
  color: var(--color-brand);
}
</style>
