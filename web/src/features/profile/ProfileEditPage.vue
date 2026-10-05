<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { parseApiError } from '@/api/error'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import FormCard from '@/features/auth/FormCard.vue'
import PhotoGrid from './PhotoGrid.vue'
import TagPicker from './TagPicker.vue'
import { useProfileStore } from '@/stores/profile'

const store = useProfileStore()

const nickname = ref('')
const gender = ref<'' | 'male' | 'female'>('')
const birthday = ref('')
const city = ref('')
const bio = ref('')
const tagIds = ref<number[]>([])
const error = ref('')
const saved = ref(false)
const submitting = ref(false)

onMounted(async () => {
  if (!store.profile) await store.load()
  nickname.value = store.profile?.nickname ?? ''
  gender.value = store.profile?.gender ?? ''
  birthday.value = store.profile?.birthday ?? ''
  city.value = store.profile?.city ?? ''
  bio.value = store.profile?.bio ?? ''
  tagIds.value = store.profile?.tags.map((t) => t.id) ?? []
})

async function onSubmit() {
  error.value = ''
  saved.value = false
  submitting.value = true
  try {
    await store.save({
      nickname: nickname.value,
      gender: gender.value || undefined,
      birthday: birthday.value || undefined,
      city: city.value,
      bio: bio.value,
      // 空数组 = 清空标签,不能用 undefined —— 否则后端不替换(users.md §2.2)
      tag_ids: tagIds.value,
    })
    saved.value = true
  } catch (e) {
    // 未满 18 岁等校验一律用后端文案,不在前端自己编(users.md §2.2)
    error.value = parseApiError(e).message
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <FormCard title="编辑资料" description="资料越完整,越容易被喜欢">
    <div class="profile-edit__form">
      <AppInput
        v-model="nickname"
        placeholder="昵称(最多 20 字)"
        :maxlength="20"
        :error="error"
      />
      <div class="profile-edit__gender">
        <button
          v-for="option in [
            { v: 'female', label: '女生' },
            { v: 'male', label: '男生' },
          ]"
          :key="option.v"
          type="button"
          class="profile-edit__chip"
          :class="{ 'profile-edit__chip--active': gender === option.v }"
          @click="gender = option.v as 'male' | 'female'"
        >
          {{ option.label }}
        </button>
      </div>
      <AppInput v-model="birthday" type="date" placeholder="生日" />
      <AppInput v-model="city" placeholder="城市" :maxlength="50" />
      <AppInput v-model="bio" placeholder="一句话介绍自己(最多 200 字)" :maxlength="200" />
      <TagPicker v-model="tagIds" />
      <PhotoGrid />
    </div>
    <p v-if="saved" class="profile-edit__saved">已保存</p>
    <AppButton
      class="profile-edit__submit"
      block
      size="lg"
      :loading="submitting"
      @click="onSubmit"
    >
      保存
    </AppButton>
  </FormCard>
</template>

<style scoped>
.profile-edit__form {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}
.profile-edit__gender {
  display: flex;
  gap: var(--space-sm);
}
.profile-edit__chip {
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
.profile-edit__chip--active {
  border-color: var(--color-brand);
  color: var(--color-brand);
}
.profile-edit__saved {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-green);
}
</style>
