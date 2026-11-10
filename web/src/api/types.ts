/** 与后端接口一一对应的出入参类型;字段以 docs/api/ 为准,不臆造。 */

import type { components } from './schema'

export interface LoginResult {
  access: string
  isNewUser: boolean
  userId: number
}

export type Gender = 'male' | 'female'
export type ProfileStatus = 'incomplete' | 'complete' | 'banned_light' | 'banned_heavy'
export type PhotoStatus = 'pending' | 'approved' | 'rejected'

export interface Tag {
  id: number
  name: string
  icon: string
}

export interface Photo {
  id: number
  url: string
  status: PhotoStatus
  order: number
}

/**
 * 资料语音自我介绍(users.md §2.1 / §2.6)。
 *
 * 直接引用**生成类型**(`npm run gen:api` 的产物),不手写一份同样形状的结构:
 * 后端改字段时前端要么跟着改、要么编译期就红,不会出现「两处声明各说各话」。
 *
 * 语义提醒:`url` 是 **m4a 公开绝对地址**(与照片同口径:不签名、不过期),原样交给播放器,
 * **不要拼 `API_BASE`**;`duration_ms` 是服务端 ffprobe 实测(≤30000),客户端不声明。
 */
export type ProfileVoice = components['schemas']['ProfileVoice']

export interface Preference {
  /** null = 不限 */
  target_gender: Gender | null
  age_min: number
  age_max: number
  /** 空字符串 = 不限 */
  city: string
}

export interface Profile {
  /** 资料表主键(不是账号 ID,跨接口引用用户一律用 user_id) */
  id: number
  user_id: number
  phone: string
  nickname: string
  gender: Gender | ''
  /** YYYY-MM-DD */
  birthday: string | null
  age: number | null
  city: string
  bio: string
  status: ProfileStatus
  ban_reason: string
  /** nickname / gender / birthday / city / bio / photos */
  missing_fields: string[]
  tags: Tag[]
  photos: Photo[]
  preference: Preference
  /** 隐身浏览:开启后自己的访问不写进他人访客列表 */
  visits_hidden: boolean
  /** 语音自我介绍;没录过为 null(users.md §2.1,上传/删除见 §2.6) */
  voice: ProfileVoice | null
}

export interface PublicProfile {
  user_id: number
  nickname: string
  gender: Gender | ''
  age: number | null
  city: string
  bio: string
  tags: Tag[]
  /** 与当前用户的标签交集(users.md §2.8);无交集为空数组 */
  shared_tags: Tag[]
  photos: Photo[]
  /** 对方的语音自我介绍;**公开**(能看资料的人都能听),没录过为 null(users.md §2.8) */
  voice: ProfileVoice | null
  /** 当前用户是否已关注对方(批次 I;关注接口见 feed.md §5.13/§5.14) */
  is_followed: boolean
  /** 对方的粉丝数(多少人关注了对方) */
  follower_count: number
  /** 对方的关注数(对方关注了多少人) */
  following_count: number
}

/** offset 分页信封(评论、回复、拉黑名单等旧接口,conventions.md) */
export interface Page<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

/**
 * 游标分页信封(动态流 / 配对 / 喜欢我的人 / 访客)。
 *
 * 这几类列表头部会持续插入新行,offset 翻页会重复/漏读,后端已改成复合游标
 * (backlog D-1):请求带 `?before=`,响应给 `next_cursor`。游标是不透明字符串,
 * 客户端只负责原样回传,不要解析。
 */
export interface CursorPage<T> {
  count: number
  next_cursor: string | null
  has_more: boolean
  results: T[]
}

export interface Candidate {
  user_id: number
  nickname: string
  gender: Gender | ''
  age: number | null
  city: string
  bio: string
  tags: Tag[]
  /** 只含已过审(discovery.md §3.1) */
  photos: Photo[]
}

/**
 * 发现页的**临时筛选**(discovery.md §3.1「请求参数」,批次 S)。
 *
 * 语义是**覆盖**而不是替换:字段缺省 = 该字段没改过,后端继续沿用「想找的人」偏好
 * (设置页仍是偏好的唯一持久化入口)。所以「只填城市」的对象里不能出现
 * `age_min` / `age_max` —— 否则年龄区间会被钉死成面板里的默认值。
 */
export interface DiscoveryFilters {
  /** 年龄下限(含),`18`–`99`;缺省沿用偏好 */
  age_min?: number
  /** 年龄上限(含),`18`–`99`;缺省沿用偏好 */
  age_max?: number
  /** 只看这个城市;缺省 / 空串 = 沿用偏好 */
  city?: string
  /** 标签 ID,**命中其一即可**;空数组 / 缺省 = 不筛标签 */
  tag_ids?: number[]
}

/**
 * 「今日精选」(discovery.md §3.11)。
 *
 * ⚠️ 响应是**包装对象** `{date, candidates}`,不是裸数组 —— 别按 `GET /discovery/candidates`
 * 的形状解析。`date` 是服务端算种子用的日期(`YYYY-MM-DD`),本期只展示,不做「今天已看过」。
 */
export interface DailyCandidates {
  date: string
  candidates: Candidate[]
}

export interface MatchSummary {
  user_id: number
  /** 形如 u9,聊天时用它 */
  im_user_id: string
  nickname: string
  avatar_url: string | null
  /** ISO 8601 */
  matched_at: string
  /** 共同标签(discovery.md §3.3);无交集为空数组 */
  shared_tags: Tag[]
}

/** 撤销滑卡的结果(discovery.md §3.9);失败走 `400` + `40003` 错误信封,不会是 `undone: false`。 */
export interface SwipeUndoResult {
  undone: boolean
  /** 被撤销的那次滑卡的目标账号 ID:按它把卡放回卡堆 */
  target_user_id: number
}

/**
 * 每日喜欢额度(discovery.md §3.10)。
 *
 * 额度按自然日(`Asia/Shanghai`)算;`like_limit = 0` 表示不限,此时 `likes_used` 恒为 0、
 * `likes_remaining` 为 `null` —— 页面据此**整块不显示**额度文案。
 */
export interface SwipeQuota {
  /** 每日喜欢上限,0 = 不限 */
  like_limit: number
  /** 今天已用掉的喜欢次数(不限时恒为 0) */
  likes_used: number
  /** 今天还剩多少次(不小于 0);不限时为 `null` */
  likes_remaining: number | null
}

/** 「喜欢我的人」列表项:公开资料 + 喜欢时间(discovery.md §3.4)。 */
export interface LikeReceived extends Candidate {
  /** ISO 8601 */
  liked_at: string
}

/** 「谁看过我」列表项:公开资料 + 最近访问时间(discovery.md §3.7)。 */
export interface ProfileVisit extends Candidate {
  /** ISO 8601,精度 30 分钟 */
  visited_at: string
}

export interface PostAuthor {
  user_id: number
  nickname: string
  avatar_url: string | null
}

export interface Post {
  id: number
  author: PostAuthor
  text: string
  /** 完整 URL,最多 9 张 */
  images: string[]
  like_count: number
  comment_count: number
  liked_by_me: boolean
  /** ISO 8601 */
  created_at: string
}

export interface ReplyTo {
  user_id: number
  nickname: string
}

export interface Comment {
  id: number
  author: PostAuthor
  text: string
  /** 顶级评论为 null;回复为所属顶级评论 ID */
  parent_id: number | null
  /** 被回复者;顶级评论为 null */
  reply_to: ReplyTo | null
  /** 该楼层的可见回复总数(回复对象恒为 0) */
  reply_count: number
  /** 内嵌的前 2 条回复(回复对象恒为空) */
  replies: Comment[]
  created_at: string
}

export type ReportType = 'harassment' | 'porn' | 'fraud' | 'other'

/** 站内通知的触发者摘要(notifications.md §1.1)。 */
export interface NotificationActor {
  /** 账号 ID(可直接拼 `/chat/u{id}`) */
  id: number
  nickname: string
  /** 首张已过审照片;无照片为 null */
  avatar: string | null
}

/** 通知点击后的跳转目标;`kind=none` 时 `id` 为 null。 */
export interface NotificationTarget {
  kind: 'post' | 'user' | 'none'
  id: number | null
}

/**
 * 一条站内通知(notifications.md §1.1)。
 *
 * `kind` 取值:`post_like` / `post_comment` / `comment_reply` / `match` /
 * `report_handled` / `system`。正文由服务端生成(`text`),前端直接展示。
 */
export interface AppNotification {
  id: number
  kind: string
  text: string
  is_read: boolean
  /** ISO 8601 */
  created_at: string
  actor: NotificationActor | null
  target: NotificationTarget
}

/**
 * 一个「登录过的端」(auth.md §1.6)。
 *
 * 一类端一行,最多两行(`app` / `web`);从没登录过的端不会出现。
 * `current` 由**请求头** `X-Client` 判定(不是令牌里的 `ct`),有且只有一项为 `true`。
 */
export interface LoginDevice {
  client_type: string
  /** 端展示名,服务端给的就是「App」/「网页端」,前端不再自己映射 */
  client_label: string
  current: boolean
  /** 该端首次登录时间(ISO 8601) */
  created_at: string
  /** 最近一次登录或刷新令牌的时间;批次 M 之前建的行、或从未刷新过为 null */
  last_active_at: string | null
}

/** 使用报告的统计周期(stats.md §1.1):自然周 / 自然月 / 自然年。 */
export type StatsPeriod = 'week' | 'month' | 'year'

/**
 * 我的使用报告(stats.md §1.1)。
 *
 * 口径是「区间内发生的事件」,不是当前存量;`start` / `end` 是**含首含尾**的日期
 * (`YYYY-MM-DD`),一律按 `Asia/Shanghai` 的自然周期算。
 * 七项计数都是非负整数,**0 也是有效值**,页面必须原样显示 `0`。
 */
export interface MyStats {
  period: StatsPeriod
  /** YYYY-MM-DD */
  start: string
  /** YYYY-MM-DD */
  end: string
  /** 区间内新产生的配对(我参与的,含事后已解除的) */
  matches: number
  likes_given: number
  likes_received: number
  /** 区间内看过我资料的人数(一人一行,按最近访问时间) */
  visits: number
  posts: number
  post_likes: number
  new_followers: number
}
