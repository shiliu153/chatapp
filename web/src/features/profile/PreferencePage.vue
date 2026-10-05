<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { parseApiError } from '@/api/error'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import FormCard from '@/features/auth/FormCard.vue'
import { useProfileStore } from '@/stores/profile'
import type { Gender } from '@/api/types'

const store = useProfileStore()

const targetGender = ref<Gender | null>(null)
const ageMin = ref(18)
const ageMax = ref(99)
const city = ref('')
const error = ref('')
const saved = ref(false)

onMounted(async () => {
  if (!store.profile) await store.load()
  const pref = store.profile?.preference
  if (!pref) return
  targetGender.value = pref.target_gender
  ageMin.value = pref.age_min
  ageMax.value = pref.age_max
  city.value = pref.city
})

async function onSubmit() {
  error.value = ''
  saved.value = false
  try {
    await store.savePreference({
      target_gender: targetGender.value, // null = 不限(users.md §2.7)
      age_min: Number(ageMin.value),
      age_max: Number(ageMax.value),
      city: city.value,
    })
    saved.value = true
  } catch (e) {
    error.value = parseApiError(e).message
  }
}
</script>

<template>
  <FormCard title="想找的人" description="偏好只影响推荐,随时可以改">
    <div class="preference__gender">
      <button
        v-for="option in [
          { v: null, label: '不限' },
          { v: 'female', label: '女生' },
          { v: 'male', label: '男生' },
        ]"
        :key="String(option.v)"
        type="button"
        class="preference__chip"
        :class="{ 'preference__chip--active': targetGender === option.v }"
        @click="targetGender = option.v as Gender | null"
      >
        {{ option.label }}
      </button>
    </div>

    <div class="preference__ages">
      <AppInput
        :model-value="String(ageMin)"
        type="number"
        placeholder="最小年龄"
        @update:model-value="ageMin = Number($event)"
      />
      <span class="preference__dash">—</span>
      <AppInput
        :model-value="String(ageMax)"
        type="number"
        placeholder="最大年龄"
        @update:model-value="ageMax = Number($event)"
      />
    </div>

    <AppInput v-model="city" placeholder="想找的城市(留空=不限)" :maxlength="50" />
    <p v-if="error" class="preference__error">{{ error }}</p>
    <p v-if="saved" class="preference__saved">已保存</p>
    <AppButton
      class="preference__submit"
      block
      size="lg"
      @click="onSubmit"
    >
      保存
    </AppButton>
  </FormCard>
</template>

<style scoped>
.preference__gender {
  display: flex;
  gap: var(--space-sm);
}
.preference__chip {
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
.preference__chip--active {
  border-color: var(--color-brand);
  color: var(--color-brand);
}
.preference__ages {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}
.preference__dash {
  color: var(--color-text3);
}
.preference__error {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-danger);
}
.preference__saved {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-green);
}
</style>
