# 规模数据报告:10 万用户量级下的查询表现(2026-11-03)

> 口径说明:本文全部基于**合成数据**(`seed_scale_users` 造的账号/资料/照片/动态),
> 不代表真实 DAU。目的只有一个:验证「数据涨到 10 万级后,接口还撑不撑得住」。
> 复现命令见 §6。

## 0. 结论速览

| 接口 | 修复前 | 修复后 | 主要手段 |
|---|---|---|---|
| 广场列表 offset=0 | **3354 ms** | **77 ms** | 两段式分页(先取当页 id,再只对 10 条聚合) |
| 广场列表 offset=50000 | 3521 ms | 163 ms | 同上 + `(created_at,id)` 索引 + 去掉 LEFT JOIN |
| 候选池(200 条) | 12–22 ms | 12–22 ms | 已走 `shuffle_key` 索引,无需改 |

10 万条动态下单次广场请求从 **3.3 秒降到 77 毫秒(约 43 倍)**;
但剩下的 77ms 里 `COUNT(*)` 占 45ms、深翻页的 OFFSET 跳读占 106ms —— 见 §4。

## 1. 造数

```bash
python manage.py seed_scale_users --count 20000 --posts 100000
# 账号:20000  资料:18000  照片:18000  动态:100000  耗时 12.1s
```

按线性外推,10 万用户 + 50 万动态约 **1 分钟**。命令幂等(`ignore_conflicts`),
`--clean` 只删 `199` 号段,不碰真实数据;`--dry-run` 只打印计划。

> 聊天消息没有造:`im_message` 在独立的 `chatapp_im` 库(imserver 自建),
> Django 没有它的连接。消息量用 `imserver/scripts/bench_ws.py` 现场产生。

## 2. 发现一:广场列表是 O(全表) 的

修复前 `visible_posts(viewer)[offset:offset+limit]` 的 SQL 形态是:

```sql
SELECT ..., COUNT(DISTINCT like.id), COUNT(DISTINCT comment.id), EXISTS(...)
FROM feed_post LEFT JOIN ... GROUP BY feed_post.id
ORDER BY created_at DESC, id DESC LIMIT 10 OFFSET 0;
```

MySQL 必须先把**全部 10 万行**分组、算完两个 `COUNT(DISTINCT)` 才能 LIMIT。
EXPLAIN 显示 `Table scan on feed_post (rows=104805)` + `Sort row IDs`。
10.5 万条时单请求 3.35 秒,而且**与 offset 无关**——offset 0 和 50000 一样慢,
说明瓶颈在聚合,不在翻页。

## 3. 修复:两段式分页 + 索引 + 去 JOIN

1. **两段式**(`feed/services.py::page_visible_posts`):先用轻量查询取当页 10 个 id,
   再 `visible_posts().filter(pk__in=ids)` 只对这 10 条做聚合。聚合成本与总数据量脱钩。
2. **索引**(`feed/migrations/0005`):`Post.Meta.indexes` 加 `(-created_at, -id)`。
   没有它,取 id 这一步也是全表扫 + filesort。
3. **去 LEFT JOIN**(`visible_base`):原来用 `exclude(author__profile__status=BANNED_HEAVY)`,
   生成 LEFT JOIN,MySQL 优化器因此**放弃索引**改走全表扫(实测加索引后仍然全扫)。
   改成 `exclude(author_id__in=Profile.objects.filter(status=BANNED_HEAVY).values("user_id"))`
   的 NOT IN 子查询后,计划变成 `Index scan on feed_post using post_feed_order_idx`。

> 这一步是最反直觉的:**加了索引不等于用得上**。判断依据只能是 EXPLAIN,
> 不能看「我加过索引」。

## 4. 剩下的 77ms 花在哪(未修,列为下一步)

105,010 条动态、MySQL 8、开发机实测:

| 组成 | 耗时 | 说明 |
|---|---|---|
| `COUNT(*)`(可见总数) | 45 ms | 接口契约要返回 `count`,必须扫全表 |
| 取当页 id(offset 0) | 12 ms | 走索引,冷启动首次 |
| 取当页 id(offset 50000) | 106 ms | OFFSET 要跳过 5 万条索引项 |
| 对 10 条做聚合 | 18 ms | 两次 `COUNT(DISTINCT)` + `EXISTS` |

两条后续路线:

1. **count 缓存**(低成本):`feed:count:{viewer}` + 10 秒 TTL,发帖/删帖升版本。
   预计 offset 0 从 77ms → 30ms 左右。
2. **keyset 分页**(要改契约):`?before=<created_at,id>` 替代 `offset`,
   深翻页从 106ms → 与页深无关。代价是 App/Web/接口文档三端同步改,
   且前端「跳页」能力丢失 —— 广场是无限滚动,实际上用不到跳页,值得做,但要单独立项。

## 5. 候选池:已经是健康的

20,051 个资料完善账号下,`candidate_pool_queryset` 冷查 **12–22 ms**,
EXPLAIN 显示 `Index scan on users_profile using users_profile_shuffle_key` +
对照片表的 semijoin。这就是 2026-10-28 M7 把 `ORDER BY RAND()` 换成
`shuffle_key` 预计算列的效果——**不需要再改**。

## 6. 复现

```bash
# 1) 造数(开发库/测试库都行;--clean 只删 199 号段)
python manage.py seed_scale_users --count 100000 --posts 500000

# 2) 量延迟与执行计划
python manage.py scale_probe --repeat 5 --offsets 0,1000,10000,50000 --explain

# 3) 压接口(需要登录态,当前 perf/run.py 只支持公开接口)
python3 perf/run.py --scenario api_read --conns 100 --dur 30 --out perf/results/feed.json

# 4) 清理
python manage.py seed_scale_users --count 100000 --clean
```

## 7. 局限

- 开发机(Windows + 本地 MySQL)与 2C2G 服务器的 IO 特性不同,**绝对值不可直接搬到线上**;
  可迁移的是「查询形态 + 执行计划 + 相对倍数」。
- 造的是「资料完善 + 一张过审照片」的理想分布;真实数据里会有大量未完善账号,
  候选池的过滤成本会更高,需要上线后用真实分布复测。
- 没有造点赞/评论,聚合成本被低估(真实场景 `COUNT(DISTINCT)` 的基数更大)。
