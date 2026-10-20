<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { parseApiError } from '@/api/error'
import * as feedApi from '@/api/feed'
import AppCard from '@/components/AppCard.vue'
import AppErrorView from '@/components/AppErrorView.vue'
import type { Comment, Post } from '@/api/types'
import CommentList from './CommentList.vue'
import PostCard from './PostCard.vue'

const props = defineProps<{ id: string }>()

const post = ref<Post | null>(null)
const comments = ref<Comment[]>([])
const error = ref('')
/** 404 = 不可见,给「重试」没有意义 */
const fatal = ref(false)

async function load() {
  error.value = ''
  fatal.value = false
  try {
    const postId = Number(props.id)
    post.value = await feedApi.fetchPost(postId)
    const page = await feedApi.fetchComments(postId)
    comments.value = page.results
  } catch (e) {
    const apiError = parseApiError(e)
    error.value = apiError.message
    fatal.value = apiError.status === 404
  }
}

onMounted(load)

function onCommentAdded(comment: Comment) {
  comments.value = [comment, ...comments.value]
  if (post.value) post.value.comment_count += 1
}

function onCommentDeleted(comment: Comment) {
  if (comment.parent_id === null) {
    comments.value = comments.value.filter((item) => item.id !== comment.id)
  } else {
    comments.value = comments.value.map((item) =>
      item.id === comment.parent_id
        ? {
            ...item,
            replies: item.replies.filter((reply) => reply.id !== comment.id),
            reply_count: Math.max(0, item.reply_count - 1),
          }
        : item,
    )
  }
  if (post.value) {
    const removed = comment.parent_id === null ? 1 + comment.reply_count : 1
    post.value.comment_count = Math.max(0, post.value.comment_count - removed)
  }
}
</script>

<template>
  <section class="post-detail">
    <AppCard v-if="post" padding="lg">
      <PostCard :post="post" @like="feedApi.likePost(post.id)" />
    </AppCard>

    <p v-if="error && fatal" class="post-detail__fatal">{{ error }}</p>
    <AppErrorView v-else-if="error" :message="error" @retry="load" />

    <AppCard v-if="post" padding="lg">
      <CommentList
        :post-id="Number(props.id)"
        :comments="comments"
        :count="post.comment_count"
        @added="onCommentAdded"
        @deleted="onCommentDeleted"
      />
    </AppCard>
  </section>
</template>

<style scoped>
.post-detail {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  width: clamp(560px, 56%, 760px);
  max-width: 100%;
  margin: 0 auto;
  padding: var(--space-section-gap) var(--space-page-h);
}
.post-detail__fatal {
  margin: 0;
  font-size: var(--text-body);
  color: var(--color-text2);
  text-align: center;
}
</style>
