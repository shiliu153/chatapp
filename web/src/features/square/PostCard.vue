<script setup lang="ts">
import { computed } from 'vue'
import AppAvatar from '@/components/AppAvatar.vue'
import type { Post } from '@/api/types'

const props = withDefaults(defineProps<{ post: Post; mine?: boolean }>(), { mine: false })
const emit = defineEmits<{ like: []; delete: []; report: [] }>()

const imagesClass = computed(() => {
  const n = props.post.images.length
  if (n === 1) return 'post-card__images--1'
  if (n === 2) return 'post-card__images--2'
  return 'post-card__images--many'
})

/** 列表里只显示到分钟,避免每张卡都像秒表 */
const createdAtText = computed(() => {
  const date = new Date(props.post.created_at)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
})
</script>

<template>
  <article class="post-card">
    <header class="post-card__head">
      <RouterLink
        class="post-card__author"
        :to="{ name: 'user-profile', params: { id: props.post.author.user_id } }"
      >
        <AppAvatar
          :src="props.post.author.avatar_url"
          :name="props.post.author.nickname"
          :size="36"
        />
        <span class="post-card__name">{{ props.post.author.nickname || '神秘人' }}</span>
      </RouterLink>
      <button
        v-if="props.mine"
        type="button"
        class="post-card__delete"
        @click="emit('delete')"
      >
        删除
      </button>
    </header>

    <RouterLink
      class="post-card__body"
      :to="{ name: 'post-detail', params: { id: props.post.id } }"
    >
      <p v-if="props.post.text" class="post-card__text">{{ props.post.text }}</p>
      <div v-if="props.post.images.length" class="post-card__images" :class="imagesClass">
        <img
          v-for="(url, i) in props.post.images"
          :key="i"
          :src="url"
          alt=""
          class="post-card__image"
        />
      </div>
    </RouterLink>

    <footer class="post-card__foot">
      <button
        type="button"
        class="post-card__like"
        :class="{ 'post-card__like--active': props.post.liked_by_me }"
        @click="emit('like')"
      >
        ♥ {{ props.post.like_count }}
      </button>
      <RouterLink
        class="post-card__comment"
        :to="{ name: 'post-detail', params: { id: props.post.id } }"
      >
        💬 {{ props.post.comment_count }}
      </RouterLink>
      <span class="post-card__time">{{ createdAtText }}</span>
      <button type="button" class="post-card__report" @click="emit('report')">举报</button>
    </footer>
  </article>
</template>

<style scoped>
.post-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  padding: var(--space-lg);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-card);
  transition: box-shadow var(--motion-base) var(--ease-out);
}
.post-card:hover {
  box-shadow: var(--shadow-floating-bar);
}
.post-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.post-card__author {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}
.post-card__name {
  font-weight: var(--weight-semibold);
}
.post-card__delete,
.post-card__report {
  border: none;
  background: none;
  color: var(--color-text2);
  font-size: var(--text-caption);
  cursor: pointer;
}
.post-card__delete:hover {
  color: var(--color-danger);
}
.post-card__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}
.post-card__text {
  margin: 0;
  font-size: var(--text-body);
  white-space: pre-wrap;
}
.post-card__images {
  display: grid;
  gap: var(--space-xs);
}
.post-card__images--1 {
  grid-template-columns: 1fr;
}
.post-card__images--2 {
  grid-template-columns: 1fr 1fr;
}
.post-card__images--many {
  grid-template-columns: repeat(3, 1fr);
}
.post-card__image {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  border-radius: var(--radius-image);
}
.post-card__images--1 .post-card__image {
  aspect-ratio: 4 / 3;
}
.post-card__foot {
  display: flex;
  align-items: center;
  gap: var(--space-lg);
  font-size: var(--text-caption);
}
.post-card__like,
.post-card__comment {
  border: none;
  background: none;
  color: var(--color-text2);
  cursor: pointer;
  transition: color var(--motion-fast) var(--ease-out);
}
.post-card__like--active {
  color: var(--color-brand);
}
.post-card__time {
  margin-left: auto;
  color: var(--color-text3);
}
</style>
