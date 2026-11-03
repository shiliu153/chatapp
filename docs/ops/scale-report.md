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

## 6. 社交列表:三条索引 + `NOT EXISTS`(2026-11-03,A-2)

「喜欢我的人 / 谁看过我 / 配对列表」三个接口此前有三处结构性劣化(审查 N-2/N-3/N-4):
`Swipe` 的 `target`、`Match` 的 `user_b` 都不是任何索引的前导列;`Photo` 的 `status` 没有索引
(候选池 / 喜欢我 / 访客三处共用的「有已过审照片的人」子查询因此全表扫);
排除列表又是「先把 id 拉进 Python 再 `__in`」,SQL 随活跃度线性变长。

**实测口径**:20,052 用户 / 20,068 照片(三成待审)/ 20,033 条滑卡(15% 是 like)/
20,000 条访客 / 10,050 条配对(九成已解除),MySQL 8.0.42,开发机,
`manage.py scale_probe --phone <探针号> --explain`,取 15 次中位数(前 3 次预热)。

| 查询 | 改动前 | 改动后 | 变化 |
|---|---|---|---|
| `likes_received`(前 20 条) | 95.72 ms,`ref` on `target_id`,rows 10098 + **filesort** | **32.02 ms**,`ref` on `idx_swipe_target_action`,rows 3000,无 filesort | −67% |
| `likes/count` | 92.04 ms | **29.83 ms** | −68% |
| `visits`(前 20 条) | 371.65 ms,**`type=ALL`** on `users_photo` rows 19576 + temporary + filesort | **105.0 ms**,`ref` on `idx_visit_owner_last`;照片子查询不再全表扫 | −72% |
| `matches`(前 20 条) | 2.01 ms,`ref` on `unmatched_at` rows 2000 | **1.74 ms**,`index_merge(uniq_match_pair, idx_match_user_b)` rows 101 | 扫行数 −95% |

三条索引:

| 表 | 索引 | 服务于 |
|---|---|---|
| `discovery_swipe` | `(target_id, action, created_at DESC, id DESC)` | 喜欢我的人:等值 + 排序一索引搞定 |
| `discovery_match` | `(user_b_id, unmatched_at)` | 配对列表的 OR:与 `uniq_match_pair` 组成 index_merge |
| `users_photo` | `(status, user_id)` | 三处共用的「有已过审照片的人」覆盖索引 |

两个容易踩的点(都实测过):

1. **MySQL 8 会把「被新索引左前缀覆盖」的外键索引当冗余删掉**:加了
   `idx_swipe_target_action` 之后,`target_id` 的独立外键索引消失(配对表同理)。
   所以「先加索引、后想回滚」时,`DROP INDEX` 会报 1553 —— 得先补一条单列索引;
   线上回滚同理,别指望 `migrate` 反向操作一定干净。
2. **拉黑过滤必须拆成两条 `EXISTS`**:一条带 `OR` 的 `EXISTS` 用不了半连接,
   MySQL 会把外层行整体物化进临时表 —— 2 万访客上实测 **565 ms**,拆成两条 **103 ms**
   (与完全不加拉黑过滤同价)。另外 `exclude(a, b)` 在 Django 里是 `NOT (a AND b)`,
   写成一次调用只会剔除「双向都拉黑」的行,单方向拉黑会漏 —— 这条已被
   `moderation/tests.py::BlockVisibilityTests` 钉死。

`/matches` 顺带修掉了「把全部配对行拉进内存再分页」:现在先 `LIMIT/OFFSET` 再组装,
翻到第 2 页和第 1 页一样贵;头像绝对 URL 仍在序列化阶段按请求拼。

## 7. 复现

```bash
# 1) 造数(开发库/测试库都行;--clean 只删 199 号段)
python manage.py seed_scale_users --count 100000 --posts 500000

# 2) 量延迟与执行计划
#    --phone 指定探针账号(要看「喜欢我/谁看过我/配对」的规模数据,得让它有对应的行)
python manage.py scale_probe --repeat 5 --offsets 0,1000,10000,50000 --explain --phone <手机号>

# 3) 压接口:只读接口直接压;写接口(需要登录态)用 perf_tokens 签令牌后压
python3 perf/run.py --scenario api_read --conns 100 --dur 30 --out perf/results/feed.json
#    python manage.py perf_tokens --count 50 --out ../perf/results/headers.jsonl
#    python3 perf/run.py --scenario api_write --path /api/v1/discovery/swipe \
#      --body '{"target_user_id": {i}, "action": "like"}' --i-start <首个目标 id> \
#      --headers-file perf/results/headers.jsonl --conns 50 --dur 30
#    写场景的口径与坑见 perf/README.md §2.2

# 4) 清理
python manage.py seed_scale_users --count 100000 --clean
```

## 8. 局限

- 开发机(Windows + 本地 MySQL)与 2C2G 服务器的 IO 特性不同,**绝对值不可直接搬到线上**;
  可迁移的是「查询形态 + 执行计划 + 相对倍数」。
- 造的是「资料完善 + 一张过审照片」的理想分布;真实数据里会有大量未完善账号,
  候选池的过滤成本会更高,需要上线后用真实分布复测。
- 没有造点赞/评论,聚合成本被低估(真实场景 `COUNT(DISTINCT)` 的基数更大)。
