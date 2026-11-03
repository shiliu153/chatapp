# 接口文档体系设计(腾讯云风格)

日期:2026-09-21
状态:已与用户逐节确认(见 §9 决策记录),待用户终审
上游:CLAUDE.md「核心契约与纪律」(错误契约 / 鉴权 / 分页 / 封禁);`config/exceptions.py`(错误信封)、`config/error_codes.py`(业务码)、`config/pagination.py`(分页)、`config/api_urls.py`(接口全集)
背景:用户提出「补充所有接口文档,腾讯风格,保存至 docs 新建文件夹,并且之后每次新增接口之后都需补充接口文档」。经逐节确认:用途 = 对外交付级;范围 = `/api/v1` 全部 + 运维探针(ops 运营台不写);组织 = 按业务模块分册;同步保障 = CLAUDE.md 纪律条目 + 自动检查测试。

## 1. 目标与范围

**目标**:`docs/api/` 成为本项目接口的**对外交付级**文档——每个接口含完整参数表与请求/响应示例,格式对齐腾讯云官网单接口页结构;并建立「新增接口必同步补文档」的机器强制机制。

**范围**:全部 `/api/v1` 接口,共 **32 个「方法+路径」组合**(清单见 §2),含运维探针 `/health`、`/readyz`。

**非目标(YAGNI)**:ops 运营台与 Django admin 的表单接口;一接口一独立文件;从代码自动生成文档(字段说明/业务规则无法自动生成,自动生成的骨架反而要人工重写);文档站点在线托管;英文版;每个接口的「最近更新时间」标注(以 git 历史为准)。

## 2. 目录结构(新建 `docs/api/`,10 个文件)

| 文件 | 内容 | 接口数 |
|---|---|---|
| `README.md` | 接口总览:调用方式入口、全量接口一览表(32 个 + 一句话描述 + 分册链接)、文档维护规则与模板说明 | — |
| `conventions.md` | 公共说明(内容清单见 §4) | — |
| `errors.md` | 错误码总表(内容见 §5) | — |
| `auth.md` | 账号与鉴权 | 3 |
| `users.md` | 用户资料 / 照片 / 偏好 / 标签 / 他人资料 / 在线状态 | 9 |
| `discovery.md` | 发现与配对 | 3 |
| `im.md` | IM 会话凭证 | 1 |
| `moderation.md` | 举报与拉黑 | 4 |
| `feed.md` | 广场动态 | 10 |
| `health.md` | 运维探针(独立一节,简版格式) | 2 |

**接口清单(写作与检查的权威列表,路径参数以 `{name}` 记)**:

| # | 接口 | 分册 |
|---|---|---|
| 1 | POST `/api/v1/auth/sms/send` | auth |
| 2 | POST `/api/v1/auth/sms/verify` | auth |
| 3 | POST `/api/v1/auth/token/refresh` | auth |
| 4 | GET `/api/v1/users/me` | users |
| 5 | PATCH `/api/v1/users/me` | users |
| 6 | GET `/api/v1/users/tags` | users |
| 7 | POST `/api/v1/users/me/photos` | users |
| 8 | DELETE `/api/v1/users/me/photos/{photo_id}` | users |
| 9 | GET `/api/v1/users/me/preference` | users |
| 10 | PATCH `/api/v1/users/me/preference` | users |
| 11 | GET `/api/v1/users/{user_id}` | users |
| 12 | GET `/api/v1/presence` | users |
| 13 | GET `/api/v1/discovery/candidates` | discovery |
| 14 | POST `/api/v1/discovery/swipe` | discovery |
| 15 | GET `/api/v1/matches` | discovery |
| 16 | POST `/api/v1/im/user_sig` | im |
| 17 | POST `/api/v1/reports` | moderation |
| 18 | GET `/api/v1/blocks` | moderation |
| 19 | POST `/api/v1/blocks` | moderation |
| 20 | DELETE `/api/v1/blocks/{user_id}` | moderation |
| 21 | GET `/api/v1/posts` | feed |
| 22 | POST `/api/v1/posts` | feed |
| 23 | GET `/api/v1/posts/mine` | feed |
| 24 | GET `/api/v1/posts/{post_id}` | feed |
| 25 | DELETE `/api/v1/posts/{post_id}` | feed |
| 26 | POST `/api/v1/posts/{post_id}/like` | feed |
| 27 | DELETE `/api/v1/posts/{post_id}/like` | feed |
| 28 | GET `/api/v1/posts/{post_id}/comments` | feed |
| 29 | POST `/api/v1/posts/{post_id}/comments` | feed |
| 30 | POST `/api/v1/posts/{post_id}/report` | feed |
| 31 | GET `/api/v1/health` | health |
| 32 | GET `/api/v1/readyz` | health |

## 3. 单接口页面模板(腾讯云单页结构,7 元素)

每个接口一个 `###` 小节,顺序固定:

1. **标题**:`### <序号> <中文接口名>`
2. **信息行(强制格式)**:`> \`方法\` \`/api/v1/路径\` · <鉴权要求> · <限流规则>` —— 既是给读者的速览,也是 §6 自动检查机器可读标记
3. **接口描述**:一段话,含业务规则(有效期、幂等、拉黑/封禁表现、排序等)
4. **请求参数**表:`参数名称 | 必填 | 类型 | 描述`
5. **响应参数**表:`参数名称 | 类型 | 描述`
6. **请求示例**(curl)+ **响应示例**(成功 1 个 + 典型失败 1 个,JSON)
7. **错误码**表:`错误码 | HTTP | 描述 | 处理建议`(只列该接口会出现的;全局 401/403/500 在 `conventions.md`/`errors.md` 统一说明)

**样例(实际文档即长这样)**:

```markdown
### 1.1 发送短信验证码

> `POST` `/api/v1/auth/sms/send` · 无需鉴权 · 限流 20 次/小时(按 IP)

**接口描述**

向指定手机号下发 6 位短信验证码,有效期 5 分钟。同一手机号 60 秒内只能发送一次;
连续校验错误 5 次锁定 15 分钟。

**请求参数**(Body,`application/json`)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| phone | 是 | String | 中国大陆手机号,11 位数字 |

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| status | String | 固定为 `"ok"`,表示已受理(不代表已送达) |

**请求示例**

```bash
curl -X POST http://<域名>/api/v1/auth/sms/send \
  -H "Content-Type: application/json" \
  -d '{"phone": "13800000001"}'
```

**响应示例**

```json
{ "status": "ok" }
```

```json
{ "code": 42901, "message": "发送太频繁,请稍后再试", "request_id": "d3f1a2…" }
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 42901 | 429 | 重发间隔未到 | 按响应头 `Retry-After` 等待后重试 |
| 50301 | 503 | 短信任务入队失败 | 稍后重试 |
```

样例中的 message 文案为真实值(取自 `accounts/exceptions.py`);写文档时一律以实际响应为准,不美化、不臆造。

`health.md` 两接口为运维用途,用简化格式:信息行 + 描述 + 响应示例 + 各状态码含义(不要求参数表)。

## 4. `conventions.md` 内容清单

1. **Base URL**:`http://<域名>/api/v1`;当前测试环境 `http://<SERVER_IP>/api/v1`,本机开发 `http://127.0.0.1:8000/api/v1`(Android 模拟器用 `http://10.0.2.2:8000/api/v1`);HTTPS 待域名备案后启用
2. **请求约定**:方法语义(GET 查询 / POST 创建 / PATCH 局部更新 / DELETE 删除);`Content-Type: application/json`;文件上传 `multipart/form-data`
3. **鉴权**:`Authorization: Bearer <access>`;access 30 分钟 / refresh 30 天,刷新即轮换、旧 refresh 进黑名单;**单设备登录**(被顶设备收 401 + `40101`)
4. **统一响应结构**:成功 2xx + 资源 JSON;失败一律 `{code, message, request_id}`;业务码规则(前 3 位 = HTTP 状态码,后 2 位序号);响应头 `X-Request-Id`
5. **分页约定**:请求 `limit`(默认 20,上限 100)/`offset`;响应 `count / next / previous / results`
6. **时间格式**:ISO 8601(时区 Asia/Shanghai),以各接口真实响应为准
7. **限流总览**:按 `settings.py::DEFAULT_THROTTLE_RATES` 实际值列全量表(sms_send 20/h、sms_verify 60/h、swipe 300/h、report 20/d、post_create 20/d、post_comment 60/d、post_report 20/d、presence 600/h),超限 429 并带 `Retry-After`;**统一写生产口径**,开发环境的放宽值(DEBUG 下 sms_send 200/h、sms_verify 600/h)在「测试环境专用行为」里说明。
   - **已核实的不一致(文档照实记录)**:60 秒重发间隔走自定义异常 → 中文文案 `"发送太频繁,请稍后再试"` + 业务码 42901;而 DRF 内置节流器(swipe / report / posts / presence / IP 限流)抛的是基类 `Throttled`,无业务码、message 为 DRF 英文默认文案("Request was throttled. Expected available in N seconds.")→ 响应 `code` 回落为 `429`。文档按实际写;是否统一成中文文案+业务码属**后续可选项**,不在本设计范围
8. **测试环境专用行为**(仅测试期有效,对上线的第三方需知):验证码固定 `123456`;上传照片自动过审

## 5. `errors.md` 内容

- 全局 HTTP 状态语义:400 参数错误 / 401 未认证或令牌失效 / 403 重封禁或权限不足 / 404 资源不存在(含「双向拉黑 = 不存在」语义)/ 405 方法不允许 / 429 限流 / 500 服务端错误
- 业务码表:`config/error_codes.py` 全部 6 个(40101 / 40001 / 40002 / 42901 / 42902 / 50301),逐个给描述 + 处理建议
- **封禁两级**的表现差异(`banned_light` 仅禁滑卡 / `banned_heavy` 全域 403,白名单 `GET /users/me`、`GET /users/tags`)
- 各分册专属错误码的索引

## 6. 同步保障机制(两块)

**① CLAUDE.md 纪律条目**(加进「核心契约与纪律」,草案原文):

> **接口文档**:`docs/api/` 是接口的对外交付文档;新增/修改/删除任何 `/api/v1` 接口,**同一次改动内**必须同步更新对应分册;`python manage.py test` 会跑 `ApiDocsCoverageTests` 双向比对,漏写即红。模板与维护规则见 `docs/api/README.md`。

同时在「文档导航」段加一行指向 `docs/api/`;`docs/pitfalls/README.md` 末尾导航行同步提及。

**② 自动检查测试** `chatapp/config/tests.py::ApiDocsCoverageTests`(与现有 `ErrorEnvelopeTests` 同级):

- **真实接口集合**:递归遍历 `config/api_urls.py` 下全部 URL pattern,拼接完整路径;对每个视图取 DRF 声明的方法(`@api_view([...])` 会写进 `view.cls.http_method_names`),仅保留 `GET/POST/PATCH/DELETE`;路径参数 `<int:photo_id>`、`<str:x>` 归一化为 `{photo_id}`、`{x}`;前缀补 `/api/v1` → 得到 32 个「方法+路径」
- **文档侧集合**:扫 `docs/api/**/*.md`(用 `settings.BASE_DIR.parent / "docs" / "api"` 定位),取每行「剥离 `>`、反引号、首尾空白后以 `方法 /api/v1/…` 开头」的行,抽出「方法+路径」
- **双向比对,规则**:
  - URLconf 有、文档没有 → 失败:`接口 POST /api/v1/xxx 未写文档,请补到 docs/api/<分册>.md`
  - 文档有、URLconf 没有 → 失败:`文档记录的 X 在 URLconf 中已不存在,请删除或修正`
- 检查范围仅 `config.api_urls`(天然排除 `/admin/`、`/ops/`)

## 7. 内容来源与写作顺序

| 内容 | 权威来源 |
|---|---|
| 请求/响应字段名、类型、必填 | 各 app `serializers.py` |
| 业务规则(幂等、拉黑过滤、封禁表现、排序) | `views.py` + `services.py` |
| 限流阈值、错误码、重试头 | `settings.py` + 各 `throttles.py` + `config/error_codes.py` |

**示例 JSON 用真实响应**:开发环境对每个接口真实调用一次(测试账号 + 固定验证码 `123456`),响应原样贴入;无法真实触发的分支(如重封禁 403、限流 429)按现有测试用例的构造方式给出并保持字段一致。

**写作顺序**:README / conventions / errors 打底 → auth → users → discovery → im → moderation → feed → health。

## 8. 验收标准

1. `ApiDocsCoverageTests` 绿;`python manage.py test` 全量绿(基线 327 用例不回归)
2. 抽查 3 个接口:照文档原文复制 curl 执行,实际结果与文档一致
3. `docs/api/README.md` 的接口一览表与 §2 清单一致(32 个)
4. CLAUDE.md 纪律条目与「文档导航」更新完成
5. 前端不涉及,无需动 Flutter(`flutter analyze` 不受影响)

## 9. 关键决策记录

- **用途**:对外交付级(用户选)——每个接口都给完整请求/响应示例
- **范围**:App 接口 + 运维探针(用户选);ops 运营台/admin 不写
- **组织**:按业务模块分册,10 个文件(用户选 A,否决「一接口一文件」「单一大文件」)
- **同步保障**:CLAUDE.md 纪律条目 + 自动检查测试(用户选;否决「只靠纪律」「仅手动脚本」)
- **机器可读标记**:复用模板信息行(不另加隐藏 HTML 注释)——对读者直观,解析规则简单(行首 方法+路径)
- **双向比对**:除防「新增漏写」,还防「接口删除/改名后文档残留」

## 10. 改动面

| 文件 | 动作 |
|---|---|
| `docs/api/` 10 个文件 | 新建(README / conventions / errors / auth / users / discovery / im / moderation / feed / health) |
| `chatapp/config/tests.py` | 新增 `ApiDocsCoverageTests` |
| `CLAUDE.md` | 纪律条目 + 文档导航 |
| `docs/pitfalls/README.md` | 末尾导航行提及 `docs/api/` |

**已知取舍**:信息行格式成为强制约定,写文档时须严格遵守(检查测试会兜底);示例为静态快照,接口演进时靠「同一次改动内更新」纪律 + 抽查复核保持同步。
