<script setup lang="ts">
import { computed, ref } from 'vue'
import { parseApiError } from '@/api/error'
import { useProfileStore } from '@/stores/profile'

const props = withDefaults(defineProps<{ editable?: boolean }>(), { editable: true })

const MAX_COUNT = 6
const MAX_BYTES = 5 * 1024 * 1024

const STATUS_LABEL: Record<string, string> = {
  pending: '审核中',
  approved: '已通过',
  rejected: '已驳回',
}

const store = useProfileStore()
const hint = ref('')
const busy = ref(false)

const photos = computed(() => store.profile?.photos ?? [])
const canUpload = computed(() => props.editable && photos.value.length < MAX_COUNT)

async function onPick(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // 允许重复选择同一文件
  if (!file) return

  hint.value = ''
  // 前端拦截只是省一次往返;后端仍会校验,所以下面 catch 里要用后端文案
  if (file.size > MAX_BYTES) {
    hint.value = '单张照片不能超过 5MB'
    return
  }
  busy.value = true
  try {
    await store.uploadPhoto(file)
  } catch (e) {
    hint.value = parseApiError(e).message
  } finally {
    busy.value = false
  }
}

async function onRemove(id: number) {
  hint.value = ''
  try {
    await store.removePhoto(id)
  } catch (e) {
    hint.value = parseApiError(e).message
  }
}
</script>

<template>
  <div class="photo-grid">
    <figure v-for="photo in photos" :key="photo.id" class="photo-grid__item">
      <img :src="photo.url" alt="" class="photo-grid__img" />
      <figcaption class="photo-grid__badge" :class="`photo-grid__badge--${photo.status}`">
        {{ STATUS_LABEL[photo.status] }}
      </figcaption>
      <button
        v-if="props.editable"
        type="button"
        class="photo-grid__remove"
        aria-label="删除照片"
        @click="onRemove(photo.id)"
      >
        ×
      </button>
    </figure>

    <label v-if="canUpload" class="photo-grid__add">
      <input
        type="file"
        accept="image/*"
        class="photo-grid__input"
        @change="onPick"
      />
      <span>{{ busy ? '上传中…' : '+' }}</span>
    </label>

    <p v-if="props.editable && !canUpload" class="photo-grid__hint">最多 6 张</p>
    <p v-if="hint" class="photo-grid__hint photo-grid__hint--error">{{ hint }}</p>
  </div>
</template>

<style scoped>
.photo-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-md);
}
.photo-grid__item {
  position: relative;
  margin: 0;
  aspect-ratio: 3 / 4;
  border-radius: var(--radius-image);
  overflow: hidden;
  background: var(--color-divider);
}
.photo-grid__img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.photo-grid__badge {
  position: absolute;
  left: var(--space-xs);
  bottom: var(--space-xs);
  padding: 2px var(--space-sm);
  border-radius: var(--radius-full);
  font-size: var(--text-badge);
  color: var(--color-bg-card);
  background: var(--color-text2);
}
.photo-grid__badge--approved {
  background: var(--color-green);
}
.photo-grid__badge--rejected {
  background: var(--color-danger);
}
.photo-grid__badge--pending {
  background: var(--color-amber);
}
.photo-grid__remove {
  position: absolute;
  top: var(--space-xs);
  right: var(--space-xs);
  width: 24px;
  height: 24px;
  border: none;
  border-radius: var(--radius-full);
  background: var(--color-photo-scrim);
  color: var(--color-bg-card);
  cursor: pointer;
}
.photo-grid__add {
  display: flex;
  align-items: center;
  justify-content: center;
  aspect-ratio: 3 / 4;
  border: 1px dashed var(--color-text3);
  border-radius: var(--radius-image);
  color: var(--color-text3);
  font-size: var(--text-display);
  cursor: pointer;
}
.photo-grid__input {
  display: none;
}
.photo-grid__hint {
  grid-column: 1 / -1;
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.photo-grid__hint--error {
  color: var(--color-danger);
}
</style>
