# 「谁看过我」访客记录 设计文档

- 日期：2026-11-01
- 状态：设计已与用户逐段确认，待写实施计划
- 关联文档：`2026-10-20-likes-received-design.md`（同构参照）、`docs/api/discovery.md`、`docs/api/users.md`

---

## 0. 一句话

**打开他人资料页即记一次访问**；访客列表按人聚合、显示最近访问时间；提供「隐身浏览」开关；App 与 Web 的入口都放在发现页顶部，与「喜欢我的人」并列。

---

## 1. 背景与目标

### 1.1 现状

`GET /api/v1/users/{user_id}`（`chatapp/users/views.py::public_profile`）已经在调用
`chatapp/users/services.py::record_profile_view`，但它只写 Redis：按「自然小时」分桶统计
**不同目标数**，用于「疑似资料抓取」告警（`PROFILE_SCRAPE_ALERT_PER_HOUR`），既不落库、
也无法回看。

### 1.2 目标

把「谁看过我」变成可回看的信息，作为发现页的第二个社交信号入口，与「喜欢我的人」并列。

### 1.3 非目标（本次不做）

- 访客推送 / 站内通知 / 灰条（避免打扰，且与「被喜欢」通知语义重复）
- 「上次查看后新增」的未读角标（本次角标 = 去重后的总人数）
- 访客次数统计、访客排行榜
- 付费可见 / 模糊化（无会员体系）
- 除 App 与 Web 外的其它端

---

## 2. 已确认决策

| # | 决策点 | 结论 |
|---|---|---|
| 1 | 什么算「看过我」 | 打开我的资料页（`GET /users/{id}` 成功返回）即算；滑卡经过、广场卡片曝光不算 |
| 2 | 多次访问怎么展示 | 每人一行，只显示最近访问时间（不显示次数） |
| 3 | 隐私 | 提供「隐身浏览」开关，默认关闭；开启后我的访问不写入任何人的访客列表，但我仍能看别人 |
| 4 | 入口 | 发现页顶部，与「喜欢我的人」并列（App + Web） |
| 5 | 写入方式 | 服务端隐式落库：扩展现有 `record_profile_view`，不新增客户端上报接口 |
| 6 | 已配对的人 | 不出现在访客列表（他们已在消息列表，避免重复入口） |
| 7 | 协议版本 | 隐私政策补「访问记录」条款，双端 `legalVersion` 2 → 3，老用户重新弹一次 |

---

## 3. 数据模型

### 3.1 新表 `users.ProfileVisit`

放在 `users` app 而不是 `discovery`：写入点在 `users.services`，而 `discovery` 本来就依赖
`users`（`discovery/services.py` 已 import `users.models`），反过来会形成 app 间的循环依赖。

| 字段 | 类型 | 说明 |
|---|---|---|
| `viewer` | `FK(User, CASCADE, related_name="visits_made")` | 谁来看的 |
| `owner` | `FK(User, CASCADE, related_name="visits_received")` | 被看的人 |
| `first_at` | `DateTimeField(auto_now_add=True)` | 首次访问时间 |
| `last_at` | `DateTimeField(db_index=True)` | 最近一次访问时间（精度 30 分钟，见 §4.2） |

约束与索引：

```python
class Meta:
    ordering = ["-last_at"]
    constraints = [
        models.UniqueConstraint(fields=["viewer", "owner"], name="uniq_visit_viewer_owner"),
    ]
    indexes = [
        models.Index(fields=["owner", "-last_at"], name="idx_visit_owner_last"),
    ]
```

- `uniq_visit_viewer_owner`：每人一行（决策 2）的基础，也是并发写入的兜底
- `idx_visit_owner_last`：列表查询固定是「`owner = me` + 按 `last_at` 倒序分页」，复合索引可
  直接走索引序，不需要额外排序（MySQL 8 支持降序索引）
- **不建 `count` 字段**：决策 2 只显示最近时间，次数没有任何消费方；将来要加是一次纯加列迁移

### 3.2 `Profile` 新增字段

```python
visits_hidden = models.BooleanField("隐身浏览", default=False)
```

- 默认 `False`（决策 3），存量用户迁移后自动为「正常记录」
- 只在 `GET/PATCH /users/me` 暴露；`PublicProfileSerializer` 是独立序列化器，**不得**包含它

### 3.3 迁移与级联

- 一个迁移同时建表与加列（`users/migrations/00xx_profilevisit.py`）
- 账号注销：`CASCADE` 会清掉该用户作为 `viewer` 与 `owner` 的全部行，
  `users/services.py::delete_account` 无需改动

---

## 4. 写入路径

### 4.1 落点

`chatapp/users/services.py::record_profile_view(viewer_id, target_id)` 末尾追加落库逻辑。
选择它的理由：它是「看了谁的资料」这件事**唯一**的服务端入口，App 与 Web 都走
`GET /users/{id}`，不可能漏报，也无法被伪造。

### 4.2 顺序

```
record_profile_view(viewer_id, target_id):
    1. [现有] Redis 按小时分桶，统计抓取广度，超阈值 WARNING
    2. 隐身判断：Profile.objects.filter(user_id=viewer_id)
                        .values_list("visits_hidden", flat=True).first()
       为 True → return（只做监控，不落库）
       注意：Profile 是懒创建的，取不到（None）按「未隐身」处理
    3. Redis cache.add("visit:{viewer}:{owner}", 1, timeout=1800)
       失败（30 分钟内已写过）→ return
    4. ProfileVisit.objects.update_or_create(
           viewer_id=viewer_id, owner_id=target_id, defaults={"last_at": now})
       并发 IntegrityError → 重试一次 update(last_at=now)
    5. 任何异常只记 logger.debug，绝不影响资料接口的 200
```

### 4.3 为什么要 30 分钟去重

- **防写放大**：同一个人反复下拉刷新资料页，每次 `GET` 都写一行 UPDATE 是无意义的写压力
  （2C2G 单机 MySQL 上尤其明显）
- **防时间抖动**：列表只显示「最近访问时间」，精度到 30 分钟足够（前端渲染「刚刚 / 3 小时前 /
  昨天」）
- **量级估算**：1000 个访客/天 × 1 次/人/30 分钟 ≈ 1000 行/天，90 天保留期约 9 万行，可忽略

### 4.4 已知取舍

`GET` 带写副作用不符合严格 REST 语义。接受的三个理由：

1. 这个 `GET` 本来就有副作用（Redis 写），只是没落库
2. 本项目该接口没有 CDN/代理缓存，不存在「缓存命中导致漏记」或「预取导致误记」的实际路径
3. 换成前端显式上报会引入「多一次请求 + 两端都要改 + 可被脚本刷 + 容易漏报」四个新问题

---

## 5. 列表口径

### 5.1 唯一口径函数

`chatapp/discovery/services.py::visits_received_queryset(me)` —— 列表与计数**必须**共用它，
与 `likes_received_queryset` 同构。

过滤条件：

| 条件 | 原因 |
|---|---|
| `owner = me` | 我的访客 |
| `viewer != me` | 自己看自己不算 |
| 排除我已划过的人（`Swipe.swiper = me`） | 与「喜欢我的人」同口径；我已 pass 的人没有价值，我已 like 的人一旦对方也 like 就会直接配对 |
| 排除双向拉黑 | 与全站口径一致 |
| 只留 `viewer.profile.status == COMPLETE` | 一并排掉未完善与两种封禁，点进去不会是空页面 |
| 只留有过审照片的人 | 与 `likes_received_queryset` 保持一致（`COMPLETE` 已隐含，保留为显式口径） |

> **已配对的人不需要单独过滤**：配对的前提是双方都划过对方，所以「排除我已划过」已经天然
> 覆盖了决策 6。不再 join `Match` 表，少一次关联。

排序：`-last_at, -id`（`id` 兜底保证分页稳定）。

### 5.2 与「喜欢我的人」的差异

只有排序键不同（`last_at` vs `created_at`），其余口径逐条对齐，便于将来抽公共函数。

---

## 6. 接口契约

### 6.1 `GET /api/v1/discovery/visits`

- 分页：`DefaultLimitOffsetPagination`（`limit` / `offset`，默认 20 条、单页上限 100，与
  `/discovery/likes` 一致）
- 权限：登录用户；`banned_heavy` 由全局权限类拦（403）；`banned_light` 可看

响应：

```json
{
  "count": 12,
  "next": null,
  "previous": null,
  "results": [
    {
      "user_id": 12,
      "im_user_id": "u12",
      "nickname": "小雨",
      "gender": "female",
      "age": 24,
      "city": "杭州",
      "bio": "喜欢徒步和摄影",
      "tags": [{ "id": 3, "name": "旅行", "icon": "flight" }],
      "photos": [{ "id": 9, "url": "https://.../media/photos/2026/10/x.jpg", "order": 0 }],
      "visited_at": "2026-11-01T12:30:00+08:00"
    }
  ]
}
```

- `photos` 只含 `status=approved`
- `visited_at` 即 `last_at`
- 序列化器 `VisitSerializer`：字段与 `LikeReceivedSerializer` 对齐，`ModelSerializer` 指向
  `ProfileVisit`，`user_id` / `nickname` 等用 `source="viewer...."`

### 6.2 `GET /api/v1/discovery/visits/count`

```json
{ "count": 12 }
```

与列表同口径（同一个 queryset 的 `.count()`），供入口角标使用。

### 6.3 隐身开关（复用现有端点）

- `GET /api/v1/users/me` 响应新增 `"visits_hidden": false`
  —— `ProfileSerializer.Meta.fields` 加 `visits_hidden`（只读侧）
- `PATCH /api/v1/users/me` 接受 `{"visits_hidden": true}`
  —— `ProfileUpdateSerializer`（这是个独立的写序列化器，不是 `ProfileSerializer`）加
  `visits_hidden = serializers.BooleanField(required=False)`；`views.me` 的 PATCH 分支是
  `setattr` + `profile.save()`，无需改视图逻辑
- `GET /api/v1/users/{id}` 的公开资料**不含**该字段（`PublicProfileSerializer` 字段表不变）

理由：一个布尔值单独开 `/users/me/privacy` 端点不划算；`PATCH /users/me` 已有「改我自己的资料」
语义，隐私开关属于同一范围。

### 6.4 错误契约

不变：失败一律 `{"code": <HTTP状态码>, "message": "<中文>", "request_id": ...}`。

### 6.5 限流

沿用 M-2 已生效的全局读接口账号级 `RateTable`，不额外加 throttle 类：列表是一条走复合索引的
分页查询，成本与 `/discovery/likes` 同量级。

---

## 7. App 前端

### 7.1 发现页入口

`app/lib/features/discovery/discovery_page.dart`：把私有 `_LikesEntry` 抽成通用
`_TopEntry({icon, label, count, key, onTap})`，标题行右侧并排两枚：

| 入口 | 图标 | 文案 | Key | 路由 |
|---|---|---|---|---|
| 喜欢我的人 | `Icons.favorite_rounded` | 喜欢我的人 | `discovery.likes` | `/likes` |
| 谁看过我 | `Icons.visibility_rounded` | 谁看过我 | `discovery.visits` | `/visits` |

- 角标：`visitsReceivedCountProvider`（新 FutureProvider），`count > 0` 才显示 `AppBadge`
- 窄屏降级：`LayoutBuilder` 宽度 < 360dp 时隐藏文案只留图标，`Semantics(label: '谁看过我，12 人')`
  保证读屏可读
- 颜色：图标用 `AppColors.text2`，品牌色只保留在「喜欢我的人」的心形上（心跳规则：主色只出现在
  引导视线处，两个彩色图标会互相抢）

### 7.2 访客列表页 `/visits`

新文件：`visits_page.dart`、`visits_controller.dart`（`AsyncNotifier<VisitsState>`，与
`likes_received_controller.dart` 同构）、`discovery_repository.dart` 加两个方法。

- 顶栏：`AppSubPageBar(title: '谁看过我')`
- 四态：骨架（共用提升后的 `AppListSkeleton`）/ `AppErrorView` + 重试 / 空态（`HeartRipple` +
  「还没有人看过你」+ 描述「完善资料、多发动态，被看到的机会更多」+ 「去完善资料」）/ 列表
- 行：`AppListRow`，44 头像 + 昵称 + 副标题 `24 岁 · 杭州 · 3 小时前`（相对时间用现有
  `formatPostTime`），点击 `context.push('/users/{id}')`
- trailing：`AppTextAction('喜欢')` —— 复用 `POST /discovery/swipe`；`matched=true` 时弹现有
  `showMatchOverlay`，否则 toast「已喜欢」。理由：资料页本身没有「喜欢」入口，访客列表若只能看，
  用户看完无处可去；后端接口已存在，前端只是复用
- 交互：下拉刷新 + 触底加载更多（与 `likes_received_page` 同一套写法）

### 7.3 设置页开关

`app/lib/features/settings/settings_page.dart` 第一张 `AppRowGroup` 内追加：

```
AppListRow(
  key: Key('settings.row.visitsHidden'),
  icon: Icons.visibility_off_rounded,
  title: '隐身浏览',
  subtitle: '开启后，你看过的人不会看到你的访问记录',
  trailing: Switch.adaptive(...),
)
```

- 乐观更新：先翻转本地状态 → `PATCH /users/me` → 失败回滚 + `AppToast`
- 成功/失败后 `ref.invalidate(profileProvider)`
- `app/lib/features/profile/models.dart` 的 `Profile` 加 `visitsHidden`

### 7.4 组件提升

`likes_skeleton.dart` 目前是「喜欢页专用」的骨架。提升为
`app/lib/core/widgets/app_list_skeleton.dart`（构造参数：`key`、`rowCount`，默认 6），
`likes` 与 `visits` 共用，避免复制第二份。

---

## 8. Web 前端

| 位置 | 改动 |
|---|---|
| `web/src/api/discovery.ts` | `fetchVisits(limit, offset)`、`fetchVisitsCount()` |
| `web/src/api/types.ts` | `ProfileVisit`（字段同 `LikeReceived`，时间字段 `visited_at`）、`Profile.visits_hidden` |
| `web/src/stores/visits.ts` | 新 store，照 `stores/likes.ts` 骨架（items / count / offset / loading / error / busyUserId / matched / load / loadCount / accept / dismissMatched） |
| `web/src/features/discovery/TopEntry.vue` | 由 `LikesEntry.vue` 泛化而来（props：`icon` / `label` / `to` / `count`），样式只留一份 |
| `web/src/features/discovery/VisitsPage.vue` | 镜像 `LikesPage.vue`：骨架 / `AppErrorView` / `AppEmpty` / 列表 / 加载更多 / `MatchMoment` |
| `web/src/router/routes.ts` | 新增 `/visits`，name `visits` |
| `web/src/features/settings/SettingsPage.vue` | 「账号与隐私」组末尾加「隐身浏览」开关行（`<button role="switch" :aria-checked>`），乐观更新 + 失败回滚 |
| `web/src/features/legal/privacy.ts` | 补「访问记录」条款 |
| `web/src/features/legal/agreed.ts` | `LEGAL_VERSION` 2 → 3 |

`web/src/features/discovery/DiscoveryPage.vue` 里 `<LikesEntry />` 换成两枚 `<TopEntry>`。

---

## 9. 合规

- 隐私政策新增一条：**为展示「谁看过我」，我们会记录访问你资料页的账号与最近访问时间；你可以在
  设置中开启「隐身浏览」，开启后你的访问不会被对方看到**
- 双端协议版本同步 `2 → 3`（`app/lib/features/legal/legal_texts.dart::legalVersion`、
  `web/src/features/legal/agreed.ts::LEGAL_VERSION`），老用户下次启动重新弹一次
- 数据保留期 90 天（§10），符合「最小必要」原则
- 访客记录属于个人信息，但**不对外公开**：只有被访者本人可见，且受拉黑/封禁/配对口径约束

---

## 10. 保留期与运维

新命令 `chatapp/users/management/commands/purge_profile_visits.py`：

```bash
python manage.py purge_profile_visits            # dry-run，打印将删除的行数与最老时间
python manage.py purge_profile_visits --apply    # 真删 last_at 早于 90 天的行
```

- 保留期常量 `PROFILE_VISIT_RETENTION_DAYS = 90` 放 `users/services.py`
- 计划任务：每天 03:40 `--apply`（避开现有媒体清理任务时段）
- 上线必跑：`python manage.py migrate`

---

## 11. 测试计划

### 11.1 后端（`chatapp/users/tests.py`、`chatapp/discovery/tests.py`）

1. 首次访问落库一行；30 分钟内重复访问不新增行、`last_at` 不变
2. 30 分钟后再次访问 → `last_at` 前进，仍是一行（测试里清掉 `visit:*` 缓存键模拟窗口过期）
3. 隐身开启后不落库，但抓取监控仍然工作（Redis 计数可断言）
4. 自己看自己 → 不记录
5. 列表口径：排除我已划过 / 双向拉黑 / 未完善 / 无过审照片 / 自己；已配对的人因「我已划过」被排除
6. `count` 与列表同一查询集（同一组数据下数字一致）
7. `GET /users/me` 返回 `visits_hidden`；`PATCH` 可切换；`GET /users/{id}` 不含该字段
8. `purge_profile_visits`：dry-run 不删；`--apply` 只删 90 天前，边界（刚好 90 天）不删
9. 落库抛异常时 `GET /users/{id}` 仍返回 200（mock `update_or_create` 抛异常）
10. 迁移后存量 `Profile.visits_hidden` 为 `False`

### 11.2 App（`app/test/features/discovery/`、`app/test/features/settings/`）

1. 发现页显示两枚入口；有访客时角标显示数字
2. 点 `discovery.visits` 进入 `/visits`
3. 访客页四态：骨架 / 错误重试 / 空态 / 列表
4. 行副标题含相对时间；点击进 `/users/{id}`
5. 点「喜欢」发出 `POST /discovery/swipe`（脚本化 adapter 断言请求体）
6. 设置页开关：开启 → PATCH `{"visits_hidden": true}`；失败回滚并 toast

### 11.3 Web（vitest）

1. `stores/visits`：load / loadMore / accept / loadCount 与 likes 同构
2. `VisitsPage`：四态 + 时间格式
3. `SettingsPage`：开关乐观更新与失败回滚

### 11.4 文档门禁

- `docs/api/discovery.md` 新增两节；`docs/api/users.md` 补 `visits_hidden`
- `docs/api/README.md` 接口总数 43 → 45
- `docs/pitfalls/backend.md` 补一条「GET 带写副作用 + 30 分钟去重」的取舍记录
- `ApiDocsCoverageTests`、`CommentCoverageTests` 必须绿

---

## 12. 上线清单

1. 后端：`migrate`（`users` 迁移 `0006_profile_visits_hidden_profilevisit`：新表 + 新列）
2. 计划任务：每天 03:40 `python manage.py purge_profile_visits --apply`（crontab 写法与现有 `media_cleanup` 计划任务保持一致）
3. App：发版（`pubspec.yaml` + `app_info.dart` + 关于页测试期望三处同改），重打签名 APK
4. Web：`npm run build` 并部署 `dist`；`web/package.json` 版本号同改
5. `.env` 的 `MIN_APP_VERSION` / `LATEST_APP_VERSION` / `APP_DOWNLOAD_URL` 按发版节奏更新
6. 手测：App 两入口 + 访客页 + 隐身开关；Web `/visits` + 设置开关；用两个账号互相访问验证

---

## 13. 风险与备选

| 风险 | 影响 | 应对 |
|---|---|---|
| `GET` 带写副作用 | 语义争议 | 已记录取舍（§4.4）；如未来加 CDN 缓存必须改为显式上报 |
| 30 分钟去重导致时间偏差 | 「3 小时前」可能偏早 | 可接受：列表只做相对时间展示 |
| 隐身开启后自己的访客列表仍有旧记录 | 无影响（隐身只影响别人看我） | 文案说明清楚 |
| 90 天保留期让老访客消失 | 用户可能疑惑 | 空态与文档说明；如需更长再调常量 |
| `update_or_create` 并发 `IntegrityError` | 偶发 500 | 捕获后重试一次 `update`，仍失败只记日志（不影响响应） |

---

## 14. 明确不做（YAGNI）

- 访客次数、访客来源（资料页 / 广场 / 聊天）、停留时长
- 未读角标与「标记已读」接口
- 访客推送 / 灰条
- 付费可见、模糊头像、匿名访客
- Web 之外的其它端
