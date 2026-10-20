<script setup lang="ts">
import { computed, ref } from 'vue'
import { parseApiError } from '@/api/error'
import AppAvatar from '@/components/AppAvatar.vue'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import * as feedApi from '@/api/feed'
import type { Comment } from '@/api/types'
import { useSessionStore } from '@/stores/session'

const props = defineProps<{ postId: number; comments: Comment[]; count: number }>()
const emit = defineEmits<{ added: [Comment]; deleted: [Comment] }>()

const session = useSessionStore()
const text = ref('')
const error = ref('')
const submitting = ref(false)
const offset = ref(props.comments.length)
const loadingMore = ref(false)
const replyTo = ref<Comment | null>(null)
const expanded = ref<Record<number, Comment[]>>({})
const expanding = ref<number | null>(null)

const hasMore = computed(() => props.comments.length < props.count)

function isMine(comment: Comment): boolean {
  return session.userId === comment.author.user_id
}

function startReply(comment: Comment) {
  replyTo.value = comment
}

function cancelReply() {
  replyTo.value = null
}

async function onSubmit() {
  const value = text.value.trim()
  error.value = ''
  if (!value) {
    error.value = '评论不能为空'
    return
  }
  submitting.value = true
  try {
    const comment = await feedApi.createComment(props.postId, value, replyTo.value?.id)
    text.value = ''
    replyTo.value = null
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

async function expandReplies(comment: Comment) {
  expanding.value = comment.id
  try {
    const page = await feedApi.fetchReplies(props.postId, comment.id)
    expanded.value = { ...expanded.value, [comment.id]: page.results }
  } catch (e) {
    error.value = parseApiError(e).message
  } finally {
    expanding.value = null
  }
}

function repliesOf(comment: Comment): Comment[] {
  return expanded.value[comment.id] ?? comment.replies
}

function showMore(comment: Comment): boolean {
  return comment.reply_count > repliesOf(comment).length
}

async function onDelete(comment: Comment) {
  const extra = comment.reply_count > 0 ? `连同 ${comment.reply_count} 条回复一起删除,` : ''
  if (!window.confirm(`${extra}删除后不可恢复。确定删除这条评论?`)) return
  try {
    await feedApi.deleteComment(props.postId, comment.id)
    if (comment.parent_id !== null && expanded.value[comment.parent_id]) {
      expanded.value = {
        ...expanded.value,
        [comment.parent_id]: expanded.value[comment.parent_id].filter(
          (item) => item.id !== comment.id,
        ),
      }
    }
    emit('deleted', comment)
  } catch (e) {
    error.value = parseApiError(e).message
  }
}
</script>

<template>
  <section class="comment-list">
    <h2 class="comment-list__title">评论 {{ props.count }}</h2>

    <p v-if="props.comments.length === 0" class="comment-list__empty">还没有评论,来说两句</p>

    <ul class="comment-list__items">
      <li v-for="comment in props.comments" :key="comment.id" class="comment-list__item">
        <AppAvatar :src="comment.author.avatar_url" :name="comment.author.nickname" :size="32" />
        <div class="comment-list__body">
          <span class="comment-list__name">{{ comment.author.nickname || '神秘人' }}</span>
          <p class="comment-list__text">{{ comment.text }}</p>
          <div class="comment-list__actions">
            <button type="button" class="comment-list__reply" @click="startReply(comment)">
              回复
            </button>
            <button
              v-if="isMine(comment)"
              type="button"
              class="comment-list__delete"
              @click="onDelete(comment)"
            >
              删除
            </button>
          </div>

          <ul v-if="repliesOf(comment).length" class="comment-list__replies">
            <li v-for="reply in repliesOf(comment)" :key="reply.id" class="comment-list__reply-item">
              <AppAvatar :src="reply.author.avatar_url" :name="reply.author.nickname" :size="24" />
              <div class="comment-list__body">
                <span class="comment-list__name">{{ reply.author.nickname || '神秘人' }}</span>
                <p class="comment-list__text">
                  <span v-if="reply.reply_to" class="comment-list__at">
                    回复 @{{ reply.reply_to.nickname }}
                  </span>
                  {{ reply.text }}
                </p>
                <div class="comment-list__actions">
                  <button type="button" class="comment-list__reply" @click="startReply(reply)">
                    回复
                  </button>
                  <button
                    v-if="isMine(reply)"
                    type="button"
                    class="comment-list__delete"
                    @click="onDelete(reply)"
                  >
                    删除
                  </button>
                </div>
              </div>
            </li>
          </ul>

          <button
            v-if="showMore(comment)"
            type="button"
            class="comment-list__more"
            :disabled="expanding === comment.id"
            @click="expandReplies(comment)"
          >
            查看全部 {{ comment.reply_count }} 条回复
          </button>
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
      <div v-if="replyTo" class="comment-list__reply-hint">
        <span>回复 @{{ replyTo.author.nickname || '神秘人' }}</span>
        <button type="button" aria-label="取消回复" @click="cancelReply">×</button>
      </div>
      <div class="comment-list__form-row">
        <AppInput
          v-model="text"
          :placeholder="replyTo ? `回复 @${replyTo.author.nickname || '神秘人'}…` : '说点什么…'"
          :maxlength="200"
          :error="error"
          @enter="onSubmit"
        />
        <AppButton class="comment-list__submit" :loading="submitting" @click="onSubmit">
          发送
        </AppButton>
      </div>
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
  min-width: 0;
}
.comment-list__name {
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.comment-list__text {
  margin: 0;
  font-size: var(--text-body);
}
.comment-list__at {
  color: var(--color-text3);
}
.comment-list__actions {
  display: flex;
  gap: var(--space-md);
}
.comment-list__actions button,
.comment-list__more {
  padding: 0;
  border: none;
  background: none;
  font-size: var(--text-caption);
  color: var(--color-text2);
  cursor: pointer;
}
.comment-list__more {
  align-self: flex-start;
}
.comment-list__replies {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  margin: var(--space-xs) 0 0;
  padding: 0;
  list-style: none;
}
.comment-list__reply-item {
  display: flex;
  gap: var(--space-xs);
}
.comment-list__form {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
}
.comment-list__form-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-sm);
}
.comment-list__form-row > :first-child {
  flex: 1;
}
.comment-list__submit {
  flex: none;
}
.comment-list__reply-hint {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.comment-list__reply-hint button {
  border: none;
  background: none;
  font-size: var(--text-body);
  color: var(--color-text3);
  cursor: pointer;
}
</style>
