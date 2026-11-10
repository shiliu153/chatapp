# 批次 S 实施计划:发现页筛选 + 每日精选

- **状态**:待实施
- **Spec 链接**:[批次 R–W 设计](../../specs/2026-11-09-batch-r-w-design.md) §4.2
- **Goal**:候选池支持**当场**按年龄/城市/标签筛选(不改设置里的偏好);新增「今日精选」——每天固定 N 张高匹配卡片,当天稳定、跨天自动换。
- **Architecture**:筛选是**查询参数**,不落库、不写回 `Preference`(设置页仍是唯一持久化入口)。候选池缓存键在**无筛选时保持原样**(默认路径命中率不退化),有筛选时追加筛选指纹分桶。「今日精选」复用同一套候选池与排除规则,种子 = `(日期, 用户 id)`,按「共同标签数 → 同城 → 随机」排序。
- **Global Constraints**:一单一条栈;改对外字段必须同改 `docs/api/discovery.md` + 重生成 `docs/api/openapi.yml`;
  新增 `.py` 补 docstring(`Args:`);App UI 走「心跳」token;不动版本号、不发版、不合并 PR。
- **验收命令**:`scripts/verify.sh backend` / `scripts/verify.sh app` / `scripts/verify.sh web`

---

## 现状(已核实)

| 已有 | 位置 | 复用方式 |
|---|---|---|
| 候选池查询(排除已划/已配对/拉黑/资料不全/无过审照片) | `discovery/services.py::candidate_pool_queryset` | 加一个可选的 `filters` 参数,**不要另写一份** |
| 池子缓存(键带用户版本 + 全局版本) | `discovery/services.py::candidate_pool_ids` | 无筛选保持原键;有筛选追加指纹 |
| 偏好过滤(性别/城市/年龄) | 同上 `preference.target_gender` / `.city` / `birthday_bounds` | 筛选参数**覆盖**偏好,缺省回落到偏好 |
| 参数校验工具 | `discovery/views.py::int_param` / `config/schema_helpers` | 复用,非法值统一 400 |
| 限流 | `CandidateThrottle` | 新接口用同款按用户限流 |
| 查询预算门禁 | `config/test_query_budget.py` | 新增/改动的查询必须仍达标 |

---

## Task 1 —— backend(先合,契约源头)

**改什么**

1. `discovery/services.py`:
   - 新增 `CandidateFilters`(dataclass):`age_min` / `age_max` / `city` / `tag_ids`,全部可空;
   - `candidate_pool_queryset(me, preference, pool_size, filters=None)`:
     `filters` 里非空字段**覆盖**对应偏好;`tag_ids` 用 `Exists(Profile.tags.through...)` 或
     `filter(tags__id__in=...).distinct()` —— **二选一按实测执行计划定**,禁止留下重复行;
   - `candidate_pool_ids(me, preference, pool_size, filters=None)`:
     缓存键 `disc:cand:{uid}:u{ver}:g{ver}:p{size}`,**filters 全空时一字不改**;
     有筛选时追加 `:f{指纹}`(指纹 = 排序后的 `age_min|age_max|city|tag_ids` 的 sha1 前 8 位)。
2. `discovery/views.py::candidates`:解析可选查询参数 `age_min` / `age_max` / `city` / `tag_ids`
   (逗号分隔整数),非法值 400;把 `CandidateFilters` 传给 `candidate_pool_ids`。
3. **新接口** `GET /api/v1/discovery/daily`(`?limit=6`,默认 6、上限 12):
   - 种子 `random.Random(f"{date.isoformat()}:{me.id}")`,当天稳定;
   - 候选来源 = 同一套候选池(可接受筛选参数,但**默认不带**);
   - 排序:共同标签数 desc → 同城优先 → 种子随机;**共同标签数用一条聚合查询算**(池子 ≤200 人);
   - 响应与 `candidates` **同构** + `date` 字段(客户端据此判断「今天已看过」)。
4. `docs/api/discovery.md` 补筛选参数表 + 新接口分册;重生成 `docs/api/openapi.yml`。

**验收口径**

1. `scripts/verify.sh backend` 全绿(含 `CommentCoverageTests` / `ApiDocsCoverageTests` / OpenAPI 生成物 / 查询预算)。
2. **无筛选时缓存键与改动前完全一致** —— 断言 `disc:cand:{uid}:u..:g..:p200` 存在(不能变成带 `:f` 的新键)。
3. 带 `city=杭州` → 返回的全是杭州;带 `age_min=25&age_max=30` → 年龄都在区间内;
   `tag_ids=1,2` → 每人至少有一个该标签;`age_min=40&age_max=20` → **400**。
4. `GET /discovery/daily` 同一天连续两次调用 → **结果完全相同**(顺序也相同);
   把日期 monkeypatch 成明天 → 结果变化(允许部分重合,但顺序/集合不完全相同)。
5. `daily` 不返回已划过/已配对/自己/无过审照片的人(与 `candidates` 同口径)。
6. `daily` 结果按共同标签数降序(构造两个候选,一个有 2 个共同标签、一个 0 个 → 前者在前)。
7. 查询预算:`candidates` 与 `daily` 都不超 `config/test_query_budget.py` 的预算(必要时给 `daily` 单独加一条)。

**禁止事项**:不把筛选写回 `Preference`;不改 `Preference` 模型/迁移;不改滑卡/配额逻辑;
不改 `docs/api/openapi.yml`(用 `manage.py spectacular` 生成);不新增业务码(非法参数走 400)。

---

## Task 2 —— app(依赖 Task 1 已合并)

**改什么**

1. 发现页(`app/lib/features/discovery/discovery_page.dart`)顶部加「筛选」入口 → 打开筛选面板
   (年龄区间滑块 + 城市输入 + 标签多选,底部「重置」/「应用」)。
2. 筛选态由 `discovery_controller.dart` 持有(内存态,**不写 shared_preferences**);
   应用后重新拉候选池。
3. 发现页顶部加「今日精选」卡:`GET /discovery/daily` 的 6 张卡横向滚动,
   点击进对方资料页,可「直接喜欢」。
4. 筛选/精选状态在页面切换后**不丢**(同一次 App 生命周期内)。

**验收口径**

1. `scripts/verify.sh app` 全绿(`flutter analyze` 零告警 + 全部测试)。
2. 新增测试:筛选面板默认值 = 当前偏好;应用后请求带上了参数;重置后回到偏好;
   `daily` 渲染 6 张卡;空态(候选池空)不崩。
3. `no_raw_colors_test.dart` 与 `dark_mode_sweep_test.dart` 仍绿。
4. **模拟器逐页手测**(`emulator-5554`):发现页 → 筛选 → 只选城市「杭州」→ 应用 → 卡片全是杭州 →
   重置 → 恢复;今日精选 6 张可滚动、可点进资料页。截图贴 PR 正文。
5. **PR 必须开 draft**,正文写「等待模拟器验收」。

**禁止事项**:不写回偏好;不新引依赖;不改滑卡手势逻辑;不碰 `flutter/`。

---

## Task 3 —— web(依赖 Task 1 已合并)

**改什么**

1. `web/src/features/discovery/`:发现页顶部「筛选」按钮 → 面板(年龄区间 + 城市 + 标签多选);
   筛选态进 `stores/discovery.ts`(内存,不写 localStorage)。
2. 「今日精选」区块:6 张卡横向排列,点击进资料页。
3. 页面只碰 store,不直接调 `http`。

**验收口径**

1. `scripts/verify.sh web` 全绿(`vue-tsc` 零错误 + `eslint --max-warnings 0` + vitest 覆盖率门槛)。
2. 组件/store 测试:筛选参数正确拼进请求;重置回到偏好;精选渲染与空态。
3. `no-raw-color.spec.ts` / `tokens.spec.ts` 仍绿;`npm run build` 通过。

**禁止事项**:不写回偏好;不手改 `schema.d.ts`;不改 `tokens.css` 既有变量值;页面不直接调 `http`。

---

## 执行记录

(交付时回填)
