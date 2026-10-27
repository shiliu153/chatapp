<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppAvatar from '@/components/AppAvatar.vue'
import AppEmpty from '@/components/AppEmpty.vue'
import AppErrorView from '@/components/AppErrorView.vue'
import AppSkeleton from '@/components/AppSkeleton.vue'
import { useChatStore } from '@/stores/chat'
import type { ImSearchHit } from '@/im/types'

const router = useRouter()
const store = useChatStore()

const keyword = ref('')
const hits = ref<ImSearchHit[]>([])
const loading = ref(false)
const hasMore = ref(false)
const error = ref('')
const searched = ref(false)

let debounceTimer: ReturnType<typeof setTimeout> | undefined
let requestSeq = 0

watch(keyword, (value) => {
  clearTimeout(debounceTimer)
  const trimmed = value.trim()
  if (!trimmed) {
    hits.value = []
    error.value = ''
    hasMore.value = false
    loading.value = false
    searched.value = false
    return
  }
  debounceTimer = setTimeout(() => run(trimmed), 300)
})

onUnmounted(() => clearTimeout(debounceTimer))

async function run(kw: string, append = false): Promise<void> {
  const seq = ++requestSeq
  loading.value = true
  error.value = ''
  searched.value = true
  try {
    const result = await store.searchMessages(
      kw,
      20,
      append && hits.value.length ? hits.value[hits.value.length - 1].msgId : undefined,
    )
    if (seq !== requestSeq) return // 丢弃过期响应
    hits.value = append ? [...hits.value, ...result.items] : result.items
    hasMore.value = result.hasMore
  } catch (e) {
    if (seq !== requestSeq) return
    error.value = e instanceof Error ? e.message : '搜索失败'
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

function loadMore(): void {
  if (!loading.value && hasMore.value) void run(keyword.value.trim(), true)
}

function open(hit: ImSearchHit): void {
  void router.push({
    name: 'chat',
    params: { peerId: hit.peerId },
    query: { focus: hit.msgId },
  })
}

/** HTML 转义(防 XSS)。 */
function escapeHtml(text: string): string {
  return text
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

/** 片段高亮:文本与关键词都先转义 HTML,关键词再转义正则元字符,最后包 <mark>。 */
function highlight(text: string): string {
  const kw = keyword.value.trim()
  const escaped = escapeHtml(text)
  if (!kw) return escaped
  const safeKw = escapeHtml(kw).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return escaped.replace(new RegExp(safeKw, 'gi'), (m) => `<mark>${m}</mark>`)
}

function timeOf(timestamp: number): string {
  const date = new Date(timestamp)
  const now = new Date()
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  if (sameDay) {
    return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
  }
  return `${date.getMonth() + 1}-${date.getDate()}`
}
</script>

<template>
  <section class="search">
    <header class="search__head">
      <RouterLink class="search__back" :to="{ name: 'chats' }">← 返回</RouterLink>
      <input
        v-model="keyword"
        class="search__input"
        data-testid="search-input"
        type="search"
        placeholder="搜索聊天记录"
        aria-label="搜索聊天记录"
        autofocus
      />
    </header>

    <div v-if="loading && hits.length === 0" class="search__loading">
      <AppSkeleton height="48px" />
      <AppSkeleton height="48px" />
      <AppSkeleton height="48px" />
    </div>

    <AppErrorView
      v-else-if="error && hits.length === 0"
      :message="error"
      @retry="run(keyword.trim())"
    />

    <AppEmpty
      v-else-if="searched && hits.length === 0"
      emoji="🫧"
      title="没有找到相关消息"
      description="换个关键词试试"
    />

    <template v-else-if="hits.length">
      <ul class="search__list">
        <li v-for="hit in hits" :key="hit.msgId">
          <button
            type="button"
            class="search__hit"
            :data-msg-id="hit.msgId"
            @click="open(hit)"
          >
            <AppAvatar :src="hit.peerAvatar" :name="hit.peerName || hit.peerId" :size="44" />
            <span class="search__main">
              <span class="search__name">{{ hit.peerName || hit.peerId }}</span>
              <!-- eslint-disable-next-line vue/no-v-html -- 内容已先转义,只包 <mark> -->
              <span class="search__snippet" v-html="highlight(hit.text)" />
            </span>
            <span class="search__time">{{ timeOf(hit.timestamp) }}</span>
          </button>
        </li>
      </ul>
      <button
        v-if="hasMore"
        type="button"
        class="search__more"
        :disabled="loading"
        @click="loadMore"
      >
        加载更多
      </button>
    </template>

    <AppEmpty
      v-else
      emoji="🔍"
      title="搜索聊天记录"
      description="输入关键词,找回你们聊过的内容"
    />
  </section>
</template>

<style scoped>
.search {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  height: 100vh;
  min-height: 0;
  padding: var(--space-lg) var(--space-section-gap);
}
.search__head {
  display: flex;
  align-items: center;
  gap: var(--space-md);
}
.search__back {
  font-size: var(--text-title);
  color: var(--color-text2);
}
.search__input {
  flex: 1;
  height: 40px;
  padding: 0 var(--space-md);
  border: none;
  border-radius: var(--radius-input);
  background: var(--color-bg-page);
  color: var(--color-text1);
  font-size: var(--text-body);
  outline: none;
}
.search__loading {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}
.search__list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  margin: 0;
  padding: 0;
  list-style: none;
}
.search__hit {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  width: 100%;
  padding: var(--space-md);
  border: none;
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  text-align: left;
  cursor: pointer;
  transition: background var(--motion-fast) var(--ease-out);
}
.search__hit:hover {
  background: var(--hover-overlay);
}
.search__main {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: var(--space-xs);
}
.search__name {
  overflow: hidden;
  font-size: var(--text-body);
  font-weight: var(--weight-semibold);
  color: var(--color-text1);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.search__snippet {
  overflow: hidden;
  font-size: var(--text-caption);
  color: var(--color-text2);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.search__snippet :deep(mark) {
  background: transparent;
  color: var(--color-brand);
  font-weight: var(--weight-semibold);
}
.search__time {
  flex: none;
  font-size: var(--text-badge);
  color: var(--color-text3);
}
.search__more {
  align-self: center;
  border: none;
  background: none;
  color: var(--color-brand);
  font-size: var(--text-body);
  font-weight: var(--weight-semibold);
  cursor: pointer;
  padding: var(--space-sm) var(--space-md);
}
.search__more:disabled {
  color: var(--color-text3);
  cursor: default;
}
</style>
