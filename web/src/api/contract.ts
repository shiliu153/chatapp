/**
 * 手写类型 ↔ 生成类型（openapi-typescript）的编译期契约检查（D-5 第 3 步）。
 *
 * 为什么不是「用生成类型替换手写类型」：
 *   `types.ts` 里的类型带了业务注释与语义化别名（如 `age: number | null`），
 *   直接换掉会丢信息；真正会出事故的是**字段名对不上**（后端改名/删字段，前端还在读旧字段，
 *   运行时静默变成 undefined）。所以这里做「手写字段名 ⊆ schema 字段名」的编译期断言：
 *   后端一改字段名 → `npm run gen:api` 重新生成 → `npm run type-check` 立刻红。
 *
 * 为什么只做单向（手写 → schema）：
 *   反方向（schema 有、手写没有）是「后端新增字段」，对前端是向后兼容的，不该把 CI 卡红。
 *
 * 维护方式：
 *   在 `types.ts` 新增/修改接口后，下面补一行 `export type XxxUnknown = ...`；
 *   断言变红 = 你写了 schema 里没有的字段名（要么改前端，要么先改后端 + `docs/api/`）。
 *
 * 注意：`LoginResult` 这类**客户端映射后**的结构（`is_new_user` → `isNewUser`）不是线上
 * 报文形状，不参与本检查。
 */

import type { components } from './schema'
import type {
  AppNotification,
  Candidate,
  Comment,
  LikeReceived,
  LoginDevice,
  MatchSummary,
  MyStats,
  NotificationActor,
  NotificationTarget,
  Photo,
  Post,
  PostAuthor,
  PostLiker,
  Preference,
  Profile,
  ProfileVisit,
  PublicProfile,
  ReplyTo,
  SwipeQuota,
  SwipeUndoResult,
  Tag,
} from './types'

type Schema<K extends keyof components['schemas']> = components['schemas'][K]

/** 编译期断言：实参必须是 `never`；不是 `never` 时 TS 报「不满足约束」。 */
type MustBeNever<T extends never> = T

/** 手写类型里「schema 组件没有的字段名」。 */
type UnknownFields<TModel, TSchema> = Exclude<keyof TModel, keyof TSchema>

export type TagUnknown = MustBeNever<UnknownFields<Tag, Schema<'Tag'>>>
export type PhotoUnknown = MustBeNever<UnknownFields<Photo, Schema<'Photo'>>>
export type PreferenceUnknown = MustBeNever<UnknownFields<Preference, Schema<'Preference'>>>
export type ProfileUnknown = MustBeNever<UnknownFields<Profile, Schema<'Profile'>>>
export type PublicProfileUnknown = MustBeNever<UnknownFields<PublicProfile, Schema<'PublicProfile'>>>
export type CandidateUnknown = MustBeNever<UnknownFields<Candidate, Schema<'Candidate'>>>
export type MatchSummaryUnknown = MustBeNever<UnknownFields<MatchSummary, Schema<'MatchEntry'>>>
export type LikeReceivedUnknown = MustBeNever<UnknownFields<LikeReceived, Schema<'LikeReceived'>>>
export type ProfileVisitUnknown = MustBeNever<UnknownFields<ProfileVisit, Schema<'Visit'>>>
export type SwipeQuotaUnknown = MustBeNever<UnknownFields<SwipeQuota, Schema<'SwipeQuota'>>>
export type SwipeUndoResultUnknown = MustBeNever<
  UnknownFields<SwipeUndoResult, Schema<'SwipeUndo'>>
>
export type PostAuthorUnknown = MustBeNever<UnknownFields<PostAuthor, Schema<'AuthorBrief'>>>
export type PostUnknown = MustBeNever<UnknownFields<Post, Schema<'Post'>>>
/** 点赞列表元素(feed.md §5.16)。少了这条,`PostLiker` 等于没被契约检查。 */
export type PostLikerUnknown = MustBeNever<UnknownFields<PostLiker, Schema<'PostLiker'>>>
export type ReplyToUnknown = MustBeNever<UnknownFields<ReplyTo, Schema<'ReplyTo'>>>
export type CommentUnknown = MustBeNever<UnknownFields<Comment, Schema<'PostComment'>>>
export type NotificationActorUnknown = MustBeNever<
  UnknownFields<NotificationActor, Schema<'NotificationActor'>>
>
export type NotificationTargetUnknown = MustBeNever<
  UnknownFields<NotificationTarget, Schema<'NotificationTarget'>>
>
export type AppNotificationUnknown = MustBeNever<
  UnknownFields<AppNotification, Schema<'NotificationItem'>>
>
export type LoginDeviceUnknown = MustBeNever<UnknownFields<LoginDevice, Schema<'DeviceItem'>>>
export type MyStatsUnknown = MustBeNever<UnknownFields<MyStats, Schema<'MyStats'>>>
