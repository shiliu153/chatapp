# D-5 可行性方案:OpenAPI 导出 + 客户端类型生成 + 门禁升级

- 日期：2026-11-08
- 状态：**三步已全部实现（2026-11-04 落地）**
- 依据：[backlog D-5](../backlog/2026-11-03-todo.md)、[fullstack review §四 D-1](../reviews/2026-11-03-fullstack-review.md)
- 结论先行：**能落地，但不是「装个库就有」**。自动导出只能拿到「路径 + 方法」这一层（实测 39 paths / 47 operations / **只有 1 个 schema 组件**），
  要到**字段级**必须逐个接口写 `@extend_schema`；因此建议**分三步走**，每步都能独立交付、独立生效。

## 0. 实测结论（2026-11-08，本地 Django 5.2 + DRF 3.15）

用 `drf-spectacular 0.30` 在**不改任何业务代码**的前提下跑了一遍 `SchemaGenerator`：

| 指标 | 结果 |
|---|---|
| OpenAPI 版本 | 3.0.3 |
| 自动识别的路径 | **39** |
| 自动识别的操作（方法数） | **47** |
| 自动生成的 schema 组件 | **1**（其余全部缺失） |
| 阻塞性报错 | `unable to guess serializer` —— feed / users / moderation / accounts 等**函数视图**全覆盖 |
| 认证解析 | `could not resolve authenticator SessionJwtAuthentication`（需要一个 10 行的 `OpenApiAuthenticationExtension`） |
| 其他 | `operationId "posts_retrieve"` 冲突（`/posts` 与 `/posts/{post_id}` 都叫 retrieve） |

**根因**：本项目几乎全是 `@api_view` 函数视图（`def candidates(request):`），serializer 是在函数体里临时构造的，
spectacular 无从推断请求体/响应体。这不是配置问题，**是视图写法的必然结果**。

## 1. 选型

| 方案 | 结论 | 理由 |
|---|---|---|
| **drf-spectacular** | ✅ **选它** | OpenAPI 3.0、活跃维护、对 `@api_view` 支持靠 `@extend_schema`（正是我们要的「显式契约」）、能输出可校验的 `schema.yml` |
| drf-yasg | ❌ | Swagger 2.0，官方已进入维护模式，与 OpenAPI 3 的 nullable/oneOf 语义不兼容 |
| 手写 schema | ❌ | 47 个操作手写 YAML，等于再造一份文档，且必然与代码漂移 |
| 只从序列化器反射（不引入库） | ⚠️ 备选 | 能做到「字段级门禁」的 80%（`Serializer.get_fields()` 已经够用），但拿不到 `paths`/参数/错误码；**可作为第一步的降级方案** |

## 2. 迁移路径（三步，每步可独立上线）

### 第 1 步：让 schema「存在且不报错」（0.5 天）

1. `chatapp/requirements.txt` 加 `drf-spectacular>=0.27`；
2. `INSTALLED_APPS` 加 `drf_spectacular`，`REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"] = "drf_spectacular.openapi.AutoSchema"`；
3. 新增 `chatapp/config/schema.py`：`SessionJwtAuthentication` 的 `OpenApiAuthenticationExtension`（10 行）+ `SPECTACULAR_SETTINGS`
   （title / version / `SERVE_INCLUDE_SCHEMA=False`）；
4. `manage.py spectacular --file docs/api/openapi.yml --validate` 能跑通（此时字段仍然空，但 **paths/methods/参数** 已经可用）。

**验收**：命令退出码 0；`openapi.yml` 里 47 个操作齐全；CI 加一步「schema 能生成」。

### 第 2 步：把「路径门禁」升级成「字段门禁」（1.5–2 天）

现状：`ApiDocsCoverageTests` 只比对**方法 + 路径**（`docs/api/*.md` 的表格 vs `urls.py`）。
升级后：**字段级双向比对**，任一侧改了字段名就变红。

实现要点：

- 给 47 个操作逐个加 `@extend_schema(request=..., responses=...)`。**大部分 serializer 已经存在**
  （`CandidateSerializer`、`SwipeSerializer`、`PostSerializer`…），主要是把「函数体里临时构造」搬到装饰器上；
  纯字典响应的（如 `/app/config`、`/im/user_sig`）用 `inline_serializer` 或 `OpenApiTypes.OBJECT` + `examples`。
- 新增 `chatapp/config/test_schema_contract.py`：
  1. 生成 schema（进程内，不落盘）；
  2. 解析 `docs/api/*.md` 的「响应参数 / 请求参数」表格；
  3. 双向断言：markdown 有的字段 schema 必须有，schema 有的字段 markdown 必须有（`request_id` 等信封字段白名单排除）。
- **故意改一个字段名 → 门禁变红**：把 `SwipeSerializer.target_user_id` 改名，`test_schema_contract` 必须报错（写进用例做自测）。

**工作量分布**：`accounts`(5) / `users`(9) / `discovery`(7) / `matches`(2) / `feed`(9) / `im`(3) / `moderation`(4) / 其他(8)。
按每个 10–15 分钟估：**6–10 小时**（这是 D-5 的主要成本，不是库本身）。

### 第 3 步：客户端类型生成 + 版本号单一来源（1–1.5 天）

| 端 | 做法 | 风险 |
|---|---|---|
| **Web（TS）** | dev 依赖加 `openapi-typescript`，`npm run gen:api` 从 `openapi.yml` 生成 `web/src/api/schema.d.ts`（**只生成类型，不生成请求代码**）；`api/*.ts` 的返回类型改成 `components['schemas']['Xxx']` | 低：类型文件是纯类型，运行时不引入任何东西 |
| **App（Dart）** | **先不生成模型代码**（`openapi_generator` 要 build_runner + 会重写现有手写模型，风险大）；改为生成一份**契约测试**：`test/api_contract_test.dart` 断言 App 侧模型字段名 ⊆ schema 字段名 | 中：需要先有第 2 步的字段级 schema |
| **版本号** | 新增 `scripts/sync_version.py`：以 `app/pubspec.yaml` 的 `version:` 为**唯一来源**，`--check` 校验 `app/lib/core/app_info.dart` 与 `web/package.json` 一致，`--write` 自动改；CI 加 `--check` | 低：纯脚本 + CI 一步 |

**为什么 Dart 不生成代码**：现有 `lib/im/`、`lib/features/*/models` 都是手写 + 有大量业务方法（`copyWith`、枚举映射、`fromJson` 容错），
生成器产出的是纯数据类，替换成本远高于收益；而「字段名对不上」才是真正会出的事故，用契约测试覆盖即可。

## 3. 门禁改造（和现状的关系）

| 门禁 | 现在 | D-5 之后 |
|---|---|---|
| 接口文档覆盖 | `ApiDocsCoverageTests`：方法 + 路径双向比对 | **字段级**双向比对（schema ↔ markdown），方法+路径仍是子集 |
| 客户端一致性 | 无（靠人） | Web 类型由 schema 生成（编译期）；App 由契约测试（CI） |
| 版本号 | 三处手改（pubspec / app_info / package.json） | `sync_version.py --check` 进 CI，漏改即红 |
| 人读文档 | `docs/api/*.md` | **保持不变**（仍是交付物），schema 只是生成物（`docs/api/openapi.yml`，只读、由 CI 校验是否与代码一致） |

## 4. 风险与取舍

| 风险 | 缓解 |
|---|---|
| 47 个接口逐个加注解，容易漏 | 门禁双向比对会立刻暴露漏掉的；先做「字段级」再做「示例」，示例可以不生成 |
| `@extend_schema` 写错导致 schema 与真实响应不符 | 每个 app 挑 1–2 个接口用**真实响应**做 fixture 比对（已有 `docs/api` 的响应示例可复用） |
| 生成物进 git 导致 diff 噪音 | `openapi.yml` 只在 CI 里「重新生成 + 比对」，不要求本地提交（或提交但 `--check` 保证同步） |
| 增加一个依赖 | drf-spectacular 是纯 Python、无编译依赖，CI 已装 `packaging`/`jsonschema` 类库，风险可控 |

## 5. 工作量与排期建议

| 步骤 | 工作量 | 交付物 |
|---|---|---|
| 第 1 步：schema 能生成 | 0.5 天 | `config/schema.py` + CI 一步 |
| 第 2 步：47 个操作加注解 + 字段级门禁 | 1.5–2 天 | `test_schema_contract.py` + `openapi.yml` |
| 第 3 步：Web 类型生成 + App 契约测试 + 版本脚本 | 1–1.5 天 | `schema.d.ts`、`api_contract_test.dart`、`sync_version.py` |
| **合计** | **3–4 天**（与 backlog 的 3~5 天估相符） | |

**建议顺序**：第 1 步单独一个 PR（零风险，先把管道打通）→ 第 2 步按 app 拆 3–4 个 PR（每个 PR 只碰一个 app 的注解）→
第 3 步一个 PR。**不要一次性 47 个接口一起改**，review 成本会爆炸。

## 6. 明确不做的事

- ❌ **不用生成器替换现有手写客户端模型**（Dart 端）：收益低、风险高，用契约测试覆盖字段名即可。
- ❌ **不自动生成请求代码**（TS 端）：现在 `api/*.ts` 里有一层错误处理/刷新/游标分页逻辑，生成器不会替我们写这些。
- ❌ **不把 `docs/api/*.md` 换成生成文档**：它是人读的交付物，schema 是机器读的契约，两者并存。
- ❌ 不在本轮动 `imserver` 的 `/im/api/*`：它不属于 `/api/v1`，门禁范围不变（见 `docs/api/README.md` 的口径说明）。

## 7. 落地记录（2026-11-04，第 1、2 步）

### 第 1 步（已完成）

| 项 | 落地内容 |
|---|---|
| 依赖 | `requirements.txt` 加 `drf-spectacular>=0.30`；`requirements.lock` 同步补 8 个包（drf-spectacular / inflection / jsonschema / jsonschema-specifications / referencing / rpds-py / attrs / PyYAML / uritemplate） |
| 配置 | `INSTALLED_APPS` 加 `drf_spectacular`；`REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"]`；`SPECTACULAR_SETTINGS`（只导出 `/api/v1`、请求/响应组件拆分、稳定排序、枚举名覆盖） |
| 认证扩展 | `chatapp/accounts/schema.py`（**不是计划里的 `config/schema.py`**：扩展的目标类在 accounts，drf-spectacular 靠「被导入」注册，所以放在 `accounts/schema.py` 并由 `AccountsConfig.ready()` 导入，比 `config` 反向依赖 accounts 干净） |
| 版本号 | `SPECTACULAR_SETTINGS["VERSION"]` 直接读 `app/pubspec.yaml`（不再多一处手写版本号） |
| 生成物 | `docs/api/openapi.yml`（39 paths / 47 operations / 66 components，openapi 3.0.3） |
| 门禁 | `config/tests.py::OpenApiSchemaTests` 校验「schema 操作集合 == URLconf 操作集合」；CI 重新生成后 `git diff --exit-code`（`backend.yml`，并把 `docs/api/**` 加入触发路径） |
| 细节 | `.gitattributes` 固定 `docs/api/openapi.yml` 为 LF，否则 Windows 检出成 CRLF 会让本地每次生成都变成整文件 diff |

### 第 2 步（已完成）

- **47 个操作全部补了 `@extend_schema`**（按 app 分批改：accounts 6 / users 10 / discovery 8 / im 4 / moderation 4 / feed 12 / 其他 3）。
  复用件集中在新模块 `config/schema_helpers.py`：`cursor_page` / `offset_page` / `cursor_params` / `offset_params`。
- **字段级双向门禁**：`config/api_schema_contract.py`（解析 + 比对）+ `config/test_schema_contract.py`（断言 + 自测）。
  解析规则：只比**顶层字段**；「请求参数」表里混写的路径参数算请求字段；「响应参数」只取标记后的**第一张**表
  （`users.md §2.1` 后面的 `tags[]` / `photos[]` 子表不算顶层）；分页信封解到 `results[]` 条目。
- **文档侧配套**：
  - 新增「`同 [X.Y 标题]`」引用约定（6 处：`/posts`、`/posts/mine`、`/posts/{id}`、`replies`、`PATCH /users/me`、`PATCH /users/me/preference`、`POST /blocks`），
    避免同一张字段表复制 3 份；约定写进 `docs/api/README.md` §维护规则 5/6。
  - `health.md` 给 `/health` 补了响应参数表（原来只有示例）。
  - `README.md` 接口一览补上漏记的 `POST /auth/logout`（46 → 47）。
- **唯一的 schema 表达不了的东西**：`DELETE /users/me` 的请求体 `phone`。OpenAPI 3.0 没有定义 DELETE body，
  drf-spectacular 直接丢弃（`_get_request_body`：只有 PUT/PATCH/POST 能有 body），因此在
  `api_schema_contract.py::SCHEMA_INEXPRESSIBLE` 里显式豁免，并用单测锁死「豁免只允许 DELETE」。
- **验证**：`python manage.py spectacular --file ../docs/api/openapi.yml --validate` 退出码 0 且**零 error / 零 warning**；
  后端 **725** 测试绿；`python config/comment_coverage.py` 无缺口；`find_problems()` 返回 `[]`。

### 第 3 步（已完成）

| 端 | 落地内容 | 门禁 |
|---|---|---|
| **Web（TS）** | `web/src/api/schema.d.ts`（openapi-typescript 7.13.0 生成，2854 行纯类型）；`npm run gen:api` 用**固定版本**的 `npx --yes openapi-typescript@7.13.0`（`openapi-typescript@7` 的 peer 是 `typescript@^5`，而本项目用 TS 6，直接装 devDependency 会让 `npm ci` 因 peer 冲突失败；用 npx 固定版本既不污染依赖图又可复现）；`eslint` 忽略生成物 | `web.yml`：`npm run gen:api` + `git diff --exit-code` |
| **Web 契约断言** | `web/src/api/contract.ts`：13 个手写接口做**字段名 ⊆ schema 字段名**的编译期断言（`Exclude<keyof 手写, keyof schema>` 必须是 `never`）。**只做单向**（手写 → schema）：后端新增字段对前端向后兼容，不该把 CI 卡红 | `npm run type-check`（已验证：把 `Post.images` 改名 → `error TS2344`） |
| **App（Dart）** | 仍**不生成模型**；改为 `scripts/check_app_models.py` 静态扫描 `app/lib/features/**/models.dart` 里所有 `json['...']` 键，断言 ⊆ `openapi.yml` 的字段全集（82 个）。用 Python 扫描而不是 Dart 测试：Dart 没有 YAML 解析器，而为一次检查引入代码生成不划算 | 新 workflow `contract.yml`（`app/lib/**`、`docs/api/**` 等路径触发，秒级） |
| **版本号** | `scripts/sync_version.py`：以 `app/pubspec.yaml` 为唯一来源，`--check` 校验 `app/lib/core/app_info.dart` + `web/package.json`，`--write` 写回；配 7 条 unittest | `contract.yml`：`--check` + 脚本自测 |

**顺带修掉的 schema 精度问题**：`GET /presence` 的 `results[]` 原来用 `DictField` 兜底，`online` / `last_active_at` 根本没进 schema（App 模型正好读这两个键）；改成 `inline_serializer` 后字段可见，App 契约检查才有意义。

**验证**：Web `type-check` 零错误 / `lint` 零告警 / **406** 单测绿；后端 **725** 绿；`scripts.test_sync_version` **7** 条绿；
`check_app_models.py` 通过（故意把 `avatar_url` 改成 `avatar` → 退出码 1，已回滚验证）。
