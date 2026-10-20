# 喜欢我的人(设计)

日期:2026-10-20 · 状态:设计已获用户批准(逐节确认后「开始」)
上游:P1 留存闭环第一小批(用户 2026-10-20 选定;P1 拆分见本文件 §1)。
下游:实施计划 `docs/superpowers/plans/2026-10-20-likes-received.md`。

## 1. 背景与定位

P1「留存闭环」被拆成四个可独立验收的小批:

| 批次 | 内容 | 外部依赖 |
|---|---|---|
| **P1-1 喜欢我的人** | 本文件 | 无 |
| P1-2 设置页补齐 | 意见反馈 / 关于 / 版本 / 通知设置骨架 | 无 |
| P1-3 关系出口 | 解除配对 / 撤回消息 / 已读回执 | 腾讯 IM SDK + 真机 |
| P1-4 推送 | 设备 token / 厂商通道 / 深链 | 厂商账号、证书、真机 |

当前「喜欢」是单向的:我 `like` 了对方,对方在滑卡池里看不到任何提示;只有**互喜**那一刻才有配对灰条。
这导致两个问题:

1. **转化漏损**:对方可能永远不再滑到我,我的喜欢石沉大海;
2. **没有回访理由**:用户不知道「有人喜欢我」,没有打开 App 的动机。

**目标:** 把「收到的喜欢」做成一个可见、可回喜欢、可直接转化为配对的列表,App 与 Web 双端交付。

**非目标(本批不做):**

- 付费 / 模糊头像 / 解锁计数(项目暂无支付体系,模糊化只会让用户点进去无路可走);
- 「我喜欢的人」(我发出的喜欢)列表;
- 超级喜欢 / 喜欢配额 / 每日限制;
- 推送提醒(P1-4);
- 服务端未读状态(列表不做已读/未读标记);
- 列表内展示在线状态(客户端已有 presence 轮询,本批不为每行多查一次 Redis)。

## 2. 已定关键决策(用户确认)

| 决策点 | 结论 | 落选理由 |
|---|---|---|
| 展示策略 | **免费完整展示**(头像 / 昵称 / 年龄 / 城市 / 标签 / 时间) | 无支付体系;模糊化是死路。先把互喜转化跑起来 |
| 交付范围 | **App + Web 双端** | 项目惯例:同一套接口、两端能力对齐、token 双份维护 |
| 回喜欢接口 | **复用 `POST /discovery/swipe`**,不新增 accept 接口 | 配对副作用必须继续走 `swipe` 一条入口(`notify_match` 唯一入口);新增接口会复制配对逻辑 |
| 数据口径 | 与候选池**完全同口径**:`Profile.status=COMPLETE` + ≥1 张已过审照片 + 排除双向拉黑 | 口径漂移会让用户点进「资料不完整」的人,回喜欢直接 400 |
| 我已划过的人 | **排除**(like / pass 都算) | 现有 `swipe` 幂等:pass 之后不会翻成 like;让他出现在列表里,点「喜欢」只会得到 `matched=false`,是死胡同 |
| 计数接口 | 单独 `GET /discovery/likes/count` | 角标只要数字,不值得为拿 count 序列化一整页 |

## 3. 数据口径(唯一事实来源)

新增 `discovery/services.py::likes_received_queryset(me)`:

```python
def likes_received_queryset(me):
    """收到的喜欢:与候选池同口径,排除我已划过 / 已配对 / 双向拉黑。"""
    swiped = Swipe.objects.filter(swiper=me).values("target_id")
    with_photos = Photo.objects.filter(status=PhotoStatus.APPROVED).values("user_id")
    return (Swipe.objects
            .filter(target=me, action=SwipeAction.LIKE)
            .exclude(swiper_id=me.id)
            .exclude(swiper_id__in=swiped)          # 我已划过(含 pass)
            .exclude(swiper_id__in=blocked_user_ids(me))
            .filter(swiper__profile__status=ProfileStatus.COMPLETE)
            .filter(swiper_id__in=with_photos)
            .select_related("swiper__profile")
            .prefetch_related("swiper__photos", "swiper__profile__tags")
            .order_by("-created_at", "-id"))
```

**口径说明**

- 起点是 `Swipe(target=me, action=like)` —— 「他喜欢我」;
- `exclude(swiper_id__in=swiped)` 同时覆盖「我已 like」与「我已 pass」;互喜后我必然划过对方,因此**已配对的人也天然被排除**,不需要再查 `Match`(保留一条防御性测试,确认不会漏);
- `filter(swiper__profile__status=COMPLETE)` 自动排除未完善、轻封禁、重封禁(封禁与完善度共用 `Profile.status`);
- `filter(swiper_id__in=with_photos)` 与候选池一致:只推有已过审照片的人;
- 排序 `-created_at, -id` —— 最近喜欢在前,时间相同按 id 稳定排序(分页不漂移);
- 列表与计数**必须**共用本函数;禁止在 view 里另写一份查询。

## 4. 接口契约

### 4.1 `GET /api/v1/discovery/likes`

> 需要鉴权 · 分页(LimitOffset,默认 20 / 上限 100)

**响应**:分页对象 `{count, next, previous, results}`。`results` 每项:

| 字段 | 类型 | 说明 |
|---|---|---|
| user_id | Integer | 对方账号 ID |
| im_user_id | String | IM 账号,如 `u12`(跨栈约定 `u{user_id}`) |
| nickname | String | 昵称 |
| gender | String | `male` / `female` |
| age | Integer \| null | 周岁;未填生日时为 `null` |
| city | String | 城市 |
| bio | String | 简介 |
| tags | Object[] | `{id, name, icon}`,与 users.md 同结构 |
| photos | Object[] | **只含已过审**;`{id, url, status, order}` |
| liked_at | String(ISO 8601) | 对方喜欢我的时间 |

- 不返回手机号、生日、封禁原因、资料缺失项等隐私字段;
- 头像由客户端取 `photos[0]`(与候选卡同一套渲染逻辑);
- 轻封禁账号**可以查看**列表(轻封禁只禁滑卡);重封禁由全局权限类 403。

### 4.2 `GET /api/v1/discovery/likes/count`

**响应**:`{"count": 12}`

- 与列表同口径;仅用于入口角标;
- 无分页参数。

### 4.3 错误

| 场景 | 结果 |
|---|---|
| 未登录 / token 失效 | `401` |
| 重封禁 | `403`(全局权限类自动覆盖) |
| 轻封禁 | 列表可读;回喜欢时由 `swipe` 返回 `403` |

## 5. App 端设计

### 5.1 入口

发现页标题行改为 `Row(spaceBetween)`:

- 左:「发现」大标题(不变);
- 右:心形图标 + `AppBadge(count)` 的可点击胶囊。

品牌粉只出现在 `AppBadge` 的渐变角标上,符合「一屏一个高音」。数量为 0 时角标隐藏(`AppBadge` 已内置),入口仍可点(进空态)。

### 5.2 页面 `LikesReceivedPage`

- 顶栏:`AppSubPageBar(title: '喜欢我的人')`;
- 列表行:直接复用 `AppListRow`(高 64):
  - `avatar`: `AppAvatar(size: 44)`,首字占位兜底;
  - `title`: 昵称;
  - `subtitle`: `年龄 · 城市 · 标签1 · 标签2`(年龄为 null 时省略年龄;标签最多 3 个,用 `·` 连接);
  - `trailing`: `AppTextAction(label: busy ? '喜欢中' : '喜欢')`(紧凑形态,能塞进 64 行;`AppButton` 固定 52 高,放进来太挤);
  - `onTap`: 进现有 `/users/:id` 资料页(那里已有举报/拉黑);
  - 相对时间用 `formatPostTime`(`app/lib/core/format.dart`),**放 `subtitle` 末尾**,不新增第三行,保持行高 64。
- 下拉刷新 + 触底加载更多(每页 20)。

### 5.3 状态

| 状态 | 呈现 |
|---|---|
| 加载中 | 6 行骨架(新建 `LikesSkeleton`,样式对齐 `BlockedUsersSkeleton`) |
| 空 | `AppEmptyState(mark: HeartRipple(), title: '还没有人喜欢你', description: '把资料完善一点,多滑几张卡,缘分快到了', action: '去完善资料')` |
| 错误 | `AppErrorView(message, onRetry)` |
| 正常 | 列表 |

### 5.4 回喜欢

复用 `DiscoveryRepository.swipe(targetUserId: userId, like: true)`:

1. 按钮进入 loading,禁用重复点击;
2. 成功后:从本地列表移除该行、`count - 1`、`ref.invalidate(matchCacheProvider)`(刚配对的人昵称/头像要立刻能显示);
3. 因为列表里的人**必然**喜欢过我,`matched` 应为 `true`;若返回 `true`,复用现有 `showMatchOverlay(candidate: ..., myAvatarUrl: ..., onGoChat: ...)` 配对情感时刻;
4. 若返回 `false`(并发/脏数据),只弹 toast「已喜欢」,不做配对动效;
5. 失败:toast 后端 `ApiException.message`,本地移除该行并重新拉取(对方可能已注销/被封/拉黑)。

### 5.5 文件

| 文件 | 职责 |
|---|---|
| `app/lib/features/discovery/likes_received_controller.dart`(新增) | 列表分页状态 + `accept(userId)` 编排(移除 / 计数 / 配对缓存 / 弹层数据) |
| `app/lib/features/discovery/likes_received_page.dart`(新增) | 页面壳 + 四态 + 列表(行直接复用 `AppListRow`) |
| `app/lib/features/discovery/widgets/likes_skeleton.dart`(新增) | 骨架 |
| `app/lib/features/discovery/discovery_repository.dart`(改) | `fetchLikesReceived` / `fetchLikesReceivedCount` |
| `app/lib/features/discovery/models.dart`(改) | `LikeReceived`(含 `Candidate` + `likedAt`) |
| `app/lib/features/discovery/discovery_page.dart`(改) | 标题行加入口 + 角标 |
| `app/lib/router.dart`(改) | `/likes` 路由 |

## 6. Web 端设计

### 6.1 入口

`DiscoveryPage` 顶部、`MatchesList` 上方,一个胶囊按钮:

`💗 喜欢我的人 · {{ count }}` → `router.push({ name: 'likes' })`

数量为 0 时只显示「喜欢我的人」,不显示 0。

### 6.2 路由与页面

- 路由:`/likes`,`name: 'likes'`,**壳外二级页**(与 `/settings` 一致,页面自带返回);
- 页面 `web/src/features/discovery/LikesPage.vue`:
  - `h1` 标题「喜欢我的人」;
  - 列表行:头像 48、昵称 + 年龄·城市、标签、相对时间、「喜欢」按钮;
  - 空态 `AppEmpty(emoji: '💗', title: '还没有人喜欢你', description: ...)`;
  - 错误 `AppErrorView`;加载 `AppSkeleton`;
  - 接受后复用 `MatchMoment` 弹层。
- store `web/src/stores/likes.ts`:`items` / `count` / `loading` / `error` / `load(reset)` / `accept(userId)`。

### 6.3 文件

| 文件 | 职责 |
|---|---|
| `web/src/api/discovery.ts`(改) | `fetchLikesReceived` / `fetchLikesReceivedCount` |
| `web/src/api/types.ts`(改) | `LikeReceived` 类型 |
| `web/src/stores/likes.ts`(新增) | 列表/计数/接受 |
| `web/src/features/discovery/LikesPage.vue`(新增) | 页面 |
| `web/src/features/discovery/LikesEntry.vue`(新增) | 入口胶囊 |
| `web/src/features/discovery/DiscoveryPage.vue`(改) | 挂入口 |
| `web/src/router/routes.ts`(改) | `/likes` |

## 7. 边界与失败路径

| 场景 | 行为 |
|---|---|
| 对方在列表打开后注销 | `Swipe` 级联删除 → 下次刷新消失;若已点「喜欢」,`swipe` 返回 400/404 → toast + 移除 |
| 对方被封禁 | 口径即时排除;已打开列表里的旧行点「喜欢」→ `swipe` 校验资料非 COMPLETE → 400 → toast + 移除 |
| 我拉黑对方 | `blocked_user_ids` 即时排除;列表刷新后消失 |
| 重复点「喜欢」 | 按钮 loading + 后端 `swipe` 幂等;不会重复配对/重复灰条 |
| 角标滞后 | 进入发现页时刷新;回喜欢后本地减一;**不轮询** |
| 年龄为空 | 接口 `null`,前端只显示城市 |

## 8. 测试与门禁

### 8.1 后端(`discovery/tests.py`)

- 只包含 `target=me, action=like`,不含 pass;
- 排除我已划过(like / pass 两种);
- 排除已配对(防御性);
- 排除双向拉黑(我拉黑 / 拉黑我);
- 排除资料未完善、无已过审照片、轻封禁、重封禁;
- 排序 `liked_at` 倒序;
- 分页 `limit/offset`;
- `count` 与列表 `count` 一致,且遵守同一套排除规则;
- 401 / 重封禁 403 / 轻封禁可读;
- 响应字段不含 `phone` / `birthday` / `ban_reason` / `missing_fields`;
- `im_user_id` 为 `u{id}`。

### 8.2 App

- 入口角标显示数量;0 时不显示角标;
- 点击入口进入页面;
- 列表渲染昵称/年龄/城市/标签/时间;
- 空态 / 错误重试 / 骨架;
- 回喜欢:按钮 loading、行移除、计数 -1、`matchCacheProvider` 失效、配对弹层出现;
- 分页加载更多。

### 8.3 Web

- `stores/likes` 单测:load / 分页 / accept / count;
- 页面组件:入口、列表、空态、错误、接受后移除 + `MatchMoment`;
- 路由 `/likes` 可达。

### 8.4 文档与门禁

- `docs/api/discovery.md` 新增 §3.4 / §3.5;
- `docs/api/README.md` 接口数 32 → 34;
- `ApiDocsCoverageTests` 必须绿(增删接口未改文档即红);
- 后端全量 `python manage.py test`;
- App `flutter analyze` 零告警 + `flutter test`;
- Web `npm run type-check` + `npm run lint` + `npm run test:run`。

## 9. 已知取舍

- **不做未读标记**:「喜欢我的人」不是消息,没有已读语义;角标只表示总数。
- **不展示在线状态**:每行查一次 presence 会给列表增加 N 次 Redis 读;需要时客户端可用现有 presence store 批量查。
- **不做「忽略」**:不喜欢的喜欢就留在列表里,不提供 pass 入口——避免用户在两个地方做同一个决定。
- **回喜欢走 `swipe`**:会占用 300/小时滑卡限流;正常使用远达不到。

## 10. 验收标准

1. 后端:收到喜欢的人出现在列表;划过的人、已配对、双向拉黑、资料不全、无过审照片、封禁账号均不出现;
2. `count` 与列表一致,入口角标正确;
3. App / Web 都能完成「看到喜欢 → 回喜欢 → 配对成功」;
4. 空态 / 错误 / 骨架 / 分页四态齐全;
5. 接口文档同步,`ApiDocsCoverageTests` 绿;
6. 三端门禁全绿(后端测试 / `flutter analyze` + `flutter test` / `vue-tsc` + eslint + vitest)。
