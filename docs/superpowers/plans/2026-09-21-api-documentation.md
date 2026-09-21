# 接口文档体系(腾讯云风格)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 `docs/api/` 对外交付级接口文档(32 个接口,腾讯云单页风格,按模块分册),并用 `ApiDocsCoverageTests` 机器强制「新增/改动接口必须同步改文档」。

**Architecture:** 文档侧用**强制信息行**(`> \`方法\` \`/api/v1/路径\` · 鉴权 · 限流`)作为人读速览 + 机器可读标记;后端侧写一个纯逻辑模块 `config/api_doc_coverage.py` 做「URLconf ↔ 文档」双向比对,再由 `config/tests.py::ApiDocsCoverageTests` 把它变成硬门禁。任务顺序刻意是「先总则 → 先做检查模块 → 逐个分册 → 最后挂门禁」:检查模块在分册之前写完,写分册过程中可用它随时查看还差哪些接口;门禁测试放最后,是因为它必须等 32 个接口全部就位才可能变绿。

**Tech Stack:** Django 5.2 + DRF(URLconf 反射、`@api_view` 的 `view.cls`)、Python 标准库 `re`/`pathlib`、Markdown、Django `SimpleTestCase`。

## Global Constraints

- 文档语言:中文;代码、JSON、路径、命令用等宽(反引号);术语与 CLAUDE.md 保持一致
- **信息行格式(机器校验核心,必须逐字符遵守)**:单独一行,以 `> ` 开头,方法与路径各用一个反引号包裹,后面接 ` · ` 分隔的鉴权与限流说明。示例:`> \`POST\` \`/api/v1/auth/sms/send\` · 无需鉴权 · 限流 20 次/小时(按 IP)`
- **路径参数一律写 `{name}`**(如 `/api/v1/users/me/photos/{photo_id}`),不写 Django 的 `<int:photo_id>`
- **不臆造文案**:所有 `message` 字段、响应 JSON、状态码必须来自真实响应或源码里的字符串常量
- 限流额度**统一写生产口径**(`settings.py` 里非 DEBUG 分支的值);开发环境放宽值只在 `conventions.md` 的「测试环境专用行为」说明
- 后端命令一律在 `chatapp/` 目录下执行;跑任何测试前 Redis 必须在跑(`docker compose -f docker-compose.dev.yml up -d`)
- 接口清单以 spec §2 为准:32 个「方法+路径」,多一个少一个都算错
- 提交信息中文,遵循仓库既有风格(`docs:` / `test:` 前缀)
- 本计划在分支 `docs/api-docs` 上进行,最后 ff 合回 `master` 并 push(用户既定收尾习惯)
- 不写 ops 运营台、Django admin 的接口;前端(`app/`)不动

---

## 文件结构

| 文件 | 责任 |
|---|---|
| `docs/api/README.md` | 总入口:定位与更新日期、目录表、32 接口一览表、维护规则与模板说明 |
| `docs/api/conventions.md` | 公共说明:Base URL、请求约定、鉴权、统一响应结构、分页、时间、限流总览、测试环境专用行为 |
| `docs/api/errors.md` | 错误码总表:HTTP 语义、6 个业务码、封禁两级表现 |
| `docs/api/auth.md` | 账号与鉴权分册(3 接口) |
| `docs/api/users.md` | 用户资料分册(9 接口) |
| `docs/api/discovery.md` | 发现与配对分册(3 接口) |
| `docs/api/moderation.md` | 举报与拉黑分册(4 接口) |
| `docs/api/feed.md` | 广场动态分册(10 接口) |
| `docs/api/im.md` | IM 凭证分册(1 接口) |
| `docs/api/health.md` | 运维探针分册(2 接口,简化格式) |
| `chatapp/config/api_doc_coverage.py` | 纯逻辑:枚举 URLconf 接口集合、解析文档信息行、双向比出问题清单 |
| `chatapp/config/tests.py` | 追加 `ApiDocsCoverageTests`(门禁) |
| `CLAUDE.md` | 「核心契约与纪律」加接口文档条目;「文档导航」加一行 |
| `docs/pitfalls/README.md` | 末尾导航行提及 `docs/api/` |

---

### Task 1: 分支 + 总则三件套(README / conventions / errors)

**Files:**
- Create: `docs/api/README.md`、`docs/api/conventions.md`、`docs/api/errors.md`
- 参考:`docs/superpowers/specs/2026-09-21-api-documentation-design.md` §4、§5、§3

**Interfaces:**
- Produces:信息行格式与单接口模板的**唯一权威定义**(后续所有分册照它写);README 的 32 行接口一览表(与 spec §2 清单逐条对应)

- [ ] **Step 1: 开分支**

```bash
cd D:/pycharmproject/chat_app
git checkout -b docs/api-docs
```

- [ ] **Step 2: 写 `docs/api/README.md`**

结构固定为五块:

1. 标题 `# 接口文档(API Reference)` + 定位一句话:「本目录是 chat_app 后端 `/api/v1` 接口的对外交付文档」+ `> 最后更新:2026-09-21`
2. `## 目录`:10 个文件的相对链接表(文件名 | 内容)
3. `## 接口一览`:**32 行表格**,列为 `方法 | 路径 | 一句话描述 | 分册`。内容必须与下表逐字对应(路径写 `{name}` 形式):

| 方法 | 路径 | 一句话描述 | 分册 |
|---|---|---|---|
| POST | `/api/v1/auth/sms/send` | 发送短信验证码 | auth |
| POST | `/api/v1/auth/sms/verify` | 校验验证码并登录(未注册自动建号) | auth |
| POST | `/api/v1/auth/token/refresh` | 刷新访问令牌 | auth |
| GET | `/api/v1/users/me` | 获取我的资料 | users |
| PATCH | `/api/v1/users/me` | 修改我的资料 | users |
| GET | `/api/v1/users/tags` | 获取标签池 | users |
| POST | `/api/v1/users/me/photos` | 上传照片 | users |
| DELETE | `/api/v1/users/me/photos/{photo_id}` | 删除照片 | users |
| GET | `/api/v1/users/me/preference` | 获取择偶偏好 | users |
| PATCH | `/api/v1/users/me/preference` | 修改择偶偏好 | users |
| GET | `/api/v1/users/{user_id}` | 获取他人公开资料 | users |
| GET | `/api/v1/presence` | 批量查询在线状态 | users |
| GET | `/api/v1/discovery/candidates` | 拉取候选卡 | discovery |
| POST | `/api/v1/discovery/swipe` | 提交滑卡动作 | discovery |
| GET | `/api/v1/matches` | 配对列表(分页) | discovery |
| POST | `/api/v1/im/user_sig` | 获取 IM userSig | im |
| POST | `/api/v1/reports` | 举报用户 | moderation |
| GET | `/api/v1/blocks` | 拉黑列表(分页) | moderation |
| POST | `/api/v1/blocks` | 拉黑用户 | moderation |
| DELETE | `/api/v1/blocks/{user_id}` | 解除拉黑 | moderation |
| GET | `/api/v1/posts` | 动态流(分页) | feed |
| POST | `/api/v1/posts` | 发布动态(可带图) | feed |
| GET | `/api/v1/posts/mine` | 我的动态(分页) | feed |
| GET | `/api/v1/posts/{post_id}` | 动态详情 | feed |
| DELETE | `/api/v1/posts/{post_id}` | 删除我的动态 | feed |
| POST | `/api/v1/posts/{post_id}/like` | 点赞 | feed |
| DELETE | `/api/v1/posts/{post_id}/like` | 取消点赞 | feed |
| GET | `/api/v1/posts/{post_id}/comments` | 评论列表(分页) | feed |
| POST | `/api/v1/posts/{post_id}/comments` | 发表评论 | feed |
| POST | `/api/v1/posts/{post_id}/report` | 举报动态 | feed |
| GET | `/api/v1/health` | 存活探针 | health |
| GET | `/api/v1/readyz` | 就绪探针(DB/Redis) | health |

4. `## 如何调用` :3~5 行,指向 `conventions.md`,给出最短调用链(登录拿 token → 带 `Authorization` 调业务接口)
5. `## 维护规则(新增/修改接口时必须遵守)`,必须含:
   - 强制信息行的**原文格式与一个真实例子**(照 Global Constraints 那条抄)
   - 单接口 7 元素模板的说明(标题 / 信息行 / 接口描述 / 请求参数表 / 响应参数表 / 示例 / 错误码表)
   - 「新增接口的完整步骤」:改代码 → 在对应分册加一节 → 更新本页一览表 → 跑 `python manage.py test config` 确认门禁绿
   - 门禁说明:`chatapp/config/tests.py::ApiDocsCoverageTests` 会双向比对 URLconf 与信息行,漏写或残留即测试红

- [ ] **Step 3: 写 `docs/api/conventions.md`**

按 spec §4 八条逐条成文,每条一个 `##`,值全部照抄(已核实):

1. `## Base URL`:对外统一写 `http://<域名>/api/v1`;当前测试环境 `http://<SERVER_IP>/api/v1`;本机开发 `http://127.0.0.1:8000/api/v1`;Android 模拟器访问本机用 `http://10.0.2.2:8000/api/v1`;HTTPS 待域名备案后启用
2. `## 请求约定`:GET 查询 / POST 创建 / PATCH 局部更新 / DELETE 删除;`Content-Type: application/json`;上传用 `multipart/form-data`;响应头带 `X-Request-Id`
3. `## 鉴权`:`Authorization: Bearer <access>`;access 30 分钟、refresh 30 天;刷新即轮换,旧 refresh 立即进黑名单;**单设备登录**——同一账号仅一台设备在线,被顶设备后续请求收 `401` + `code: 40101`
4. `## 统一响应结构`:成功 2xx + 资源 JSON;失败一律 `{"code": int, "message": str, "request_id": str}`;`code` 规则 = 前 3 位与 HTTP 状态码一致、后 2 位为业务序号(如 `42901`);客户端应以 `code` 为准做分支
5. `## 分页约定`:请求 `limit`(默认 20,上限 100)/`offset`;响应 `{count, next, previous, results}`;`next`/`previous` 为完整 URL
6. `## 时间格式`:ISO 8601,时区 Asia/Shanghai(如 `2026-09-21T14:30:00+08:00`);以各接口真实响应为准
7. `## 限流总览`:一张表列全 8 个 scope —— sms_send 20 次/小时(按 IP)、sms_verify 60 次/小时(按 IP)、swipe 300 次/小时(按用户)、report 20 次/天(按用户)、post_create 20 次/天(按用户)、post_comment 60 次/天(按用户)、post_report 20 次/天(按用户)、presence 600 次/小时(按用户);超限返回 `429` + `Retry-After` 响应头。**必须写明**:60 秒重发间隔走自定义异常返回中文文案 + 业务码 `42901`;DRF 内置节流器返回的 `message` 是框架英文默认文案、`code` 为 `429`
8. `## 测试环境专用行为`:仅测试环境生效——验证码固定 `123456`;上传照片自动过审(`AUTO_APPROVE=1`)

- [ ] **Step 4: 写 `docs/api/errors.md`**

三块:

1. `## HTTP 状态码语义`:400 参数/业务校验失败;401 未认证、令牌失效或被顶号(带 `40101`);403 权限不足或账号重封禁;404 资源不存在(含「双向拉黑 = 不存在」语义);405 方法不允许;429 触发限流;503 依赖服务不可用;500 服务端异常
2. `## 业务码总表`:`config/error_codes.py` 全部 6 个,列 `业务码 | HTTP | 含义 | 处理建议`:
   - `40101` 401 单设备登录冲突(账号已在其他设备登录,请重新登录)→ 客户端清凭证回登录页
   - `40001` 400 验证码已过期,请重新获取 → 重新发码
   - `40002` 400 验证码错误 → 允许重试,注意 5 次锁定时长
   - `42901` 429 重发间隔未到(发送太频繁,请稍后再试)→ 按 `Retry-After` 等待
   - `42902` 429 错误次数过多,请稍后再试 → 按 `Retry-After` 等待(15 分钟)
   - `50301` 503 短信服务暂时不可用,请稍后重试 → 稍后重试
3. `## 封禁行为`:`banned_light` 仅禁止滑卡(`POST /api/v1/discovery/swipe` 403),其余功能可用;`banned_heavy` 全域 403,白名单仅 `GET /api/v1/users/me`、`GET /api/v1/users/tags`

- [ ] **Step 5: 机械自检**

```bash
cd D:/pycharmproject/chat_app
grep -c '^| \(GET\|POST\|PATCH\|DELETE\) |' docs/api/README.md      # 期望 32
grep -c '^> `' docs/api/README.md docs/api/conventions.md docs/api/errors.md   # 期望 0(总则里不放信息行)
```

- [ ] **Step 6: 提交**

```bash
git add docs/api/README.md docs/api/conventions.md docs/api/errors.md
git commit -m "docs(api): 总则三件套——README 接口一览表 / conventions 公共说明 / errors 错误码总表"
```

---

### Task 2: 检查模块 `config/api_doc_coverage.py`(纯逻辑 + 单元测试)

**Files:**
- Create: `chatapp/config/api_doc_coverage.py`
- Test: `chatapp/config/tests.py`(在文件末尾追加 `ApiDocCoverageLogicTests`)
- 参考:`chatapp/config/urls.py`(根路由)、`chatapp/config/api_urls.py`(API 路由)

**Interfaces:**
- Produces:
  - `endpoints_from_urlconf() -> set[tuple[str, str]]`(方法大写、路径形如 `/api/v1/users/me/photos/{photo_id}`)
  - `endpoints_from_docs(docs_dir: Path) -> dict[tuple[str, str], str]`(值 = `文件名:行号`)
  - `find_problems(docs_dir: Path | None = None) -> list[str]`
  - 常量 `DOCS_DIR: Path`、`METHODS = ("get", "post", "patch", "delete")`
- Consumes:无(本任务不依赖任何已写好的文档)

- [ ] **Step 1: 先写失败的单元测试**

追加到 `chatapp/config/tests.py` 末尾(注意:`SimpleTestCase` 不碰数据库,本模块也不需要 Redis):

```python
class ApiDocCoverageLogicTests(SimpleTestCase):
    """检查模块自身的单元测试(用临时目录,不依赖真实文档)。"""

    def test_normalize_route_params(self):
        from config.api_doc_coverage import normalize_route

        self.assertEqual(normalize_route("me/photos/<int:photo_id>"),
                         "me/photos/{photo_id}")
        self.assertEqual(normalize_route("blocks/<int:user_id>"),
                         "blocks/{user_id}")

    def test_endpoints_from_urlconf_covers_api_v1(self):
        from config.api_doc_coverage import endpoints_from_urlconf

        found = endpoints_from_urlconf()
        self.assertIn(("GET", "/api/v1/users/me"), found)
        self.assertIn(("PATCH", "/api/v1/users/me"), found)
        self.assertIn(("DELETE", "/api/v1/users/me/photos/{photo_id}"), found)
        self.assertIn(("POST", "/api/v1/auth/token/refresh"), found)
        # ops/admin 不在 /api/v1 下,不应被枚举到
        self.assertFalse(any(p.startswith("/ops") for _, p in found))

    def test_endpoints_from_docs_parses_info_line(self):
        from config.api_doc_coverage import endpoints_from_docs

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.md"
            path.write_text(
                "# 演示分册\n\n"
                "### 1.1 演示接口\n\n"
                "> `POST` `/api/v1/demo/thing` · 需要鉴权 · 无额外限流\n\n"
                "正文里提到 `GET /api/v1/other` 不算信息行。\n",
                encoding="utf-8")
            found = endpoints_from_docs(Path(tmp))
        self.assertEqual(set(found), {("POST", "/api/v1/demo/thing")})

    def test_find_problems_reports_both_directions(self):
        from config.api_doc_coverage import find_problems

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "demo.md").write_text(
                "> `GET` `/api/v1/demo/gone` · 需要鉴权 · 无额外限流\n",
                encoding="utf-8")
            problems = find_problems(Path(tmp))
        joined = "\n".join(problems)
        self.assertIn("未写文档", joined)            # URLconf 有、文档没有
        self.assertIn("/api/v1/demo/gone", joined)   # 文档有、URLconf 没有
```

同时在 `chatapp/config/tests.py` 顶部补两个 import(已有的 import 保持不动):

```python
import tempfile
from pathlib import Path
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd D:/pycharmproject/chat_app/chatapp
python manage.py test config.tests.ApiDocCoverageLogicTests -v 2
```

Expected:FAIL,`ModuleNotFoundError: No module named 'config.api_doc_coverage'`

- [ ] **Step 3: 实现 `chatapp/config/api_doc_coverage.py`**

```python
"""接口文档覆盖率:URLconf 与 docs/api 信息行的双向比对(逻辑层,门禁测试在 tests.py)。"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.urls import URLPattern, URLResolver

DOCS_DIR = Path(settings.BASE_DIR).parent / "docs" / "api"

METHODS = ("get", "post", "patch", "delete")

# 信息行(剥离 ">"、反引号、空白后)以「方法 空格 /api/v1/...」开头
INFO_LINE_RE = re.compile(r"^(GET|POST|PATCH|DELETE) (/api/v1/\S+)")
# Django 路径参数:<int:photo_id> / <str:code> / <photo_id> 统一成 {photo_id}
ROUTE_PARAM_RE = re.compile(r"<(?:\w+:)?(\w+)>")
# 行首的 markdown 装饰:引用符、空白、加粗/斜体星号
LINE_DECORATION_RE = re.compile(r"^[\s>*]+")


def normalize_route(route: str) -> str:
    return ROUTE_PARAM_RE.sub(r"{\1}", route)


def _methods_of(view) -> list[str]:
    """DRF 视图(@api_view 或 as_view())的 cls 上,只有被声明的方法才是可调用属性。"""
    cls = getattr(view, "cls", None)
    if cls is None:
        return []
    return [m.upper() for m in METHODS if callable(getattr(cls, m, None))]


def endpoints_from_urlconf() -> set[tuple[str, str]]:
    from config import api_urls

    found: set[tuple[str, str]] = set()

    def walk(patterns, prefix: str) -> None:
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                walk(pattern.url_patterns, prefix + str(pattern.pattern))
            elif isinstance(pattern, URLPattern):
                for method in _methods_of(pattern.callback):
                    found.add((method, normalize_route("/api/v1/" + prefix + str(pattern.pattern))))

    walk(api_urls.urlpatterns, "")
    return found


def endpoints_from_docs(docs_dir: Path = DOCS_DIR) -> dict[tuple[str, str], str]:
    documented: dict[tuple[str, str], str] = {}
    for md in sorted(Path(docs_dir).rglob("*.md")):
        for lineno, line in enumerate(md.read_text(encoding="utf-8").splitlines(), 1):
            stripped = LINE_DECORATION_RE.sub("", line).replace("`", "").strip()
            match = INFO_LINE_RE.match(stripped)
            if match:
                documented[(match.group(1), match.group(2))] = f"{md.name}:{lineno}"
    return documented


def find_problems(docs_dir: Path | None = None) -> list[str]:
    real = endpoints_from_urlconf()
    documented = endpoints_from_docs(docs_dir or DOCS_DIR)

    problems = [
        f"接口 {method} {path} 未写文档,请补到 docs/api/<分册>.md"
        for method, path in sorted(real - set(documented))
    ]
    problems += [
        f"文档记录的 {method} {path}({documented[(method, path)]})在 URLconf 中已不存在,请删除或修正"
        for method, path in sorted(set(documented) - real)
    ]
    return problems
```

- [ ] **Step 4: 跑测试确认通过**

```bash
python manage.py test config.tests.ApiDocCoverageLogicTests -v 2
```

Expected:4 个用例全 PASS

- [ ] **Step 5: 打印当前缺口(给后面写分册时当进度条用)**

```bash
python manage.py shell -c "import config.api_doc_coverage as c; print(len(c.endpoints_from_urlconf()), '个真实接口'); [print(p) for p in c.find_problems()]"
```

Expected:输出 `32 个真实接口`,后跟 32 行「未写文档」(此刻文档还没写,正是预期)

- [ ] **Step 6: 提交**

```bash
git add chatapp/config/api_doc_coverage.py chatapp/config/tests.py
git commit -m "test(config): api_doc_coverage 检查模块——URLconf/文档信息行解析与双向比对(4 用例)"
```

---

### Task 3: `docs/api/auth.md`(3 接口)

**Files:**
- Create: `docs/api/auth.md`
- 参考(以此为准):`chatapp/accounts/views.py:62-128`、`chatapp/accounts/serializers.py`、`chatapp/accounts/exceptions.py`、`chatapp/accounts/services.py`

**Interfaces:**
- Produces:3 行强制信息行(后置门禁测试要用):

```markdown
> `POST` `/api/v1/auth/sms/send` · 无需鉴权 · 限流 20 次/小时(按 IP)
> `POST` `/api/v1/auth/sms/verify` · 无需鉴权 · 限流 60 次/小时(按 IP)
> `POST` `/api/v1/auth/token/refresh` · 无需鉴权 · 无额外限流
```

- [ ] **Step 1: 起依赖并拿一个 access token(后续任务复用)**

```bash
cd D:/pycharmproject/chat_app/chatapp
docker compose -f docker-compose.dev.yml up -d
python manage.py runserver          # 另开一个终端保持运行

# 取 token(开发模式验证码固定 123456)
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/sms/send \
  -H "Content-Type: application/json" -d '{"phone":"13900000010"}'
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/sms/verify \
  -H "Content-Type: application/json" -d '{"phone":"13900000010","code":"123456"}'
```

把响应里的 `access` 与 `refresh` 都记下来:后续任务命令里 `$TOKEN` 指 `access`,`$REFRESH` 指 `refresh`。

- [ ] **Step 2: 抓三个接口的真实响应**

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/sms/send \
  -H "Content-Type: application/json" -d '{"phone":"13900000010"}'          # 成功
# 紧接重发一次 → 触发 60 秒间隔,拿到 42901 + Retry-After 真实文案:
curl -si -X POST http://127.0.0.1:8000/api/v1/auth/sms/send \
  -H "Content-Type: application/json" -d '{"phone":"13900000010"}'
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/sms/verify \
  -H "Content-Type: application/json" -d '{"phone":"13900000010","code":"000000"}'   # 40002
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/token/refresh \
  -H "Content-Type: application/json" -d "{\"refresh\":\"$REFRESH\"}"        # 成功(响应含新 refresh)
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/token/refresh \
  -H "Content-Type: application/json" -d '{"refresh":"bad.token.here"}'      # 401 示例
```

注意:Step 1 已经发过一次码,若这次发送被 60 秒间隔拦住(直接回 42901),换个手机号或等 60 秒再发一次,务必拿到「成功」与「42901」两个真实响应。

- [ ] **Step 3: 写 `docs/api/auth.md`**

开头一段分册说明 + 「本分册含 3 个接口」。随后 3 节,每节 7 元素(标题 / 信息行 / 接口描述 / 请求参数表 / 响应参数表 / 示例 / 错误码表,格式照 `docs/api/README.md` 模板),编号 `3.1`/`3.2`/`3.3`。必写点:

1. **发送短信验证码**:参数 `phone`(String);响应 `status`;描述写清——验证码 5 分钟有效、同号 60 秒重发间隔、连续错误 5 次锁 15 分钟、测试环境固定 `123456`;错误码 `42901`(带 `Retry-After`,**用真实文案**)、`50301`、400(参数不合法);响应示例给成功 + 42901 两个
2. **校验验证码并登录**:参数 `phone`、`code`;响应 `access`、`refresh`、`is_new_user`、`user_id`(注意:`user_id` 是账号 ID,不是资料表主键);描述写清——未注册号码自动建号、成功后有 60 秒幂等重放窗口、**单设备登录**(再登录会顶掉旧设备,旧设备收 `40101`);错误码 `40001`、`40002`、`42902`(带 `Retry-After`)、400;示例给成功 + 40002
3. **刷新访问令牌**:参数 `refresh`;响应 `access`、`refresh`(每次刷新都轮换并拉黑旧 refresh);描述写清——access 30 分钟 / refresh 30 天、被顶号的旧 refresh 会直接 401 + `40101`;错误码 401(格式不合法/已过期/已拉黑)、`40101`;示例给成功 + 40101

- [ ] **Step 4: 验证信息行被解析到**

```bash
cd D:/pycharmproject/chat_app/chatapp
python manage.py shell -c "import config.api_doc_coverage as c; print(sorted(p for p in c.endpoints_from_docs() if '/auth/' in p[1]))"
```

Expected:`[('POST', '/api/v1/auth/sms/send'), ('POST', '/api/v1/auth/sms/verify'), ('POST', '/api/v1/auth/token/refresh')]`

- [ ] **Step 5: 提交**

```bash
git add docs/api/auth.md
git commit -m "docs(api): auth 分册——发码/登录/刷新令牌(含真实 42901 文案与单设备登录说明)"
```

---

### Task 4: `docs/api/users.md`(9 接口)

**Files:**
- Create: `docs/api/users.md`
- 参考:`chatapp/users/views.py`、`chatapp/users/serializers.py`、`chatapp/users/models.py`、`chatapp/users/presence.py`、`chatapp/moderation/services.py`(拉黑过滤)

**Interfaces:**
- Produces:9 行强制信息行:

```markdown
> `GET` `/api/v1/users/me` · 需要鉴权 · 无额外限流
> `PATCH` `/api/v1/users/me` · 需要鉴权 · 无额外限流
> `GET` `/api/v1/users/tags` · 需要鉴权 · 无额外限流
> `POST` `/api/v1/users/me/photos` · 需要鉴权 · 无额外限流
> `DELETE` `/api/v1/users/me/photos/{photo_id}` · 需要鉴权 · 无额外限流
> `GET` `/api/v1/users/me/preference` · 需要鉴权 · 无额外限流
> `PATCH` `/api/v1/users/me/preference` · 需要鉴权 · 无额外限流
> `GET` `/api/v1/users/{user_id}` · 需要鉴权 · 无额外限流
> `GET` `/api/v1/presence` · 需要鉴权 · 限流 600 次/小时(按用户)
```

- [ ] **Step 1: 抓真实数据(先拿到真实 user_id 与一张图)**

```bash
cd D:/pycharmproject/chat_app/chatapp
python manage.py shell -c "from django.contrib.auth import get_user_model as g; print(list(g().objects.values_list('id','phone')))"
ls ../app/android/app/src/main/res/mipmap-hdpi/    # 取一个 png 当上传用图
```

- [ ] **Step 2: 抓九个接口的真实响应**

```bash
B="http://127.0.0.1:8000/api/v1"
curl -s $B/users/me -H "Authorization: Bearer $TOKEN"                       # 资料(含 status/missing_fields)
curl -s -X PATCH $B/users/me -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"city":"上海"}'                                                       # 局部更新
curl -s $B/users/tags -H "Authorization: Bearer $TOKEN"                     # 12 个标签
curl -s -X POST $B/users/me/photos -H "Authorization: Bearer $TOKEN" \
  -F "file=@../app/android/app/src/main/res/mipmap-hdpi/ic_launcher.png"    # 201
curl -s -X DELETE $B/users/me/photos/{photo_id} -H "Authorization: Bearer $TOKEN" -o /dev/null -w '%{http_code}\n'   # 204
curl -s $B/users/me/preference -H "Authorization: Bearer $TOKEN"
curl -s -X PATCH $B/users/me/preference -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"age_min":22,"age_max":35}'
curl -s $B/users/{user_id} -H "Authorization: Bearer $TOKEN"                # 他人公开资料(用 Step 1 的 id)
curl -s "$B/presence?user_ids={user_id}" -H "Authorization: Bearer $TOKEN"  # 在线状态
# 失败样例:参数不合法
curl -s "$B/presence?user_ids=abc" -H "Authorization: Bearer $TOKEN"        # 400
curl -s $B/users/999999 -H "Authorization: Bearer $TOKEN"                   # 404
```

- [ ] **Step 3: 写 `docs/api/users.md`**

9 节,编号 `4.1`~`4.9`,每节 7 元素。字段表逐个对着 `users/serializers.py` 抄(类型、必填、取值范围)。必写点:

1. **GET /users/me**:响应字段照 `ProfileSerializer`;写清 `id` 是资料表主键、`user_id` 是账号 ID;**资料完善判定**——昵称/性别/生日/城市/简介非空 + ≥1 张过审照片 → `status=complete`,否则 `incomplete` 且 `missing_fields` 列出缺项;`banned_light`/`banned_heavy` 出现在 `status` 里
2. **PATCH /users/me**:可改字段与校验(未满 18 岁 400;`tag_ids` 全量替换语义);改昵称会异步同步 IM
3. **GET /users/tags**:12 个标签(数据迁移写入),响应为数组
4. **POST /users/me/photos**:`multipart/form-data`,字段名 `file`;最多 6 张、单张 ≤5MB、超出 400;测试环境上传即过审;返回 201 + 照片对象
5. **DELETE /users/me/photos/{photo_id}**:204;不存在的照片 404
6. **GET /users/me/preference**:目标性别(可空=不限)/年龄区间/城市
7. **PATCH /users/me/preference**:局部更新,字段校验范围
8. **GET /users/{user_id}**:公开资料;**写清 404 语义**——被双向拉黑、账号不存在、对方重封禁,一律 404「用户不存在」(防止探测)
9. **GET /presence**:`user_ids` 逗号分隔、≤100 个、去重保序;被拉黑/不存在/自己/重封禁的人**直接从结果省略**;`online` = 120 秒内有认证请求;无记录(`last_active_at: null`)含义;400 的三种情形(空/非数字/超 100);限流 600/小时

- [ ] **Step 4: 验证信息行被解析到**

```bash
python manage.py shell -c "import config.api_doc_coverage as c; print(len([1 for m,p in c.endpoints_from_docs() if p.startswith('/api/v1/users') or p=='/api/v1/presence']))"
```

Expected:`9`

- [ ] **Step 5: 提交**

```bash
git add docs/api/users.md
git commit -m "docs(api): users 分册——资料/照片/偏好/标签/公开资料/在线状态(9 接口)"
```

---

### Task 5: `docs/api/discovery.md`(3 接口)

**Files:**
- Create: `docs/api/discovery.md`
- 参考:`chatapp/discovery/views.py`、`chatapp/discovery/serializers.py`、`chatapp/discovery/models.py`(Swipe/Match)、`chatapp/users/models.py::birthday_bounds`

**Interfaces:**
- Produces:3 行强制信息行:

```markdown
> `GET` `/api/v1/discovery/candidates` · 需要鉴权 · 无额外限流
> `POST` `/api/v1/discovery/swipe` · 需要鉴权 · 限流 300 次/小时(按用户)
> `GET` `/api/v1/matches` · 需要鉴权 · 无额外限流
```

- [ ] **Step 1: 抓真实响应**

前置:`$TOKEN` 取法见 Task 3 Step 1(无则重跑那两条 curl);`{user_id}` 换成真实账号 id,查法:

```bash
cd D:/pycharmproject/chat_app/chatapp
python manage.py shell -c "from django.contrib.auth import get_user_model as g; print(list(g().objects.values_list('id','phone')))"
```

```bash
B="http://127.0.0.1:8000/api/v1"
curl -s "$B/discovery/candidates?limit=5" -H "Authorization: Bearer $TOKEN"
curl -s -X POST $B/discovery/swipe -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"target_user_id":{user_id},"action":"like"}'      # 幂等:同参重发结果一致
curl -s "$B/matches?limit=20&offset=0" -H "Authorization: Bearer $TOKEN"
curl -s -X POST $B/discovery/swipe -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"target_user_id":123,"action":"like"}'            # 对方资料不完整/不存在 → 400
```

若开发库候选为空,先造数:`python manage.py seed_fake_users --count 20`;无配对时可用 `python manage.py dev_reset_pair --a u8 --b u9` 重演配对。

- [ ] **Step 2: 写 `docs/api/discovery.md`**

3 节(`5.1`~`5.3`)。必写点:

1. **candidates**:`limit` 默认 10、上限 20(非法值回落默认);**筛选规则**——排除自己/划过的人/已配对/**双向拉黑的人**;只推「资料完善(complete)且有已过审照片」的人;按 `preference` 的目标性别/城市/年龄区间过滤;返回随机顺序;响应字段照 `CandidateSerializer`(含照片、标签、`im_user_id`)
2. **swipe**:参数 `target_user_id`、`action`(`like`/`pass`);**幂等**——重复提交保留第一次的动作与结果;互喜时 `matched: true` 且双方各收到一条系统灰条消息;轻封禁用户调用 403(账号已被限制,暂时无法滑卡);不能划自己 / 对方资料不完整 → 400;限流 300 次/小时
3. **matches**:分页(`count/next/previous/results`);每项字段 `user_id`/`im_user_id`/`nickname`/`avatar_url`/`matched_at`;被拉黑的人不出现在列表

- [ ] **Step 3: 验证 + 提交**

```bash
python manage.py shell -c "import config.api_doc_coverage as c; print(sorted(p for m,p in c.endpoints_from_docs() if 'discovery' in p or p=='/api/v1/matches'))"
git add docs/api/discovery.md
git commit -m "docs(api): discovery 分册——候选卡/滑卡(幂等+配对灰条)/配对列表"
```

Expected:`[('/api/v1/discovery/candidates', ...)]` 形式的 3 条(方法分别为 GET/POST/GET)

---

### Task 6: `docs/api/moderation.md`(4 接口)

**Files:**
- Create: `docs/api/moderation.md`
- 参考:`chatapp/moderation/views.py`、`chatapp/moderation/serializers.py`、`chatapp/moderation/models.py`(Report/Block)

**Interfaces:**
- Produces:4 行强制信息行:

```markdown
> `POST` `/api/v1/reports` · 需要鉴权 · 限流 20 次/天(按用户)
> `GET` `/api/v1/blocks` · 需要鉴权 · 无额外限流
> `POST` `/api/v1/blocks` · 需要鉴权 · 无额外限流
> `DELETE` `/api/v1/blocks/{user_id}` · 需要鉴权 · 无额外限流
```

- [ ] **Step 1: 抓真实响应**

前置:`$TOKEN` 取法见 Task 3 Step 1;`{user_id}` 换成真实账号 id(查法见 Task 4 Step 1)。

```bash
cd D:/pycharmproject/chat_app/chatapp
B="http://127.0.0.1:8000/api/v1"
curl -s -X POST $B/reports -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"target_user_id":{user_id},"type":"harass","detail":"示例"}'   # 201;同对象重复举报返回 200 + 原记录
curl -s $B/blocks -H "Authorization: Bearer $TOKEN"
curl -s -X POST $B/blocks -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"target_user_id":{user_id}}'                                   # 201;重复返回 200
curl -s -X DELETE $B/blocks/{user_id} -H "Authorization: Bearer $TOKEN" -o /dev/null -w '%{http_code}\n'  # 204
curl -s -X POST $B/reports -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"target_user_id":{自己 id},"type":"harass"}'                    # 400 不能举报自己
```

举报类型可选值以 `moderation/serializers.py` 的 choices 为准,照抄进文档。

- [ ] **Step 2: 写 `docs/api/moderation.md`**

4 节(`6.1`~`6.4`)。必写点:

1. **POST /reports**:参数 `target_user_id`、`type`(枚举照 serializer)、`detail`(可选);**幂等**——同一对象已有未处理举报时不重复创建,返回 200 + 已有记录(新建为 201);不能举报自己 400;举报后由运营台人工处理,处理结果通过系统通知回到被举报人/举报人(一句话说明即可,细节属运营台)
2. **GET /blocks**:分页;每项含被拉黑者昵称/头像
3. **POST /blocks**:参数 `target_user_id`;幂等(新建 201 / 已存在 200);不能拉黑自己 400;**拉黑 = 双向不可见**(对方也看不到你,且双方从彼此的候选卡/配对列表/在线状态里消失),同时同步到 IM 黑名单
4. **DELETE /blocks/{user_id}**:204;未拉黑过的对象也返回 204(幂等)

- [ ] **Step 3: 验证 + 提交**

```bash
python manage.py shell -c "import config.api_doc_coverage as c; print(len([1 for m,p in c.endpoints_from_docs() if p.startswith('/api/v1/reports') or p.startswith('/api/v1/blocks')]))"
git add docs/api/moderation.md
git commit -m "docs(api): moderation 分册——举报/拉黑三操作(幂等与双向不可见语义)"
```

Expected:`4`

---

### Task 7: `docs/api/feed.md`(10 接口)

**Files:**
- Create: `docs/api/feed.md`
- 参考:`chatapp/feed/views.py`、`chatapp/feed/serializers.py`、`chatapp/feed/services.py::visible_posts`、`chatapp/feed/throttles.py`

**Interfaces:**
- Produces:10 行强制信息行:

```markdown
> `GET` `/api/v1/posts` · 需要鉴权 · 无额外限流
> `POST` `/api/v1/posts` · 需要鉴权 · 限流 20 次/天(按用户)
> `GET` `/api/v1/posts/mine` · 需要鉴权 · 无额外限流
> `GET` `/api/v1/posts/{post_id}` · 需要鉴权 · 无额外限流
> `DELETE` `/api/v1/posts/{post_id}` · 需要鉴权 · 无额外限流
> `POST` `/api/v1/posts/{post_id}/like` · 需要鉴权 · 无额外限流
> `DELETE` `/api/v1/posts/{post_id}/like` · 需要鉴权 · 无额外限流
> `GET` `/api/v1/posts/{post_id}/comments` · 需要鉴权 · 无额外限流
> `POST` `/api/v1/posts/{post_id}/comments` · 需要鉴权 · 限流 60 次/天(按用户)
> `POST` `/api/v1/posts/{post_id}/report` · 需要鉴权 · 限流 20 次/天(按用户)
```

- [ ] **Step 1: 抓真实响应(发一条自己的动态当样本)**

前置:`$TOKEN` 取法见 Task 3 Step 1。

```bash
cd D:/pycharmproject/chat_app/chatapp
B="http://127.0.0.1:8000/api/v1"
curl -s -X POST $B/posts -H "Authorization: Bearer $TOKEN" -F 'text=文档示例动态' \
  -F "images=@../app/android/app/src/main/res/mipmap-hdpi/ic_launcher.png"   # 201,记下 post_id
curl -s "$B/posts?limit=5" -H "Authorization: Bearer $TOKEN"
curl -s "$B/posts/mine?limit=5" -H "Authorization: Bearer $TOKEN"
curl -s $B/posts/{post_id} -H "Authorization: Bearer $TOKEN"
curl -s -X POST $B/posts/{post_id}/like -H "Authorization: Bearer $TOKEN"     # 201;重复 → 200
curl -s -X DELETE $B/posts/{post_id}/like -H "Authorization: Bearer $TOKEN" -o /dev/null -w '%{http_code}\n'  # 204
curl -s -X POST $B/posts/{post_id}/comments -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"text":"示例评论"}'                 # 201
curl -s "$B/posts/{post_id}/comments?limit=5" -H "Authorization: Bearer $TOKEN"
curl -s -X POST $B/posts/{post_id}/report -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"type":"spam"}'                    # 201(不能举报自己的动态 → 换成别人的 post_id 才是成功路径)
curl -s -X DELETE $B/posts/{post_id} -H "Authorization: Bearer $TOKEN" -o /dev/null -w '%{http_code}\n'  # 204(非作者 → 404)
```

- [ ] **Step 2: 写 `docs/api/feed.md`**

10 节(`7.1`~`7.10`)。必写点:

1. **GET /posts**:分页;**可见性规则**(照 `visible_posts`)——排除作者被双向拉黑/重封禁的动态;响应字段照 `PostSerializer`(`like_count`/`comment_count`/`liked_by_me`/`images` 等)
2. **POST /posts**:`multipart/form-data`;字段 `text`、`images`(可多张,字段名 `images`);限流 20 次/天;201 + 动态对象
3. **GET /posts/mine**:分页;含自己全部动态(不看可见性过滤)
4. **GET /posts/{post_id}**:详情;不可见/不存在 → 404
5. **DELETE /posts/{post_id}**:仅作者可删,非作者 404;204
6. **POST /posts/{post_id}/like**:幂等(201 首次 / 200 重复),响应 `{"liked": true}`
7. **DELETE /posts/{post_id}/like**:204(未点赞也 204)
8. **GET /posts/{post_id}/comments**:分页;排除被拉黑/重封禁作者的评论
9. **POST /posts/{post_id}/comments**:参数 `text`;限流 60 次/天;201;作者会收到系统通知(一句话说明)
10. **POST /posts/{post_id}/report**:参数 `type`、`detail`;幂等(201/200),响应 `{"id", "status"}`;不能举报自己的动态 400

- [ ] **Step 3: 验证 + 提交**

```bash
python manage.py shell -c "import config.api_doc_coverage as c; print(len([1 for m,p in c.endpoints_from_docs() if p.startswith('/api/v1/posts')]))"
git add docs/api/feed.md
git commit -m "docs(api): feed 分册——动态流/发布/点赞/评论/举报(10 接口)"
```

Expected:`10`

---

### Task 8: `docs/api/im.md` + `docs/api/health.md`(3 接口)

**Files:**
- Create: `docs/api/im.md`、`docs/api/health.md`
- 参考:`chatapp/im/views.py`、`chatapp/accounts/views.py:26-59`(health/readyz)

**Interfaces:**
- Produces:3 行强制信息行:

```markdown
> `POST` `/api/v1/im/user_sig` · 需要鉴权 · 无额外限流
> `GET` `/api/v1/health` · 无需鉴权 · 无额外限流
> `GET` `/api/v1/readyz` · 无需鉴权 · 无额外限流
```

- [ ] **Step 1: 抓真实响应**

前置:`$TOKEN` 取法见 Task 3 Step 1。

```bash
cd D:/pycharmproject/chat_app/chatapp
B="http://127.0.0.1:8000/api/v1"
curl -s -X POST $B/im/user_sig -H "Authorization: Bearer $TOKEN"
curl -s $B/health
curl -s -w '\n%{http_code}\n' $B/readyz
```

- [ ] **Step 2: 写 `docs/api/im.md`**

1 节(`8.1`)。必写点:响应 `user_sig`/`sdkappid`/`im_user_id`/`expire`(秒);说明——`im_user_id` 规则 `u{user_id}`;每次调用都会幂等确保 IM 账号存在;若本次登录顶掉了旧设备,服务端会在发签名前先踢旧 IM 会话(客户端若收到 SDK 的「已在其他设备登录」提示,属单设备登录预期行为);重封禁用户 403;错误码 401。

- [ ] **Step 3: 写 `docs/api/health.md`**(简化格式:信息行 + 描述 + 响应示例 + 状态码含义,不要求参数表)

- **GET /health**:存活探针,固定 `{"status": "ok"}` 200
- **GET /readyz**:就绪探针,响应 `{"status": "ok"|"unavailable", "checks": {"db": "ok"|"error", "redis": "ok"|"error"}}`;全 ok → 200,任一异常 → 503;供负载均衡/监控使用,不供客户端调用

- [ ] **Step 4: 验证 + 提交**

```bash
python manage.py shell -c "import config.api_doc_coverage as c; print(c.find_problems())"
git add docs/api/im.md docs/api/health.md
git commit -m "docs(api): im 与 health 分册——userSig 获取与运维探针(3 接口)"
```

Expected:`[]`(空列表——32 个接口此时应全部有文档;若还有输出,回到对应任务补齐)

---

### Task 9: 门禁测试 `ApiDocsCoverageTests`

**Files:**
- Modify: `chatapp/config/tests.py`(在 `ApiDocCoverageLogicTests` 之后追加)

**Interfaces:**
- Consumes:`config.api_doc_coverage.find_problems`、`endpoints_from_urlconf`(Task 2);`docs/api/*.md` 的信息行(Task 3–8)
- Produces:32 接口覆盖率的硬门禁

- [ ] **Step 1: 写门禁测试**

```python
class ApiDocsCoverageTests(SimpleTestCase):
    """接口文档门禁:URLconf ↔ docs/api 信息行双向比对(漏写/残留即红)。"""

    def test_docs_cover_every_endpoint(self):
        from config.api_doc_coverage import endpoints_from_docs, endpoints_from_urlconf

        missing = sorted(endpoints_from_urlconf() - set(endpoints_from_docs()))
        self.assertEqual(
            missing, [],
            "以下接口未写文档,请补到 docs/api/ 对应分册:\n" +
            "\n".join(f"  {m} {p}" for m, p in missing))

    def test_docs_have_no_stale_endpoints(self):
        from config.api_doc_coverage import endpoints_from_docs, endpoints_from_urlconf

        real = endpoints_from_urlconf()
        stale = sorted(set(endpoints_from_docs()) - real)
        self.assertEqual(
            stale, [],
            "以下文档信息行在 URLconf 中已不存在,请删除或修正:\n" +
            "\n".join(f"  {m} {p}" for m, p in stale))
```

- [ ] **Step 2: 跑门禁**

```bash
cd D:/pycharmproject/chat_app/chatapp
python manage.py test config.tests.ApiDocsCoverageTests -v 2
```

Expected:2 个用例 PASS

- [ ] **Step 3: 破坏性验证(证明它真的会红)**

```bash
cd D:/pycharmproject/chat_app/chatapp
# 临时把 auth.md 的一行信息行注释掉
sed -i 's|^> `POST` `/api/v1/auth/sms/send`|<!-- 临时破坏 -->|' ../docs/api/auth.md
python manage.py test config.tests.ApiDocsCoverageTests -v 2
```

Expected:FAIL,报错信息含 `POST /api/v1/auth/sms/send`

```bash
# 再验证反向检测:造一条不存在的接口信息行
echo '> `GET` `/api/v1/no/such` · 需要鉴权 · 无额外限流' >> ../docs/api/auth.md
python manage.py test config.tests.ApiDocsCoverageTests -v 2
```

Expected:FAIL,报错信息含 `/api/v1/no/such`

```bash
# 恢复两处破坏并确认回绿
git checkout -- ../docs/api/auth.md
python manage.py test config.tests.ApiDocsCoverageTests -v 2
```

Expected:2 个用例 PASS(用完 `git checkout` 前确保 auth.md 已提交,即 Task 3 的 commit)

- [ ] **Step 4: 跑 config 全量 + 提交**

```bash
python manage.py test config -v 1
git add chatapp/config/tests.py
git commit -m "test(config): ApiDocsCoverageTests 门禁——32 接口双向比对(漏写/残留即红)"
```

---

### Task 10: 纪律落条 + 全量回归 + 合分支

**Files:**
- Modify: `CLAUDE.md`(「文档导航」段、「核心契约与纪律」段)
- Modify: `docs/pitfalls/README.md`(末尾导航行)

- [ ] **Step 1: 改 `CLAUDE.md`**

在「文档导航(按需读取)」段末尾补一句:

```markdown
接口文档(对外交付级,腾讯云风格)→ [docs/api/README.md](docs/api/README.md)。
```

在「核心契约与纪律」列表末尾追加一条:

```markdown
- **接口文档**:`docs/api/` 是接口的对外交付文档;新增/修改/删除任何 `/api/v1` 接口,**同一次改动内**必须同步更新对应分册;`python manage.py test` 会跑 `ApiDocsCoverageTests` 双向比对,漏写即红。模板与维护规则见 `docs/api/README.md`
```

- [ ] **Step 2: 改 `docs/pitfalls/README.md` 末行**

把末尾那行改为:

```markdown
另:设计与计划在 `docs/superpowers/{specs,plans}/`;UI 规范在 `specs/2026-09-15-ui-design-language-design.md`(强制);接口文档在 [`../api/README.md`](../api/README.md)。
```

- [ ] **Step 3: 全量回归**

```bash
cd D:/pycharmproject/chat_app/chatapp
python manage.py test -v 1
```

Expected:全绿——基线 327 个用例 + 本计划新增 6 个(检查模块 4 + 门禁 2),约 333 通过、**0 失败**(以实际输出为准,只认「0 失败」)

- [ ] **Step 4: 提交文档与纪律**

```bash
cd D:/pycharmproject/chat_app
git add CLAUDE.md docs/pitfalls/README.md
git commit -m "docs: 接口文档纪律落条——CLAUDE.md 强制条目 + 导航;docs/api 体系交付完成"
```

- [ ] **Step 5: 合回 master 并推送(用户既定收尾习惯)**

```bash
git checkout master
git merge --ff-only docs/api-docs
git branch -d docs/api-docs
git push origin master
```

- [ ] **Step 6: 收尾核对**

```bash
cd chatapp && python manage.py test config 2>&1 | tail -3
git log --oneline -8
ls ../docs/api
```

Expected:`docs/api` 下 10 个 md 文件齐;git log 看到本计划 8 个提交;`master` 与 origin 同步

---

## 验收清单(取自 spec §8)

- [ ] `ApiDocsCoverageTests` 绿;`python manage.py test` 全量绿(基线 327 不回归)
- [ ] 抽查 3 个接口:照文档原文复制 curl 执行,实际结果与文档一致
- [ ] `docs/api/README.md` 一览表与 spec §2 清单一致(32 行)
- [ ] CLAUDE.md 纪律条目与「文档导航」「docs/pitfalls/README.md」导航更新完成
- [ ] 前端未改动(`flutter analyze` 不受影响)
