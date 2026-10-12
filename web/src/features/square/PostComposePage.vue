<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { parseApiError } from '@/api/error'
import AppButton from '@/components/AppButton.vue'
import FormCard from '@/features/auth/FormCard.vue'
import { useFeedStore } from '@/stores/feed'

const MAX_IMAGES = 9
const MAX_BYTES = 5 * 1024 * 1024

const router = useRouter()
const store = useFeedStore()

const text = ref('')
const images = ref<File[]>([])
const previews = ref<string[]>([])
const error = ref('')
const submitting = ref(false)

const canSubmit = computed(() => text.value.trim().length > 0 || images.value.length > 0)

function revokeAll() {
  previews.value.forEach((src) => URL.revokeObjectURL(src))
}

function refreshPreviews() {
  revokeAll()
  previews.value = images.value.map((file) => URL.createObjectURL(file))
}

function onPick(event: Event) {
  const input = event.target as HTMLInputElement
  const picked = Array.from(input.files ?? [])
  input.value = '' // 允许重复选同一张
  error.value = ''

  // 前端拦截只是省一次往返,后端仍会校验(feed.md),失败文案以后端为准
  if (picked.some((file) => file.size > MAX_BYTES)) {
    error.value = '单张图片不能超过 5MB'
    return
  }
  const next = [...images.value, ...picked]
  if (next.length > MAX_IMAGES) {
    error.value = '最多 9 张图片'
    return
  }
  images.value = next
  refreshPreviews()
}

function removeImage(index: number) {
  images.value = images.value.filter((_, i) => i !== index)
  refreshPreviews()
}

onUnmounted(revokeAll)

async function onSubmit() {
  error.value = ''
  if (!canSubmit.value) {
    error.value = '写点文字或选张图片吧'
    return
  }
  submitting.value = true
  try {
    await store.create(text.value.trim(), images.value)
    await router.push({ name: 'square' })
  } catch (e) {
    error.value = parseApiError(e).message
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <FormCard title="发动态" description="正文最多 500 字,图片最多 9 张">
    <textarea
      v-model="text"
      class="post-compose__text"
      placeholder="此刻在想什么?"
      maxlength="500"
      rows="5"
    />
    <div class="post-compose__images">
      <figure v-for="(src, i) in previews" :key="src" class="post-compose__item">
        <img :src="src" alt="" class="post-compose__img" />
        <button type="button" class="post-compose__remove" @click="removeImage(i)">×</button>
      </figure>
      <label v-if="images.length < MAX_IMAGES" class="post-compose__add">
        <input
          type="file"
          accept="image/*"
          multiple
          class="post-compose__input"
          @change="onPick"
        />
        <span>+</span>
      </label>
    </div>
    <p v-if="error" class="post-compose__error">{{ error }}</p>
    <AppButton
      class="post-compose__submit"
      block
      size="lg"
      :loading="submitting"
      @click="onSubmit"
    >
      发布
    </AppButton>
  </FormCard>
</template>

<style scoped>
.post-compose__text {
  width: 100%;
  padding: var(--space-md);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-input);
  font-family: var(--font-latin);
  font-size: var(--text-body);
  line-height: var(--leading-body);
  resize: vertical;
}
.post-compose__text:focus {
  border-color: var(--color-brand);
  outline: none;
}
.post-compose__images {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-sm);
}
.post-compose__item {
  position: relative;
  margin: 0;
  aspect-ratio: 1;
}
.post-compose__img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: var(--radius-image);
}
.post-compose__remove {
  position: absolute;
  top: var(--space-xs);
  right: var(--space-xs);
  width: 22px;
  height: 22px;
  border: none;
  border-radius: var(--radius-full);
  background: var(--color-photo-scrim);
  color: var(--color-bg-card);
  cursor: pointer;
}
.post-compose__add {
  display: flex;
  align-items: center;
  justify-content: center;
  aspect-ratio: 1;
  border: 1px dashed var(--color-text3);
  border-radius: var(--radius-image);
  color: var(--color-text3);
  font-size: var(--text-title);
  cursor: pointer;
}
.post-compose__input {
  display: none;
}
.post-compose__error {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-danger);
}
</style>
