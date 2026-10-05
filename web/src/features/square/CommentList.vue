<script setup lang="ts">
import { computed, ref } from 'vue'
import { parseApiError } from '@/api/error'
import AppAvatar from '@/components/AppAvatar.vue'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import * as feedApi from '@/api/feed'
import type { Comment } from '@/api/types'

const props = defineProps<{ postId: number; comments: Comment[]; count: number }>()
const emit = defineEmits<{ added: [Comment] }>()

const text = ref('')
const error = ref('')
const submitting = ref(false)
const offset = ref(props.comments.length)
const loadingMore = ref(false)

const hasMore = computed(() => props.comments.length < props.count)

async function onSubmit() {
  const value = text.value.trim()
  error.value = ''
  if (!value) {
    error.value = '评论不能为空'
    return
  }
  submitting.value = true
  try {
    const comment = await feedApi.createComment(props.postId, value)
    text.value = ''
    emit('added', comment)
  } catch (e) {
    error.value = parseApiError(e).message
  } finally {
    submitting.value = false
  }
}

async function loadMore() {
  loadingMore.value = true
  try {
    const page = await feedApi.fetchComments(props.postId, 20, offset.value)
    offset.value += page.results.length
    page.results.forEach((item) => emit('added', item))
  } finally {
    loadingMore.value = false
  }
}
</script>

<template>
  <section class="comment-list">
    <h2 class="comment-list__title">评论 {{ props.count }}</h2>

    <p v-if="props.comments.length === 0" class="comment-list__empty">还没有评论,来说两句</p>

    <ul class="comment-list__items">
      <li v-for="comment in props.comments" :key="comment.id" class="comment-list__item">
        <AppAvatar
          :src="comment.author.avatar_url"
          :name="comment.author.nickname"
          :size="32"
        />
        <div class="comment-list__body">
          <span class="comment-list__name">{{ comment.author.nickname || '神秘人' }}</span>
          <p class="comment-list__text">{{ comment.text }}</p>
        </div>
      </li>
    </ul>

    <AppButton
      v-if="hasMore"
      variant="ghost"
      block
      :loading="loadingMore"
      @click="loadMore"
    >
      加载更多评论
    </AppButton>

    <div class="comment-list__form">
      <AppInput
        v-model="text"
        placeholder="说点什么…"
        :maxlength="200"
        :error="error"
        @enter="onSubmit"
      />
      <AppButton class="comment-list__submit" :loading="submitting" @click="onSubmit">
        发送
      </AppButton>
    </div>
  </section>
</template>

<style scoped>
.comment-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}
.comment-list__title {
  margin: 0;
  font-size: var(--text-subtitle);
  font-weight: var(--weight-semibold);
}
.comment-list__empty {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.comment-list__items {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  margin: 0;
  padding: 0;
  list-style: none;
}
.comment-list__item {
  display: flex;
  gap: var(--space-sm);
}
.comment-list__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
}
.comment-list__name {
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.comment-list__text {
  margin: 0;
  font-size: var(--text-body);
}
.comment-list__form {
  display: flex;
  align-items: flex-start;
  gap: var(--space-sm);
}
.comment-list__form > :first-child {
  flex: 1;
}
.comment-list__submit {
  flex: none;
}
</style>
