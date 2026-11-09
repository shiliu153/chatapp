import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as discoveryApi from '@/api/discovery'
import { parseApiError } from '@/api/error'
import type { Candidate, MatchSummary, SwipeQuota, Tag } from '@/api/types'

const MATCHES_PAGE_SIZE = 20

/**
 * 撤销窗口(discovery.md §3.9):从客户端拿到滑卡响应起 **30 秒**。
 * 客户端自己计时,不依赖服务端返回过期时刻 —— 超过窗口按钮置灰,别再打接口。
 */
export const UNDO_WINDOW_MS = 30_000

/** 倒计时/解封的刷新间隔。1 秒够用:环按整秒走,文案也是秒。 */
const TICK_MS = 1000

/** 额度用尽的提示(验收口径固定文案;`42904` 的 `message` 以后端为准,这里只兜底体验)。 */
export const QUOTA_EXHAUSTED_TEXT = '今日喜欢次数已用完,明天再来'

/** 没有可撤销的滑卡(`400` + `40003`)时的提示,同时收起撤销按钮。 */
export const UNDO_UNAVAILABLE_TEXT = '没有可撤销的操作'

/**
 * 禁用到什么时候:优先用后端 `Retry-After`(额度超限给的是「到次日 0 点」),
 * 没有就自己算到次日 0 点 —— 上海没有夏令时,固定 +8 直接取日界,不引第三方时区库。
 */
function retryDelayMs(retryAfterSeconds?: number): number {
  if (retryAfterSeconds !== undefined) return retryAfterSeconds * 1000
  const dayMs = 86_400_000
  const shanghaiOffsetMs = 8 * 60 * 60 * 1000
  return dayMs - ((Date.now() + shanghaiOffsetMs) % dayMs)
}

/** 「最近一次滑卡」:撤销成功后按它把卡放回卡堆顶部。 */
interface PendingUndo {
  candidate: Candidate
  action: 'like' | 'pass'
}

export const useDiscoveryStore = defineStore('discovery', () => {
  const candidates = ref<Candidate[]>([])
  const index = ref(0)
  const matched = ref<Candidate | null>(null)
  /** 配对那一刻的共同标签:只给破冰文案用,关掉配对动效即清空 */
  const matchedSharedTags = ref<Tag[]>([])
  const matches = ref<MatchSummary[]>([])
  const matchesCount = ref(0)
  /** 配对列表的下一页游标:null = 没有下一页 */
  const matchesCursor = ref<string | null>(null)
  /** 配对列表至少成功拉过一次:聊天页据此判断「不在列表里 = 已被解除」 */
  const matchesLoaded = ref(false)
  const loading = ref(false)
  const submitting = ref(false)
  const error = ref('')

  /** 每日喜欢额度(discovery.md §3.10);`null` = 还不知道或拿不到,页面不显示 */
  const quota = ref<SwipeQuota | null>(null)
  /** 最近一次滑卡;`null` = 没有可撤销的操作(没划过 / 已撤销 / 已配对) */
  const pendingUndo = ref<PendingUndo | null>(null)
  /** 撤销窗口的截止时刻(epoch ms);`null` = 撤销按钮不显示 */
  const undoDeadline = ref<number | null>(null)
  const undoing = ref(false)
  /** 额度用尽后「喜欢」按钮禁用到什么时候(epoch ms);`null` = 没被封 */
  const likeBlockedUntil = ref<number | null>(null)
  /** 本地时钟:倒计时与解封都从它派生,由 `syncTicker()` 按秒推进 */
  const now = ref(Date.now())

  const current = computed<Candidate | null>(() => candidates.value[index.value] ?? null)
  const exhausted = computed(() => !loading.value && current.value === null)

  /** 额度条只在 `like_limit > 0`(额度开启)时显示;`0` = 不限,整块不显示 */
  const quotaVisible = computed(() => (quota.value?.like_limit ?? 0) > 0)
  const likesRemaining = computed<number | null>(() => quota.value?.likes_remaining ?? null)
  /** 额度文案:「今日还可喜欢 N 次」 */
  const quotaText = computed(() =>
    likesRemaining.value === null ? '' : `今日还可喜欢 ${likesRemaining.value} 次`,
  )

  /** 撤销按钮是否显示:划过一次且未配对(过期也留在原地,置灰) */
  const undoVisible = computed(() => undoDeadline.value !== null)
  const undoSecondsLeft = computed(() => {
    if (undoDeadline.value === null) return 0
    return Math.max(0, Math.ceil((undoDeadline.value - now.value) / 1000))
  })
  const canUndo = computed(() => undoDeadline.value !== null && undoSecondsLeft.value > 0)
  /** 倒计时环的进度:1 = 满 30 秒,0 = 已过期 */
  const undoProgress = computed(() => {
    if (undoDeadline.value === null) return 0
    return Math.min(1, Math.max(0, (undoDeadline.value - now.value) / UNDO_WINDOW_MS))
  })

  /** 「喜欢」是否已被额度挡住:本地剩余为 0,或收到 `42904` 后还在 `Retry-After` 里 */
  const likeBlocked = computed(() => {
    if (likeBlockedUntil.value !== null && now.value < likeBlockedUntil.value) return true
    return likesRemaining.value === 0
  })

  let ticker: ReturnType<typeof setInterval> | undefined

  /** 只在还有倒计时/封禁时开定时器,跑完就关,不留后台轮询。 */
  function syncTicker(): void {
    const pending =
      (undoDeadline.value !== null && now.value < undoDeadline.value) ||
      (likeBlockedUntil.value !== null && now.value < likeBlockedUntil.value)
    if (pending && !ticker) {
      ticker = setInterval(onTick, TICK_MS)
    } else if (!pending && ticker) {
      clearInterval(ticker)
      ticker = undefined
    }
  }

  /** 秒级推进本地时钟;封禁到期时顺手对账一次额度(次日 0 点会重置)。 */
  function onTick(): void {
    now.value = Date.now()
    if (likeBlockedUntil.value !== null && now.value >= likeBlockedUntil.value) {
      likeBlockedUntil.value = null
      void loadQuota()
    }
    syncTicker()
  }

  /** 记下可撤销的那一次滑卡并开 30 秒窗口;配对成功不挂窗口(§3.9 一律拒绝撤销)。 */
  function rememberUndo(
    candidate: Candidate,
    action: 'like' | 'pass',
    matchedNow: boolean,
  ): void {
    if (matchedNow) {
      clearUndo()
      return
    }
    pendingUndo.value = { candidate, action }
    undoDeadline.value = Date.now() + UNDO_WINDOW_MS
    now.value = Date.now()
    syncTicker()
  }

  /** 收起撤销入口(撤销成功 / 被拒 / 重新拉候选)。 */
  function clearUndo(): void {
    pendingUndo.value = null
    undoDeadline.value = null
    now.value = Date.now()
    syncTicker()
  }

  /** 本地递减一次喜欢额度(成功 like 后调用,不额外打接口)。 */
  function spendOneLike(): void {
    const q = quota.value
    if (!q || q.like_limit <= 0 || q.likes_remaining === null) return
    quota.value = {
      ...q,
      likes_used: q.likes_used + 1,
      likes_remaining: Math.max(q.likes_remaining - 1, 0),
    }
  }

  /** 撤销一次喜欢,把额度退回一次(§3.9「撤销意味着那次操作没有发生」)。 */
  function refundOneLike(): void {
    const q = quota.value
    if (!q || q.like_limit <= 0 || q.likes_remaining === null) return
    quota.value = {
      ...q,
      likes_used: Math.max(q.likes_used - 1, 0),
      likes_remaining: Math.min(q.likes_remaining + 1, q.like_limit),
    }
  }

  /** 把撤销掉的卡放回卡堆顶部(即 `index` 指向的那一格之前)。 */
  function restoreCard(userId: number, fallback: Candidate | null): void {
    const pos = candidates.value.findIndex((item) => item.user_id === userId)
    if (pos === index.value - 1) {
      // 常规路径:那张卡还在数组里,指针退一格就回到它
      index.value = Math.max(index.value - 1, 0)
      return
    }
    const card = pos >= 0 ? candidates.value[pos] : fallback
    if (!card) return
    const rest = candidates.value.filter((item) => item.user_id !== userId)
    const at = Math.min(index.value, rest.length)
    candidates.value = [...rest.slice(0, at), card, ...rest.slice(at)]
    // 卡堆比指针短时(换批次刷过)要把指针一起拉回来,否则 current 会指到数组外
    index.value = at
  }

  /** 额度对账:拿不到就当不知道(不显示、不挡滑卡),绝不因为提示接口出错卡住用户。 */
  async function loadQuota(): Promise<void> {
    try {
      quota.value = await discoveryApi.fetchQuota()
    } catch {
      quota.value = null
    }
    now.value = Date.now()
    syncTicker()
  }

  async function loadCandidates(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      candidates.value = await discoveryApi.fetchCandidates()
      index.value = 0
      // 新一批候选 = 旧的撤销目标已经不在卡堆里,收起撤销入口
      clearUndo()
    } catch (e) {
      error.value = parseApiError(e).message
    } finally {
      loading.value = false
    }
  }

  async function decide(action: 'like' | 'pass'): Promise<void> {
    const target = current.value
    if (!target || submitting.value) return
    submitting.value = true
    error.value = ''
    try {
      const result = await discoveryApi.swipe(target.user_id, action)
      index.value += 1
      rememberUndo(target, action, result.matched)
      if (action === 'like') spendOneLike()
      if (result.matched) {
        matched.value = target
        matchedSharedTags.value = result.shared_tags
      }
    } catch (e) {
      const apiError = parseApiError(e)
      if (apiError.status === 404) {
        // 目标不存在/已不可见:跳过这张卡,不打扰用户(discovery.md §3.2)
        index.value += 1
      } else if (apiError.code === 42904) {
        // 今日喜欢额度用完(discovery.md §3.2 / §3.10):停住这张卡,按 Retry-After 禁「喜欢」
        likeBlockedUntil.value = Date.now() + retryDelayMs(apiError.retryAfter)
        now.value = Date.now()
        syncTicker()
        if (quota.value) quota.value = { ...quota.value, likes_remaining: 0 }
        error.value = QUOTA_EXHAUSTED_TEXT
      } else {
        // 403 轻封禁 / 429 限流:停住当前卡并展示后端文案
        error.value = apiError.message
      }
    } finally {
      submitting.value = false
    }
  }

  /**
   * 撤销最近一次滑卡。成功返回 `true`(调用方提示「已撤销」),失败返回 `false`
   * 并把提示写进 `error`;`400` + `40003` 一律收起撤销入口,不重试。
   */
  async function undo(): Promise<boolean> {
    if (!canUndo.value || undoing.value) return false
    const entry = pendingUndo.value
    undoing.value = true
    error.value = ''
    try {
      const result = await discoveryApi.undoSwipe()
      clearUndo()
      restoreCard(result.target_user_id, entry?.candidate ?? null)
      if (entry?.action === 'like') refundOneLike()
      return true
    } catch (e) {
      const apiError = parseApiError(e)
      if (apiError.status === 400) {
        // 40003:没有可撤销的滑卡(无记录 / 超过 30 秒 / 已配对)——按钮没意义了
        clearUndo()
        error.value = UNDO_UNAVAILABLE_TEXT
      } else {
        // 403 轻封禁 / 429 限流:按钮留着,让用户按提示稍后再试
        error.value = apiError.message
      }
      return false
    } finally {
      undoing.value = false
    }
  }

  function dismissMatched(): void {
    matched.value = null
    matchedSharedTags.value = []
  }

  /** 配对列表;`reset` 用于下拉首刷,否则顺着 next_cursor 追加。 */
  async function loadMatches(reset = false): Promise<void> {
    if (reset) {
      matches.value = []
      matchesCursor.value = null
    }
    const page = await discoveryApi.fetchMatches(MATCHES_PAGE_SIZE, matchesCursor.value)
    matches.value = [...matches.value, ...page.results]
    matchesCount.value = page.count
    matchesCursor.value = page.next_cursor
    matchesLoaded.value = true
  }

  /** 解除配对:后端软删除 + 双向拉黑;本地立刻从配对列表移除。 */
  async function unmatch(userId: number): Promise<void> {
    await discoveryApi.unmatch(userId)
    matches.value = matches.value.filter((item) => item.user_id !== userId)
    matchesCount.value = Math.max(matchesCount.value - 1, 0)
  }

  return {
    candidates,
    index,
    matched,
    matchedSharedTags,
    matches,
    matchesCount,
    matchesLoaded,
    loading,
    submitting,
    error,
    quota,
    undoing,
    current,
    exhausted,
    quotaVisible,
    likesRemaining,
    quotaText,
    undoVisible,
    undoSecondsLeft,
    canUndo,
    undoProgress,
    likeBlocked,
    loadQuota,
    loadCandidates,
    decide,
    undo,
    dismissMatched,
    loadMatches,
    unmatch,
  }
})
