# D-5 可行性方案:OpenAPI 导出 + 客户端类型生成 + 门禁升级

- 日期：2026-11-08
- 状态：**可行性验证完成（含实测），待排期实现**
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
