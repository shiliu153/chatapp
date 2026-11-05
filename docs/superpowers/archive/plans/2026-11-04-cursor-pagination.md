# cursor/keyset 分页替代 offset(backlog D-1)

> **来源**:[backlog D-1](../../../backlog/2026-11-03-todo.md)、[全栈审查 §N-5](../../../reviews/2026-11-03-fullstack-review.md)、
> [可观测性与容量 B.3 未勾项](2026-11-02-observability-and-capacity.md)(深翻页 OFFSET 跳读 106ms)。
> **Goal**:把「头部持续插入」的四类列表从 `limit/offset` 换成复合游标(keyset)分页,
> 翻页不再重复/漏读,深翻页耗时与页深无关;App / Web / 接口文档三端同改。
> **Architecture**:后端新增 `config/cursor.py`(游标编解码 + 切片助手 + 响应封装);
> 视图层只决定「排序字段是哪个」;客户端把 `offset` 计数器换成 `next_cursor` 透传。
> **Global Constraints**:
> 1. `offset` **保留兼容**(老 APK 1.0.3 还在用):请求里带 `offset` 且不带 `before` 时走旧代码路径,响应形状也保持旧的 `count/next/previous/results`;
> 2. 新协议:请求 `?before=<不透明游标>`,响应 `{count, next_cursor, has_more, results}`(仍带 `count`,因为 App/Web 都用它算 `hasMore` 与角标);
> 3. 游标对客户端**不透明**(base64url),不要把 `<created_at>_<id>` 明文格式写进客户端逻辑 —— ISO 时间里的 `+08:00` 进 query 会被解成空格;
> 4. 非法游标一律 `400`(统一错误信封),不许漏成 500;
> 5. 不改 `docs/api/` 之外的门禁:接口文档只比对「方法 + 路径」,本次不新增接口。

## 验收命令

```bash
cd chatapp && python manage.py test feed discovery config   # 分页回归 + 查询预算
cd chatapp && python manage.py test                         # 全量(需 Redis)
cd app && ../flutter/bin/flutter.bat analyze && ../flutter/bin/flutter.bat test
cd web && npm run type-check && npm run lint && npm run test:run
```

## 任务

### Task 1 后端:游标基础设施
- [ ] `chatapp/config/cursor.py`:`encode_cursor(value, pk)` / `decode_cursor(raw)` /
      `read_before(request)` / `apply_before(qs, field, cursor)` / `wants_legacy_offset(request)` /
      `cursor_page(request, qs, field, limit_default, limit_max)`。
- [ ] 单测:编解码往返、非法值(`garbage` / 时间不合法 / id 非数字)抛 `InvalidCursor`、
      游标切片的边界(同一时间戳不同 id 不乱序)。
- 验证:`python manage.py test config`

### Task 2 后端:`/posts`、`/posts/mine`
- [ ] `feed/services.py::page_visible_posts(viewer, limit, before=None, offset=None)`:
      `before` 用 `(created_at, id) < (v, pk)` 元组比较;多取 1 条判断 `has_more`。
- [ ] `feed/views.py`:`_page_visible_posts` 与 `my_posts` 走 `cursor_page`,
      `offset` 请求走旧的 `DefaultLimitOffsetPagination` 路径(响应形状不变)。
- [ ] 回归测试:翻页期间插入新帖 → 第 2 页不重复、不漏读;`before` 走完 `has_more=false`;
      非法游标 400;`offset` 老路径仍返回 `count/next/previous`。
- 验证:`python manage.py test feed`

### Task 3 后端:`/matches`、`/discovery/likes`、`/discovery/visits`
- [ ] 三个视图各自声明排序字段(`Match.created_at`、`Swipe.created_at`、`ProfileVisit.last_at`),
      并补 `-id` 兜底排序(同秒插入时顺序稳定)。
- [ ] 同样的 `offset` 兼容分支。
- [ ] 回归测试:三处各一条「翻页期间插入 → 不重复不漏读」+ 非法游标 400。
- 验证:`python manage.py test discovery`

### Task 4 文档
- [ ] `docs/api/conventions.md` §分页约定:写清新旧两种模式与迁移建议。
- [ ] `docs/api/feed.md` §5.1/§5.3、`docs/api/discovery.md` §3.3/§3.4/§3.7:参数表 + 响应示例 + `curl` 示例。
- 验证:`python manage.py test config`(接口文档门禁)+ 人工通读。

### Task 5 App
- [ ] `core/api_client.dart::getAllPages`:响应带 `next_cursor` 就顺着它翻,否则退回 `offset`(通用)。
- [ ] `feed_repository.fetchPosts(cursor:)` → `(items, nextCursor)`;`square_controller` / `myPosts` 存 `nextCursor`。
- [ ] `discovery_repository.fetchLikesReceived/fetchVisits(cursor:)` → `(items, count, nextCursor)`;两个 controller 用 `nextCursor` 判 `hasMore`。
- [ ] 单测:翻页传的是 `before` 而不是 `offset`;`hasMore` 由 `next_cursor` 决定。
- 验证:`flutter analyze` 零告警 + `flutter test`

### Task 6 Web
- [ ] `api/types.ts` 新增 `CursorPage<T>`;`api/feed.ts`、`api/discovery.ts` 改 `cursor` 参数。
- [ ] `stores/feed.ts`、`stores/likes.ts`、`stores/visits.ts`、`stores/discovery.ts` 用 `next_cursor` 翻页。
- [ ] vitest:新增/改 4 条断言(传 `before`、`hasMore` 依据 `next_cursor`)。
- 验证:`npm run type-check && npm run lint && npm run test:run`

### Task 7 收尾
- [ ] backlog D-1 勾选 + 执行记录;`docs/milestones.md` 补一行;superpowers README 归档。
- [ ] 开 PR,CI 全绿后 squash 合并。

---

## 执行记录(2026-11-04)

**与计划的偏差**
1. **游标改成 base64url 不透明串**,而不是 backlog 原文的 `?before=<created_at>_<id>` 明文:ISO 时间里的 `+08:00` 进 query 会被解码成空格,`_` 分隔也会诱导客户端自己拼游标。代价是 curl 手测不能手写游标(先跑一次第一页拿 `next_cursor`)。
2. **`count` 保留**在游标响应里。原计划想省掉这次 `COUNT(*)`,但 App 的 `hasMore` 与 Web 的两个入口角标都依赖它,去掉会连带改 UI;深翻页的收益来自 keyset 本身,与 count 无关,所以原样保留。
3. **`/posts/mine` 一起改**(backlog 只点名 `/posts`):它和广场流是同一个两段式实现,不改会留下两条分页语义。
4. **`offset` 兼容不是临时开关而是双分支**:请求带 `offset` 且不带 `before` 时走老 `LimitOffsetPagination`,响应形状也回到 `count/next/previous/results`。老 APK 因此在翻页时不会卡在第 1 页(新代码一律游标)。
5. **`/matches` 补了 `-id` 兜底排序**:`Match.Meta.ordering` 只有 `-created_at`,同一条时间戳下的行顺序由 MySQL 决定,游标会漏行。

**踩到的坑**
- `feed/services.page_visible_posts` 原签名是 `(viewer, offset, limit)` 位置参数,改成 `(viewer, limit, *, before, offset)` 后,`feed/test_pagination.py` 里所有位置调用都要跟着改 —— 顺手把该文件扩成「游标 + offset 兼容」两套断言。
- App 的 `getAllPages` 首请求若直接带 `offset=0`,后端会判定为老客户端、永远走 offset 分支,`/matches` 就测不到游标。改成**首请求两个参数都不带**,靠响应里有没有 `next_cursor` 判断协议。
- `autoDispose` 的 Riverpod provider 在测试里 `read` 完会被回收,新写的分页单测必须先 `container.listen(...)` 才能断言 `loadMore` 之后的状态。

**验证**:后端 751 绿(`manage.py test`,含查询预算与接口文档门禁);App `analyze` 零告警 + 447 绿;Web `vue-tsc`/`eslint` 零告警 + 429 绿。

## 上线记录(2026-11-04)

`origin/master` = `ae7099f`(版本号 PR #51 把三处同改到 **1.0.4**),按发布流程部署:

| 项 | 动作 | 结果 |
|---|---|---|
| 后端 | `git checkout -f b5015bf` → `migrate --check` → `collectstatic` → 重启 `chatapp-web`/`chatapp-celery` | 无新迁移;health/readyz `200` |
| Web | 本地 `npm run build` → tar → 服务器解包 → `chown www:www` | 新 `assets/index-_l04JpFd.js`,旧包备份 `chatapp-web-dist-20261104-2032-preD1.tar.gz` |
| APK | `flutter build apk --release`(`ERROR_REPORTING=true`)→ `chatapp-1.0.4.apk`(MD5 `f202cc1b…`) | 断点下载 `206` |
| `.env` | 只改 `LATEST_APP_VERSION=1.0.4` + `APP_DOWNLOAD_URL` | `MIN_APP_VERSION` **保持 1.0.1**;`/app/config` 返回 1.0.4 |

生产冒烟(用 `SessionRefreshToken` 现场签一个令牌,`/tmp` 脚本跑完即删):游标模式 `{count, next_cursor, has_more, results}`、
第 2 页与第 1 页**零重叠**、`?offset=1` 仍是 `count/next/previous`、坏游标 `400 + 400`,
`/posts/mine`、`/matches`、`/discovery/likes`、`/discovery/visits` 四个接口全是新形状。

两个重启窗口(20:31 / 20:41)共 73 个 `502`,全部来自本机探针 `curl`(`/users/me` 与 `/app/config`),**无真实用户 5xx**。
回滚点:代码 `a08599b`、`.env.bak.20261104-2041-104`、旧 dist 备份(旧 APK 1.0.3 仍在服务器)。
