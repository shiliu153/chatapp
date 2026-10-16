# 后端 Python 注释规范化(腾讯风格)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> 本项目全局约定:**一律内联执行,不派发子 agent**(见 `~/.dsh/AGENTS.md`)。

**Goal:** 把 `chatapp/` 下全部 Python 代码的注释统一到腾讯系 Python 规范——模块 docstring 作文件头、函数 docstring 结构化(`Args`/`Returns`/`Raises`)、行内注释去口语化去装饰符号——并用 AST 门禁锁死,防止回潮。

**Architecture:** 先立规范文档(单一事实来源),再按 Django app 分批改写;每批用一个**纯标准库**的 AST 检查脚本 `config/comment_coverage.py` 验收(不依赖 Django,秒级出结果);全部分批完成后,把该脚本挂成 Django 测试门禁,与既有 `ApiDocsCoverageTests` 并列。

**Tech Stack:** Python 3.10(conda 环境 `Django`)、Django 5.2、`ast` + `tokenize` 标准库。

---

## Global Constraints

以下约束对**每个任务**都生效:

- **只改注释,不改代码。** 禁止改函数签名(包括补类型注解)、禁止改逻辑、禁止改字符串字面量的内容、禁止重排 import。改注释时若发现顺手能修的代码问题,**记到 plan 末尾的「顺带发现」一节**,不在本批次内动手。
- **语言风格:** 全部中文书面语,中文全角标点(`,。();:「」`),句末带句号。
- **验证命令(cwd = `chatapp/`,Python 用 `C:\Users\20157\anaconda3\envs\Django\python.exe`):**
  - 缺口检查:`python config/comment_coverage.py --app <app>` → 必须输出「无缺口」
  - 回归测试:`python manage.py test <app>` → 必须 OK(前置:Redis 在跑,`docker ps` 可见 `chatapp-redis`)
- **豁免范围:** 0 字节文件(如空 `__init__.py`)、`migrations/` 目录、`test_*` 函数与方法。
- **基线(动手前已实测):** `python manage.py test` = `Ran 360 tests in 38.474s` / `OK`;`flutter`/`web` 本批次不碰。
- **不动 `docs/api/`:** 接口文档由 `ApiDocsCoverageTests` 单独门禁,本次只改代码注释。
- 每个任务独立提交,提交信息用 `docs:` 前缀(本次改动不产生行为变化)。

---

## 规范正文(所有任务共同遵守)

> Task 0 会把下面这节原样落到 `docs/standards/python.md`。执行任务时若对某条规则拿不准,**以本节为准**,不要自行发明新格式。

### 0. 一句话说清「腾讯方式」落到 Python 是什么

腾讯的公开规范里,与本项目相关的是三条线:

| 来源 | 原始形态 | 本项目落地 |
|---|---|---|
| 腾讯后台/C++ 规范的文件头块 | `@file` / `@brief` / `@author` / `@date` / `@note` | 换成 Python 的**模块 docstring**:一句话职责 + 可选小节 |
| 腾讯 Python 规范(以 Google Python Style Guide 为基础) | 模块/类/函数三级 docstring,函数用 `Args`/`Returns`/`Raises` | **结构化函数 docstring**(本项目目前 118 个 docstring 里 0 个用过结构化小节,这是最大缺口) |
| AlloyTeam 前端规范「注释解释为什么,不解释是什么」 | 行内注释只写非显然的决策依据 | 行内注释**去口语化、去 emoji、去内部编号引用**,保留技术结论 |

**不引入** `@author` / `@date`(git 已有作者与时间,写进文件头会腐烂,且多人协作时必然过期)。**不引入** ruff/black 等格式化工具(会把本次 diff 从「注释行」放大成「全文件」,单独立项)。

### 1. 模块 docstring(文件头)

```python
"""<一句话职责:本模块提供什么、给谁用>。

<可选:2~4 行补充说明,讲清它在系统中的位置与边界。>

设计要点:
    1. <关键决策及原因>;
    2. <关键决策及原因>。

注意事项:
    - <前置条件、易踩的坑、调用约束>。

关联文档:
    - 接口契约:docs/api/<分册>.md
    - 踩坑记录:docs/pitfalls/<分册>.md
"""
```

取舍规则:

- **只写有内容的小节。** 一句话已说清的小模块(`apps.py`、`urls.py`、纯常量模块),只留首行。
- `设计要点` 回答「为什么这么设计」,`注意事项` 回答「用错了会怎样」,两者不要互相搬运。
- `关联文档` 只在**确有**对应文档时写;路径必须真实存在,不臆造。
- 首行不以「本模块」「该文件」开头,直接说职责。
- **原注释里的信息不能丢。** 例如 `im/im_client` 那类「全项目唯一 import 腾讯 SDK 的文件」属于设计约束,必须原样保留为 `设计要点` 条目。

### 2. 函数 docstring

```python
def issue_code(phone: str) -> str:
    """生成并存储验证码。

    短信入队由调用方负责(见 ``views.sms_send``);本函数只负责限流、
    生成、落库三步。

    Args:
        phone: 手机号,同时作为发送间隔限流的键。

    Returns:
        本次生成的 6 位验证码;开发模式下固定为 ``settings.SMS_DEV_CODE``。

    Raises:
        SmsSendTooFrequent: 距上次发送不足 ``SMS_RESEND_INTERVAL`` 秒。
    """
```

规则:

- 首行**一句话动宾结构**,句末 `。`,不写「本函数」「该方法」。
- 首行与后续小节之间**空一行**。
- `Args:` 每个参数一行,格式 `参数名: 说明。`。类型已在类型注解里,**不重复写类型**。
- `Returns:` 仅在返回值语义非显然时写;返回 `None` 时省略整节。
- `Raises:` 只列**本函数主动抛出**的异常(不含被调用方穿透上来的)。
- **私有函数**(`_` 前缀)、`@property`、`@override` 装饰的方法:**允许只写首行**,不强制 `Args`/`Returns`。
- **Django 视图**:首行末尾注明对应接口,格式 `(GET /api/v1/discovery/candidates)`。
- **Django Model 的字段**:字段语义不显然时用行内注释,不塞进类 docstring。
- **测试用例**(`test_*`):豁免。用例名即文档。

### 3. 类 docstring

- 一句话职责。Django Model 额外用 `Attributes:` 列出**语义不显然**的字段(如状态机取值、派生属性)。
- `Meta` 内部类、`AppConfig` 子类也要求一句话。
- 测试类豁免(由测试模块头统一说明覆盖范围)。

### 4. 行内注释

- **禁止 emoji 与装饰符号**:`⚠️`、`🔴`、`✅`、`❌` 一律改为 `注意:` 起头。
- **禁止口语词**:别/坑/够用/我们/压根/悄悄/顺手/其实/干脆/偷懒/踩… 改为书面语。
- **禁止内部编号引用**:`spec §13`、`规则 §5.1` 改为 `详见 docs/...` 或直接删除。
- 只解释「为什么」,不解释「是什么」(代码已自明)。
- 统一 `# ` 前缀 + 空格;中文句末加句号。
- 分节分隔线保留 `# --- 说明 ---` 形式(`config/settings.py` 已在用)。
- **行内注释全后端仅 237 行,其中需改写的只有 13 行**(见 Task 0 的清单),不要顺手大改无关注释。

### 5. 门禁规则(AST 判定)

**强制**(不满足即测试红):

1. 非空 `.py` 文件(`migrations/` 除外)必须有模块 docstring;
2. 每个 `FunctionDef` / `AsyncFunctionDef` / `ClassDef` 必须有 docstring,除 `test_*` 名称外;
3. 模块 docstring 与函数/类 docstring 中**不得出现 emoji 或 `⚠` 类装饰符号**。

**只报告不拦截**(写成 warning 输出,不进断言):

4. 口语词黑名单命中项 —— 该黑名单会有误报(例如「兜底」在技术语境里是合法用词),做成硬门禁会逼着后人写 `# noqa`,反而降低规范权威性。人工在 review 时看。

**明确不检查:**

5. `Args`/`Returns`/`Raises` 小节是否齐全 —— AST 无法判断「这个函数该不该有 Args 节」,强做必然误报。靠 review + 本规范文档约束。

---

## 工作量基线(已实测,任务划分依据)

对 `chatapp/` 做 AST 普查(排除 `migrations/`、`__pycache__`),**检查脚本口径**下的真实缺口:

| 范围 | 文件 | 模块头缺失 | 符号 docstring 缺失 | 装饰符号 | 小计 |
|---|---|---|---|---|---|
| 生产代码 | 94 | 57 | 275 | 5 | **337** |
| 测试代码 | 9 | 9 | 96 | 0 | **105** |
| **合计** | 103 | **66** | **371** | **5** | **442** |

按 app 拆分的生产代码缺口(即 Task 1~8 各自的验收目标):

| app | 模块头 | 符号 | 小计 | 对应任务 |
|---|---|---|---|---|
| `config` | 3 | 15 | 18 | Task 1 |
| `accounts` | 9 | 45 | 54 | Task 2 |
| `users` | 8 | 54 | 62 | Task 3 |
| `discovery` | 8 | 24 | 32 | Task 4 |
| `im` | 5 | 36 | 41 | Task 5 |
| `moderation` | 9 | 35 | 44 | Task 6 |
| `feed` | 7 | 42 | 49 | Task 7 |
| `ops` | 6 | 24 | 30 | Task 8 |
| `notifications` | 2 | 5 | 7 | Task 8 |
| **合计** | **57** | **280** | **337** | — |

测试代码的 105 处缺口(9 模块头 + 96 符号)全部归 Task 9。

> **⚠️ 计划修正记录(2026-10-17,执行 Task 0 时发现):**
> 本计划初稿在 Task 0 Step 3 写的预期是「336 处 = 57 + 185 + 94」,**这个数字是错的**——
> 它只统计了生产代码,完全漏掉了测试文件的 9 个模块头与 96 处符号缺口。
> 真实基线是 **442 处**。同时,初稿的豁免规则会在测试代码里强制 54 个 `setUp` 与 10 处
> 函数内闭包(`fake_request`、`FakeTask` 这类 3 行打桩)补 docstring,属于本计划自己
> 反对过的「纯噪音」。因此豁免规则已扩展(见 `docs/standards/python.md` §6):
> 追加豁免**测试生命周期钩子**(`setUp`/`tearDown`/`setUpClass`/`tearDownClass`/`setUpTestData`)
> 与**嵌套在函数体内的函数与类**。两条新规则均按**名称与嵌套形态**判定,不引入文件名特判。

需改写的行内注释 **13 行**、docstring 内装饰符号 **8 处**(精确行号见 Task 0)。

**关键判断一:测试代码不补 `test_*` 方法的 docstring。** 451 个测试方法补 docstring 是纯噪音,且用例名已是完整句子。这与腾讯/Google 规范对测试的豁免一致。

**关键判断二:测试类仍然要写 docstring。** 一个测试类就是一个场景分组(`ErrorEnvelopeTests`、`CacheBackendTests`…),给它一行「这个类覆盖什么」的说明价值很高、成本极低(共 66 个待补),而且**让门禁规则保持统一**——检查器只需豁免 `test_*` 名称,不必再按文件名判断是不是测试文件。基于文件名的特判是门禁脚本最容易出错的地方,不值得为省 66 行注释引入。

因此测试代码的要求是:**模块头 + 测试类 docstring + 非 `test_*` 辅助函数 docstring**,唯独豁免 `test_*` 函数本身。

---

## Task 0: 规范文档 + 缺口检查脚本

**Files:**
- Create: `docs/standards/README.md`
- Create: `docs/standards/python.md`
- Create: `chatapp/config/comment_coverage.py`
- Modify: `chatapp/config/tests.py`(仅本任务**不加**门禁,只加脚本自身的单元测试)

**Interfaces:**
- Produces:
  - `config/comment_coverage.py::iter_target_files(root: Path) -> Iterator[Path]`
  - `config/comment_coverage.py::check_file(path: Path) -> list[str]`(返回缺口描述,空列表表示通过)
  - `config/comment_coverage.py::find_problems(root: Path | None = None, app: str | None = None) -> list[str]`
  - `config/comment_coverage.py::find_tone_warnings(root: Path | None = None) -> list[str]`
  - CLI:`python config/comment_coverage.py [--app <name>] [--warnings]`,通过时打印 `无缺口`,有缺口时逐行打印并以退出码 1 结束
- 后续 Task 1~10 全部依赖这些签名,不要改名。

- [ ] **Step 1: 写规范文档**

把上文「规范正文」第 0~5 节原样复制到 `docs/standards/python.md`,并在文件末尾补一节「正反例」,内容为下面这份完整的 golden sample。

**正例(`accounts/services.py` 的目标形态)**——注意 `_sent_key` **保持原签名 `def _sent_key(phone):` 不变**,只加 docstring:

```python
"""短信验证码的生成、限流与校验。

验证码本身存在 Redis(见 ``sms_codes``);真实短信发送由调用方入队 Celery
任务完成,响应路径不做任何第三方网络调用。

关联文档:
    - 接口契约:docs/api/auth.md
"""

import logging
import random

from django.conf import settings
from django.core.cache import cache

from . import sms_codes
from .exceptions import SmsCodeExpired, SmsCodeWrong, SmsLocked, SmsSendTooFrequent

logger = logging.getLogger(__name__)


def _sent_key(phone):
    """拼出该手机号最近一次发送的限流键。"""
    return f"sms:send:{phone}"


def issue_code(phone: str) -> str:
    """生成并存储验证码。

    短信入队由调用方负责(见 ``views.sms_send``);本函数只负责限流、
    生成、落库三步。

    Args:
        phone: 手机号,同时作为发送间隔限流的键。

    Returns:
        本次生成的 6 位验证码;开发模式下固定为 ``settings.SMS_DEV_CODE``。

    Raises:
        SmsSendTooFrequent: 距上次发送不足 ``SMS_RESEND_INTERVAL`` 秒。
    """
    if not cache.add(_sent_key(phone), 1, settings.SMS_RESEND_INTERVAL):
        raise SmsSendTooFrequent(wait=settings.SMS_RESEND_INTERVAL)
    code = settings.SMS_DEV_CODE if settings.SMS_DEV_MODE else f"{random.randint(0, 999999):06d}"
    sms_codes.store(phone, code)
    logger.info("[开发模式] 验证码 phone=%s code=%s", phone, code)
    return code


def rollback_send(phone: str) -> None:
    """短信任务入队失败时回滚。

    删掉限流占位与验证码,让用户能立刻重试(见 ``views.sms_send`` 的异常分支)。

    Args:
        phone: 手机号。
    """
    cache.delete(_sent_key(phone))
    sms_codes.delete(phone)


def check_code(phone: str, code: str) -> None:
    """校验验证码,成功即通过。

    含 60 秒重放窗口内的重复校验:窗口内重复提交同一个码仍算成功。

    Args:
        phone: 手机号。
        code: 用户提交的 6 位验证码。

    Raises:
        SmsCodeExpired: 验证码已过期或不存在。
        SmsCodeWrong: 验证码错误。
        SmsLocked: 连错次数超限,账号被临时锁定。
    """
    result = sms_codes.verify(phone, code)
    if result is sms_codes.CodeResult.EXPIRED:
        raise SmsCodeExpired()
    if result is sms_codes.CodeResult.WRONG:
        raise SmsCodeWrong()
    if result in (sms_codes.CodeResult.LOCKED, sms_codes.CodeResult.JUST_LOCKED):
        raise SmsLocked(wait=settings.SMS_LOCK_TTL)
```

**反例(禁止出现)**:

```python
# ⚠️ 别用 @装饰器:celery 的 Signal.connect 行为不一致        ← emoji + 口语
def _user(user_id):                                          ← 缺 docstring
    """🔴 参数是 im_user_id 不是 user_id,见 spec §13"""      ← emoji + 内部编号引用
    ...
def candidates(request):                                     ← 缺 docstring
    # order_by("?") 数据量大时会慢,MVP 阶段够用              ← 口语(「够用」)
    ...
```

再写 `docs/standards/README.md`:一节索引(说明 `python.md` 是本项目 Python 注释的单一事实来源、门禁在 `config/comment_coverage.py`,后续 Dart/TypeScript 分册待立项)+ 一节「三条通用原则」(注释解释为什么;信息不丢失;规范由门禁而非自觉维持)。

- [ ] **Step 2: 写缺口检查脚本**

创建 `chatapp/config/comment_coverage.py`。要点:

- **纯标准库**,不 import Django(这样能直接 `python config/comment_coverage.py` 秒级运行,不必等测试框架启动)。
- 项目根用 `Path(__file__).resolve().parents[1]` 得到 `chatapp/`。
- 跳过 `migrations/`、`__pycache__`;跳过内容为空白的文件。
- 用 `ast.parse` 遍历,判定规则见「规范正文 §5」。
- emoji 检测正则:`re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u26A0]")`。
- 口语词黑名单:`re.compile(r"(别用|别在|别把|别出|够用|我们|压根|悄悄|顺手|其实|干脆|偷懒|坑)")`。

**完整实现**(照抄,不要改写):

```python
"""注释规范门禁:模块头与函数/类 docstring 的覆盖率检查。

判定规则见 docs/standards/python.md。本模块只依赖标准库,可直接命令行运行:

    python config/comment_coverage.py              # 全量检查
    python config/comment_coverage.py --app im     # 只检查某个 app
    python config/comment_coverage.py --warnings   # 附带口语词提示(不拦截)
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
import tokenize
from collections.abc import Iterator
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"migrations", "__pycache__"}

DECORATION_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u26A0]")
CASUAL_RE = re.compile(r"(别用|别在|别把|别出|够用|我们|压根|悄悄|顺手|其实|干脆|偷懒|坑)")


def _display_path(path: Path) -> str:
    """给出门禁报错用的展示路径。

    Args:
        path: 待展示的文件路径。

    Returns:
        相对 chatapp/ 的路径;不在其下时(单元测试用临时目录)降级为文件名。
    """
    try:
        return path.relative_to(BACKEND_ROOT).as_posix()
    except ValueError:
        return path.name


def iter_target_files(root: Path = BACKEND_ROOT, app: str | None = None) -> Iterator[Path]:
    """产出需要检查的 .py 文件。

    跳过 migrations、缓存目录与空白文件(空的 __init__.py 无内容可写)。

    Args:
        root: 后端根目录,默认 chatapp/。
        app: 只检查该 app 子目录;None 表示全量。

    Yields:
        待检查的文件路径,按路径升序。
    """
    base = root / app if app else root
    for path in sorted(base.rglob("*.py")):
        if SKIP_DIRS & set(path.parts):
            continue
        if not path.read_text(encoding="utf-8").strip():
            continue
        yield path


def check_file(path: Path) -> list[str]:
    """检查单个文件的注释覆盖情况。

    Args:
        path: 待检查的 .py 文件。

    Returns:
        缺口描述列表,格式 ``相对路径:行号 说明``;空列表表示通过。
    """
    problems: list[str] = []
    rel = _display_path(path)
    tree = ast.parse(path.read_text(encoding="utf-8"))

    module_doc = ast.get_docstring(tree)
    if module_doc is None:
        problems.append(f"{rel}:1 缺少模块 docstring")
    elif DECORATION_RE.search(module_doc):
        problems.append(f"{rel}:1 模块 docstring 含装饰符号")

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
            if name.startswith("test_"):
                continue                      # 测试用例豁免:用例名即文档
            doc = ast.get_docstring(node)
            if doc is None:
                problems.append(f"{rel}:{node.lineno} {name} 缺少 docstring")
            elif DECORATION_RE.search(doc):
                problems.append(f"{rel}:{node.lineno} {name} 的 docstring 含装饰符号")
    return problems


def _iter_comments(path: Path) -> Iterator[tuple[int, str]]:
    """产出文件中的 # 注释。

    Args:
        path: 待扫描的 .py 文件。

    Yields:
        ``(行号, 注释原文)``;无法 tokenize 时产出空序列。
    """
    with path.open(encoding="utf-8") as handle:
        try:
            for token in tokenize.generate_tokens(handle.readline):
                if token.type == tokenize.COMMENT:
                    yield token.start[0], token.string
        except tokenize.TokenError:
            return


def find_problems(root: Path = BACKEND_ROOT, app: str | None = None) -> list[str]:
    """汇总全部注释缺口。

    Args:
        root: 后端根目录,默认 chatapp/。
        app: 只检查该 app 子目录;None 表示全量。

    Returns:
        缺口描述列表;空列表表示全部通过。
    """
    problems: list[str] = []
    for path in iter_target_files(root, app):
        problems.extend(check_file(path))
    return problems


def find_tone_warnings(root: Path = BACKEND_ROOT, app: str | None = None) -> list[str]:
    """汇总口语词命中项(只提示,不参与门禁断言)。

    黑名单会有误报(如「兜底」在技术语境里合法),因此只报告不拦截。

    Args:
        root: 后端根目录,默认 chatapp/。
        app: 只检查该 app 子目录;None 表示全量。

    Returns:
        形如 ``相对路径:行号 口语词「命中词」`` 的提示列表。
    """
    warnings: list[str] = []
    for path in iter_target_files(root, app):
        rel = _display_path(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node)
                match = CASUAL_RE.search(doc) if doc else None
                if match:
                    warnings.append(
                        f"{rel}:{getattr(node, 'lineno', 1)} 口语词「{match.group(1)}」")
        for lineno, text in _iter_comments(path):
            match = CASUAL_RE.search(text)
            if match:
                warnings.append(f"{rel}:{lineno} 口语词「{match.group(1)}」")
    return warnings


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    Args:
        argv: 参数列表;None 表示取 sys.argv。

    Returns:
        进程退出码:0 表示通过,1 表示存在缺口。
    """
    parser = argparse.ArgumentParser(description="检查 Python 注释规范覆盖情况")
    parser.add_argument("--app", default=None, help="只检查指定 app 子目录")
    parser.add_argument("--warnings", action="store_true",
                        help="附带口语词提示(不拦截)")
    args = parser.parse_args(argv)

    if args.warnings:
        for warning in find_tone_warnings(app=args.app):
            print(f"[提示] {warning}")

    problems = find_problems(app=args.app)
    if problems:
        print(f"发现 {len(problems)} 处注释缺口:")
        for problem in problems:
            print(f"  {problem}")
        return 1

    print("无缺口")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**注意两处容易写错的地方:**

1. `check_file` 里**不能**直接写 `path.relative_to(BACKEND_ROOT)` —— Step 4 的单元测试传的是临时目录路径,会抛 `ValueError`;必须走 `_display_path()` 降级。
2. `iter_target_files` 的 `SKIP_DIRS & set(path.parts)` 依赖 `path` 是**绝对路径**(`rglob` 在绝对 `base` 下产出的就是绝对路径),因此不能用相对路径调用。

- [ ] **Step 3: 跑脚本,记录当前缺口基线**

Run:
```bash
cd chatapp
python config/comment_coverage.py            # 期望:报 442 处缺口,退出码 1
python config/comment_coverage.py --app im   # 期望:报 41 处(im 的生产代码)
```

Expected: 缺口总数 = 66(模块头)+ 371(符号 docstring)+ 5(装饰符号)= **442**,与
「工作量基线」表一致;且**输出里不应出现 `config/comment_coverage.py` 自身**(脚本必须自洽)。

> **注意:** 本计划初稿在这里写的预期是 336,那是错的(只算了生产代码)。真实基线 442。
> 若实际数字与 442 不符,**先查脚本判定逻辑**,不要开始改写。

- [ ] **Step 4: 给脚本写单元测试**

在 `chatapp/config/tests.py` 追加一个测试类(不要动既有类):

```python
class CommentCoverageLogicTests(SimpleTestCase):
    """注释门禁检查模块自身的单元测试(用临时目录,不依赖真实代码)。"""

    def _write(self, tmp, body):
        path = Path(tmp) / "demo.py"
        path.write_text(body, encoding="utf-8")
        return path

    def test_clean_file_passes(self):
        from config.comment_coverage import check_file

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, '"""演示模块。"""\n\n\ndef foo() -> None:\n'
                                    '    """做一件事。"""\n')
            self.assertEqual(check_file(path), [])

    def test_missing_module_docstring_is_reported(self):
        from config.comment_coverage import check_file

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "x = 1\n")
            self.assertTrue(any("缺少模块 docstring" in p for p in check_file(path)))

    def test_missing_function_docstring_is_reported(self):
        from config.comment_coverage import check_file

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, '"""演示模块。"""\n\n\ndef foo() -> None:\n    pass\n')
            self.assertTrue(any("foo 缺少 docstring" in p for p in check_file(path)))

    def test_missing_class_docstring_is_reported(self):
        from config.comment_coverage import check_file

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, '"""演示模块。"""\n\n\nclass Foo:\n    pass\n')
            self.assertTrue(any("Foo 缺少 docstring" in p for p in check_file(path)))

    def test_test_functions_are_exempt(self):
        from config.comment_coverage import check_file

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, '"""演示模块。"""\n\n\ndef test_foo():\n    pass\n')
            self.assertEqual(check_file(path), [])

    def test_lifecycle_hooks_are_exempt(self):
        """setUp 等框架钩子豁免(全项目 54 处,补 docstring 是噪音)。"""
        from config.comment_coverage import check_file

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, '"""演示模块。"""\n\n\nclass FooTests:\n'
                                    '    """演示测试类。"""\n\n'
                                    "    def setUp(self):\n        pass\n\n"
                                    "    def tearDown(self):\n        pass\n")
            self.assertEqual(check_file(path), [])

    def test_nested_functions_are_exempt(self):
        """函数体内的闭包与局部类豁免(测试里大量 3 行打桩属于此类)。"""
        from config.comment_coverage import check_file

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, '"""演示模块。"""\n\n\ndef outer():\n'
                                    '    """外层函数。"""\n\n'
                                    "    def fake_request():\n        pass\n\n"
                                    "    class FakeTask:\n        pass\n\n"
                                    "    return fake_request, FakeTask\n")
            self.assertEqual(check_file(path), [])

    def test_top_level_helper_still_requires_docstring(self):
        """豁免不能过宽:非 test_ 的顶层辅助函数仍必须有 docstring。"""
        from config.comment_coverage import check_file

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, '"""演示模块。"""\n\n\ndef _make_user():\n    pass\n')
            self.assertTrue(any("_make_user 缺少 docstring" in p for p in check_file(path)))

    def test_decoration_symbol_is_reported(self):
        from config.comment_coverage import check_file

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, '"""演示模块。⚠️"""\n')
            self.assertTrue(any("含装饰符号" in p for p in check_file(path)))

    def test_display_path_falls_back_outside_backend_root(self):
        """临时目录不在 chatapp/ 下,展示路径必须降级为文件名而不是抛 ValueError。"""
        from config.comment_coverage import check_file

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "x = 1\n")
            self.assertTrue(all(p.startswith("demo.py:") for p in check_file(path)))
```

- [ ] **Step 5: 跑测试确认全绿**

Run: `python manage.py test config`
Expected: OK(`config/tests.py` 原有 19 个用例 + 本任务新增 10 个)

- [ ] **Step 6: 提交**

```bash
git add docs/standards/ chatapp/config/comment_coverage.py chatapp/config/tests.py
git commit -m "docs: 立 Python 注释规范(腾讯风格)+ AST 缺口检查脚本"
```

---

## Task 1: `config/` —— 基础设施层

**Files(13 个生产文件,排除 `tests.py`):**

| 文件 | 行 | 模块头 | 函数 | 类 | 需处理 |
|---|---|---|---|---|---|
| `config/__init__.py` | 7 | 缺 | 0/0 | 0/0 | 补模块头 |
| `config/api_urls.py` | 18 | 缺 | 0/0 | 0/0 | 补模块头 |
| `config/exceptions.py` | 36 | 缺 | 1/2 | 0/0 | 补模块头 + 1 函数 |
| `config/celery.py` | 44 | 有 | 1/4 | 0/0 | 改模块头 + 3 函数 + **行内 22 行 emoji/口语** |
| `config/settings.py` | 308 | 有 | 0/0 | 0/0 | 改模块头 + **行内 133、270 行 emoji** |
| `config/middleware.py` | 33 | 有 | 0/2 | 0/1 | 2 函数 + 1 类 |
| `config/request_id.py` | 22 | 有 | 0/3 | 1/1 | 3 函数 + 1 类 |
| `config/error_codes.py` | 8 | 有 | 0/0 | 0/0 | 仅核对 |
| `config/pagination.py` | 8 | 有 | 0/0 | 0/1 | 1 类 |
| `config/api_doc_coverage.py` | 88 | 有 | 2/7 | 0/0 | 5 函数 |
| `config/urls.py` / `asgi.py` / `wsgi.py` | 15/16/16 | 有 | 0/0 | 0/0 | 仅核对 |
| `manage.py`(项目根) | 22 | 有 | 1/1 | 0/0 | 仅核对(已达标) |

**Interfaces:**
- Consumes: `config/comment_coverage.py::check_file`、`find_problems`(Task 0)
- Produces: 无(纯注释改动)

- [ ] **Step 1: 通读该 app 全部文件**

Run: `python config/comment_coverage.py --app config`
Expected: 列出本 app 全部缺口(约 3 + 11 + 1 = 15 行),作为本任务的验收清单。

- [ ] **Step 2: 改写模块 docstring**

按「规范正文 §1」逐个改写。要点提示:

- `config/settings.py` 的模块头要说清三件事:配置来源(`chatapp/.env`)、`TESTING` 分支的意义、`BROKER_URL` 不能带 `CELERY_` 前缀的原因。原文件第 131 行的分节线 `# --- Redis / 缓存 / Celery ---` 保留。
- `config/celery.py` 必须保留原第 22 行那条结论:「注册信号用 `signal.connect(函数)` 显式调用,不能用 `@装饰器`」,改写成 `注意事项:` 条目并去掉 `⚠️`。
- `config/api_doc_coverage.py` 已有一行模块头,按模板扩成「职责 + 设计要点(双向比对)」,不要推翻重写。

- [ ] **Step 3: 补函数与类 docstring**

按「规范正文 §2、§3」。`config/settings.py` 无函数,跳过。

- [ ] **Step 4: 改写行内注释**

本 app 的 3 处:

| 位置 | 现状 | 目标 |
|---|---|---|
| `config/celery.py:22` | `# ⚠️ 用 signal.connect(函数) 显式注册,别用 @装饰器:...` | `# 注意:注册信号必须用 signal.connect(函数) 显式调用,不能用 @装饰器——` (保留后半句原因) |
| `config/settings.py:133` | `# ⚠️ 环境变量必须叫 BROKER_URL:...` | `# 注意:环境变量必须叫 BROKER_URL。celery/app/utils.py 的 broker_url 属性...` |
| `config/settings.py:270` | `# ⚠️ 手测时用 runserver --noreload:...` | `# 手测时必须加 --noreload:autoreload 的两个进程会抢写同一文件。` |

`config/tests.py:37` 的 `⚠️` 归 Task 9 处理。

- [ ] **Step 5: 验收缺口清零**

Run: `python config/comment_coverage.py --app config`
Expected: `无缺口`

- [ ] **Step 6: 回归测试**

Run: `python manage.py test config`
Expected: OK(360 基线中 config 部分不变)

- [ ] **Step 7: 提交**

```bash
git add chatapp/config/
git commit -m "docs(config): 注释规范化(模块头/函数 docstring/去装饰符号)"
```

---

## Task 2: `accounts/` —— 鉴权与账号

**Files(14 个生产文件,排除 `tests.py`):**

| 文件 | 行 | 模块头 | 函数 | 类 | 需处理 |
|---|---|---|---|---|---|
| `accounts/views.py` | 128 | 缺 | 0/8 | 1/1 | 模块头 + 8 函数 |
| `accounts/services.py` | 41 | 缺 | 3/4 | 0/0 | 按 Task 0 的 golden sample 落地 |
| `accounts/sms_codes.py` | 83 | 有 | 0/7 | 0/0 | 7 函数 |
| `accounts/models.py` | 47 | 缺 | 1/4 | 0/2 | 模块头 + 3 函数 + 2 类 |
| `accounts/exceptions.py` | 45 | 缺 | 0/1 | 1/6 | 模块头 + 1 函数 + 5 类 |
| `accounts/authentication.py` | 23 | 有 | 0/1 | 0/1 | 1 函数 + 1 类 |
| `accounts/tokens.py` | 25 | 有 | 0/2 | 0/2 | 2 函数 + 2 类 |
| `accounts/serializers.py` | 19 | 缺 | 0/1 | 0/2 | 模块头 + 1 函数 + 2 类 |
| `accounts/throttles.py` | 20 | 缺 | 0/2 | 2/2 | 模块头 + 2 函数 |
| `accounts/admin.py` | 22 | 缺 | 0/0 | 0/1 | 模块头 + 1 类 |
| `accounts/apps.py` | 6 | 缺 | 0/0 | 0/1 | 模块头 + 1 类 |
| `accounts/urls.py` | 9 | 缺 | 0/0 | 0/0 | 模块头 |
| `accounts/management/commands/seed_fake_users.py` | 154 | 有 | 1/6 | 0/1 | 5 函数 + 1 类 + **行内 147 行 emoji** |
| `accounts/__init__.py` | 0 | 空 | — | — | 豁免 |

- [ ] **Step 1: 通读并取缺口清单**

Run: `python config/comment_coverage.py --app accounts`
Expected: 约 9 + 35 + 15 = 59 行缺口。

- [ ] **Step 2: 落地 `services.py` 为 golden sample**

直接采用 Task 0 规范文档里给出的完整形态(逐字),确认与文档一致。

- [ ] **Step 3: 改写其余文件模块 docstring**

重点:

- `accounts/views.py`:说明本模块提供哪些接口(发码/校验/刷新),并点出「响应路径不做第三方调用,短信走 Celery」。
- `accounts/models.py`:说明 `User` 是自定义用户模型、手机号是登录标识,并保留 `im_user_id` 属性「IM 账号 = `u{user_id}`」这条跨栈约定。
- `accounts/exceptions.py`:说明这是短信验证码相关的业务异常族,与 `config/exceptions.py` 的错误信封如何配合。

- [ ] **Step 4: 补函数与类 docstring**

按模板。`accounts/throttles.py` 的限流类要写清限流维度与阈值。

- [ ] **Step 5: 改写行内注释**

| 位置 | 处理 |
|---|---|
| `accounts/management/commands/seed_fake_users.py:147` | `# ⚠️ 月/日必须**不晚于今天**:...` → 去掉 `⚠️`,保留「否则 `calculate_age` 会算出 age-1」这条结论 |
| `accounts/authentication.py`、`accounts/models.py`、`accounts/views.py` 各 1 处口语 | 按 §4 改为书面语 |

- [ ] **Step 6: 验收 + 回归**

```bash
python config/comment_coverage.py --app accounts    # 期望:无缺口
python manage.py test accounts                      # 期望:OK
```

- [ ] **Step 7: 提交**

```bash
git add chatapp/accounts/
git commit -m "docs(accounts): 注释规范化(模块头/函数 docstring/去装饰符号)"
```

---

## Task 3: `users/` —— 资料、照片、在线状态

**Files(10 个生产文件,排除 `tests.py`):**

| 文件 | 行 | 模块头 | 函数 | 类 | 需处理 |
|---|---|---|---|---|---|
| `users/models.py` | 133 | 缺 | 3/11 | 0/8 | 模块头 + 8 函数 + 8 类 |
| `users/serializers.py` | 122 | 缺 | 0/9 | 2/13 | 模块头 + 9 函数 + 11 类 |
| `users/views.py` | 127 | 缺 | 1/7 | 0/0 | 模块头 + 6 函数 |
| `users/services.py` | 78 | 缺 | 5/6 | 0/0 | 模块头 + 1 函数 |
| `users/presence.py` | 66 | 有 | 4/5 | 0/0 | 1 函数 |
| `users/admin.py` | 60 | 缺 | 0/5 | 0/4 | 模块头 + 5 函数 + 4 类 |
| `users/throttles.py` | 10 | 缺 | 0/1 | 1/1 | 模块头 + 1 函数 |
| `users/urls.py` | 12 | 缺 | 0/0 | 0/0 | 模块头 |
| `users/apps.py` | 6 | 缺 | 0/0 | 0/1 | 模块头 + 1 类 |
| `users/__init__.py` | 0 | 空 | — | — | 豁免 |

- [ ] **Step 1: 取缺口清单** — `python config/comment_coverage.py --app users`(约 8 + 31 + 24 = 63 行)
- [ ] **Step 2: 改写模块 docstring** — 重点:
  - `users/models.py`:说明 `Profile` 与 `User` 的分工(账号 vs 资料)、`ProfileStatus` 的「完善」判定口径(昵称/性别/生日/城市/简介非空 + ≥1 张过审照片)、`birthday_bounds` 的年龄换算口径。
  - `users/presence.py`:必须保留「在线 = 120 秒内有认证请求(45 秒心跳)」这条定义,并说明它是**公开信息**、不依赖配对。
  - `users/views.py`:`DELETE /users/me` 是账号注销,要在模块头点出「立即硬删除 + 释放手机号」。
- [ ] **Step 3: 补函数与类 docstring** — 按模板。
- [ ] **Step 4: 改写行内注释** — `users/tests.py` 的两处归 Task 9;本 app 生产代码无 emoji,只处理 1 处口语。
- [ ] **Step 5: 验收 + 回归**

```bash
python config/comment_coverage.py --app users    # 期望:无缺口
python manage.py test users                      # 期望:OK
```

- [ ] **Step 6: 提交**

```bash
git add chatapp/users/
git commit -m "docs(users): 注释规范化(模块头/函数 docstring/去装饰符号)"
```

---

## Task 4: `discovery/` —— 候选与滑卡配对

**Files(12 个生产文件,排除 `tests.py`):**

| 文件 | 行 | 模块头 | 函数 | 类 | 需处理 |
|---|---|---|---|---|---|
| `discovery/views.py` | 122 | 缺 | 0/4 | 0/0 | 模块头 + 4 函数 + **行内 39、60 行口语** |
| `discovery/models.py` | 49 | 缺 | 1/4 | 0/5 | 模块头 + 3 函数 + 5 类 |
| `discovery/serializers.py` | 26 | 缺 | 0/1 | 0/3 | 模块头 + 1 函数 + 3 类 |
| `discovery/services.py` | 12 | 缺 | 1/1 | 0/0 | 模块头 |
| `discovery/admin.py` | 14 | 缺 | 0/0 | 0/2 | 模块头 + 2 类 |
| `discovery/throttles.py` | 10 | 缺 | 0/1 | 1/1 | 模块头 + 1 函数 |
| `discovery/urls.py` | 8 | 缺 | 0/0 | 0/0 | 模块头 |
| `discovery/apps.py` | 6 | 缺 | 0/0 | 0/1 | 模块头 + 1 类 |
| `discovery/management/commands/dev_reset_pair.py` | 50 | 有 | 0/3 | 0/1 | 3 函数 + 1 类 |
| `discovery/__init__.py`、`management/__init__.py`、`management/commands/__init__.py` | 0 | 空 | — | — | 豁免 |

- [ ] **Step 1: 取缺口清单** — `python config/comment_coverage.py --app discovery`(约 8 + 12 + 12 = 32 行)
- [ ] **Step 2: 改写模块 docstring** — 重点:
  - `discovery/views.py`:说明候选池的四条排除规则(自己/划过/已配对/已拉黑)与「只推有已过审照片的人」;保留原第 39 行「用子查询而非 JOIN,避免重复行与 distinct + 随机排序冲突」的结论(移到 `设计要点`)。
  - `discovery/services.py`:`notify_match` 的双方灰条语义。
- [ ] **Step 3: 补函数与类 docstring** — `Swipe` / `Match` 模型说明幂等性与唯一约束。
- [ ] **Step 4: 改写行内注释**

| 位置 | 现状 | 目标 |
|---|---|---|
| `discovery/views.py:39` | `# 有过审照片的人才进候选(用子查询而不是 JOIN,避免出重复行、也避免 distinct + 随机排序的坑)` | `# 只让有已过审照片的人进候选。用子查询而非 JOIN,避免产生重复行,也避免 distinct 与随机排序冲突。` |
| `discovery/views.py:60` | `# order_by("?") 在数据量大时会慢,MVP 阶段(几百人)够用,将来换成预计算随机列` | `# order_by("?") 在数据量大时性能下降。当前用户规模(数百人)可接受,后续改为预计算随机列。` |

- [ ] **Step 5: 验收 + 回归**

```bash
python config/comment_coverage.py --app discovery    # 期望:无缺口
python manage.py test discovery                      # 期望:OK
```

- [ ] **Step 6: 提交**

```bash
git add chatapp/discovery/
git commit -m "docs(discovery): 注释规范化(模块头/函数 docstring/去口语)"
```

---

## Task 5: `im/` —— 腾讯云 IM 集成

> 本 app 是全项目注释**信息密度最高**的一处(唯一 import 腾讯 REST 的地方、单设备踢人顺序、注销删号的任务参数例外)。改写时**信息只增不减**,这是本任务的核心风险点。

**Files(14 个生产文件,排除 `tests.py`):**

| 文件 | 行 | 模块头 | 函数 | 类 | 需处理 |
|---|---|---|---|---|---|
| `im/client.py` | 242 | 有 | 11/21 | 0/0 | 改模块头 + 10 函数 + **行内 112 行 emoji + 4 处 docstring emoji** |
| `im/tasks.py` | 175 | 有 | 6/14 | 0/0 | 改模块头 + 8 函数 + **2 处 docstring 装饰/口语** |
| `im/signature.py` | 55 | 有 | 1/5 | 0/0 | 改模块头(去口语)+ 4 函数 |
| `im/views.py` | 35 | 缺 | 0/1 | 0/0 | 模块头 + 1 函数 + **行内 24 行 emoji** |
| `im/management/commands/im_send.py` | 34 | 有 | 0/2 | 0/1 | 2 函数 + 1 类 |
| `im/management/commands/im_setup_system_account.py` | 21 | 有 | 0/1 | 0/1 | 1 函数 + 1 类 |
| `im/management/commands/im_sync_nicknames.py` | 24 | 有 | 0/1 | 0/1 | 1 函数 + 1 类 |
| `im/apps.py` | 6 | 缺 | 0/0 | 0/1 | 模块头 + 1 类 |
| `im/urls.py` | 7 | 缺 | 0/0 | 0/0 | 模块头 |
| `im/admin.py` | 3 | 缺 | 0/0 | 0/0 | 模块头 |
| `im/models.py` | 3 | 缺 | 0/0 | 0/0 | 模块头 |
| `im/__init__.py`、`management/__init__.py`、`management/commands/__init__.py` | 0 | 空 | — | — | 豁免 |

- [ ] **Step 1: 取缺口清单** — `python config/comment_coverage.py --app im`(约 5 + 27 + 4 = 36 行)
- [ ] **Step 2: 改写模块 docstring** — **必须逐条保留下列既有结论**:
  - `im/client.py`:`对外永不抛异常(失败返回 False 只记日志)`、`超时/重试口径`、`identifier 语义待真凭据实测`。
  - `im/tasks.py`:`im/client.py` 返回 False 时这里转异常,让 Celery 重试策略生效;`任务参数一律 user_id,任务内查库`。
  - `im/views.py`:踢旧会话必须在签发新签名**之前**完成的顺序约束。
  - `im/signature.py`:userSig 的生成口径与有效期。
- [ ] **Step 3: 补函数与类 docstring** — 重点:
  - `im/tasks.py::delete_account` 的 docstring 是**全项目唯一「任务参数不是 user_id」的例外**,必须完整保留原因(用户行已删除 → 任务内查库必为 None → 沿用 `_user()` 兜底会静默跳过、删号永不发生),只把 `🔴` 换成 `注意:`。
  - `im/client.py::ensure_account`、`set_profile_nick`、`set_profile_avatar`、`delete_account` 的 docstring 去掉装饰符号,保留业务语义。
- [ ] **Step 4: 改写行内注释**

| 位置 | 处理 |
|---|---|
| `im/client.py:112` | 去 `⚠️`,保留「`identifier` 是否必须管理员需用真凭据实测,与 sendmsg 的 60010 同类」 |
| `im/views.py:24` | 去 `⚠️`,保留「顺序不能反:踢必须发生在新会话建立之前,否则会把本机刚建的会话一起踢掉」 |
| `im/tasks.py:144`(`kick_pending` docstring)、`im/signature.py:1`(模块头) | 去口语,保留「正常路径由 `views.user_sig` 同步踢并清标记,本任务只覆盖 App 未登 IM 的情况」 |

- [ ] **Step 5: 验收 + 回归**

```bash
python config/comment_coverage.py --app im    # 期望:无缺口
python manage.py test im                      # 期望:OK
```

- [ ] **Step 6: 提交**

```bash
git add chatapp/im/
git commit -m "docs(im): 注释规范化(保留踢人顺序/删号参数例外等关键结论)"
```

---

## Task 6: `moderation/` —— 审核、举报、拉黑

**Files(11 个生产文件,排除 `tests.py`):**

| 文件 | 行 | 模块头 | 函数 | 类 | 需处理 |
|---|---|---|---|---|---|
| `moderation/models.py` | 79 | 缺 | 0/3 | 1/9 | 模块头 + 3 函数 + 8 类 |
| `moderation/serializers.py` | 42 | 缺 | 0/2 | 0/6 | 模块头 + 2 函数 + 6 类 |
| `moderation/services.py` | 63 | 缺 | 5/6 | 0/0 | 模块头 + 1 函数 |
| `moderation/admin.py` | 59 | 缺 | 0/7 | 2/3 | 模块头 + 7 函数 + 1 类 |
| `moderation/views.py` | 65 | 缺 | 0/3 | 0/0 | 模块头 + 3 函数 |
| `moderation/permissions.py` | 24 | 缺 | 0/1 | 1/1 | 模块头 + 1 函数 |
| `moderation/text_check.py` | 13 | 有 | 0/1 | 0/0 | 1 函数 |
| `moderation/throttles.py` | 10 | 缺 | 0/1 | 1/1 | 模块头 + 1 函数 |
| `moderation/urls.py` | 9 | 缺 | 0/0 | 0/0 | 模块头 |
| `moderation/apps.py` | 6 | 缺 | 0/0 | 0/1 | 模块头 + 1 类 |
| `moderation/__init__.py` | 0 | 空 | — | — | 豁免 |

- [ ] **Step 1: 取缺口清单** — `python config/comment_coverage.py --app moderation`(约 9 + 19 + 16 = 44 行)
- [ ] **Step 2: 改写模块 docstring** — 重点:封禁两级语义(`banned_light` 只禁滑卡 / `banned_heavy` 全域 403)、全局权限类自动覆盖新接口、白名单仅 `GET /users/me` 与 `GET /users/tags`;`blocked_user_ids` 被 discovery 复用的边界。
- [ ] **Step 3: 补函数与类 docstring** — 审核台相关的 Model 要写清状态流转。
- [ ] **Step 4: 改写行内注释** — 本 app 生产代码无 emoji/口语命中,只做一致性核对。
- [ ] **Step 5: 验收 + 回归**

```bash
python config/comment_coverage.py --app moderation    # 期望:无缺口
python manage.py test moderation                      # 期望:OK
```

- [ ] **Step 6: 提交**

```bash
git add chatapp/moderation/
git commit -m "docs(moderation): 注释规范化(模块头/函数 docstring)"
```

---

## Task 7: `feed/` —— 广场动态

**Files(8 个生产文件,排除 `tests.py`):**

| 文件 | 行 | 模块头 | 函数 | 类 | 需处理 |
|---|---|---|---|---|---|
| `feed/models.py` | 83 | 缺 | 0/5 | 1/10 | 模块头 + 5 函数 + 9 类 |
| `feed/serializers.py` | 88 | 缺 | 0/7 | 0/7 | 模块头 + 7 函数 + 7 类 |
| `feed/views.py` | 113 | 缺 | 0/8 | 0/0 | 模块头 + 8 函数 |
| `feed/services.py` | 53 | 缺 | 3/3 | 0/0 | 模块头 |
| `feed/throttles.py` | 38 | 缺 | 0/5 | 3/3 | 模块头 + 5 函数 |
| `feed/urls.py` | 12 | 缺 | 0/0 | 0/0 | 模块头 |
| `feed/apps.py` | 6 | 缺 | 0/0 | 0/1 | 模块头 + 1 类 |
| `feed/__init__.py` | 0 | 空 | — | — | 豁免 |

- [ ] **Step 1: 取缺口清单** — `python config/comment_coverage.py --app feed`(约 7 + 25 + 20 = 52 行)
- [ ] **Step 2: 改写模块 docstring** — 动态/评论/点赞的数据模型关系,配图数量与尺寸限制,点赞幂等口径。
- [ ] **Step 3: 补函数与类 docstring** — 按模板;`feed/views.py` 的视图首行注明接口路径。
- [ ] **Step 4: 改写行内注释** — `feed/tests.py:41` 的 `# 别把测试图片写进真 media/` 归 Task 9。
- [ ] **Step 5: 验收 + 回归**

```bash
python config/comment_coverage.py --app feed    # 期望:无缺口
python manage.py test feed                      # 期望:OK
```

- [ ] **Step 6: 提交**

```bash
git add chatapp/feed/
git commit -m "docs(feed): 注释规范化(模块头/函数 docstring)"
```

---

## Task 8: `ops/` + `notifications/` —— 审核台与通知后端

**Files(11 个生产文件):**

| 文件 | 行 | 模块头 | 函数 | 类 | 需处理 |
|---|---|---|---|---|---|
| `ops/views.py` | 296 | 缺 | 3/22 | 0/0 | 模块头 + 19 函数 |
| `ops/forms.py` | 9 | 缺 | 0/1 | 0/1 | 模块头 + 1 函数 + 1 类 |
| `ops/urls.py` | 34 | 缺 | 0/0 | 0/0 | 模块头 |
| `ops/decorators.py` | 16 | 缺 | 0/2 | 0/0 | 模块头 + 2 函数 |
| `ops/context_processors.py` | 14 | 缺 | 0/1 | 0/0 | 模块头 + 1 函数 |
| `ops/apps.py` | 6 | 缺 | 0/0 | 0/1 | 模块头 + 1 类 |
| `ops/__init__.py` | 0 | 空 | — | — | 豁免 |
| `notifications/backends.py` | 18 | 有 | 0/2 | 0/1 | 2 函数 + 1 类 |
| `notifications/tasks.py` | 8 | 缺 | 0/1 | 0/0 | 模块头 + 1 函数 |
| `notifications/apps.py` | 6 | 缺 | 0/0 | 0/1 | 模块头 + 1 类 |
| `notifications/__init__.py` | 0 | 空 | — | — | 豁免 |

> `ops/` 的 `/ops/*` 路由**不在** `/api/v1` 下,不受 `ApiDocsCoverageTests` 约束;但注释仍按同一规范写。

- [ ] **Step 1: 取缺口清单** — `python config/comment_coverage.py --app ops` 与 `--app notifications`(合计约 8 + 27 + 2 = 37 行)
- [ ] **Step 2: 改写模块 docstring** — `ops/views.py` 22 个函数、296 行,是本批次最大的单文件:模块头要说明审核台的鉴权方式(`ops/decorators.py` 的装饰器)与它为什么用 Django 模板而非 DRF。
- [ ] **Step 3: 补函数与类 docstring** — 逐个补;审核动作类函数要写清对用户状态的影响。
- [ ] **Step 4: 验收 + 回归**

```bash
python config/comment_coverage.py --app ops              # 期望:无缺口
python config/comment_coverage.py --app notifications    # 期望:无缺口
python manage.py test ops notifications                  # 期望:OK
```

- [ ] **Step 5: 提交**

```bash
git add chatapp/ops/ chatapp/notifications/
git commit -m "docs(ops,notifications): 注释规范化(模块头/函数 docstring)"
```

---

## Task 9: 测试文件 —— 模块头 + 行内注释

**Files(9 个测试文件):**

| 文件 | 行 | 类(待补) | 需处理 |
|---|---|---|---|
| `accounts/tests.py` | 453 | 3/12 | 模块头 + 9 个测试类 |
| `config/tests.py` | 184 | 2/8 | 模块头 + 6 个测试类 + **行内 37 行 emoji** |
| `discovery/tests.py` | 341 | 1/6 | 模块头 + 5 个测试类 + 1 处口语 |
| `feed/tests.py` | 411 | 1/8 | 模块头 + 7 个测试类 + **行内 41 行口语** |
| `im/tests.py` | 617 | 3/11 | 模块头 + 8 个测试类 + **docstring 205 行 emoji** |
| `moderation/tests.py` | 423 | 3/9 | 模块头 + 6 个测试类 |
| `notifications/tests.py` | 20 | 0/2 | 模块头 + 2 个测试类 |
| `ops/tests.py` | 412 | 0/11 | 模块头 + 11 个测试类 |
| `users/tests.py` | 653 | 2/14 | 模块头 + 12 个测试类 + **行内 198、510、614 行** |

**策略:`test_*` 方法豁免 docstring,测试类不豁免。**

- 451 个 `test_*` 用例名已是完整句子(如 `test_testing_uses_isolated_redis_db`),补 docstring 是纯噪音 → **豁免**。
- 66 个测试类是场景分组,一行说明价值高 → **必须补**。
- 非 `test_*` 的辅助函数(`setUp`、`make_user` 等)按正常规则补。

- [ ] **Step 1: 取缺口清单** — `python config/comment_coverage.py`(全量;此时除 9 个测试模块头外应已清零)
- [ ] **Step 2: 给每个测试文件写模块头**

模板(测试文件专用,比生产代码轻):

```python
"""<被测对象>的测试:覆盖 <主要场景枚举>。

测试用真实 provider + 假网络/假 IM(见 ``test/support`` 对应实现),
不触达真实第三方服务。
"""
```

每个文件的模块头必须**列出该文件覆盖的场景清单**(用中文短句枚举,如「发码限流 / 校验成功 / 连错锁定 / 重放窗口」),这是测试代码最重要的文档。

- [ ] **Step 3: 改写测试代码的行内注释**

| 位置 | 现状 | 目标 |
|---|---|---|
| `config/tests.py:37` | `# ⚠️ Celery 的 broker_url 属性会优先读环境变量 CELERY_BROKER_URL,...` | 去 `⚠️`,保留结论(这是踩坑回归点) |
| `feed/tests.py:41`、`users/tests.py:198`、`users/tests.py:510` | `# 别把测试图片写进真 media/` | `# 测试图片必须写入临时目录,不能落到真实 media/。` |
| `users/tests.py:614` | `# ⚠️ 必须在注销前取,删完 user.id 会是 None` | `# 注意:必须在注销前取出 im_user_id —— 用户行删除后 user.id 会变成 None。` |
| `im/tests.py:205` | docstring 内 `⚠️ 回归:...` | 去 `⚠️`,保留「对已存在的账号再调 account_import 会把昵称/头像清空」这条回归结论 |
| `discovery/tests.py`、`accounts/tests.py`、`im/tests.py` 的零散口语 | 按 §4 改为书面语 |

- [ ] **Step 4: 验收 + 全量回归**

```bash
python config/comment_coverage.py     # 期望:无缺口(全量)
python manage.py test                 # 期望:Ran 360 tests ... OK
```

- [ ] **Step 5: 提交**

```bash
git add chatapp/*/tests.py
git commit -m "docs(tests): 测试模块头补场景说明 + 行内注释去装饰符号"
```

---

## Task 10: 门禁测试 + 全量验收

**Files:**
- Modify: `chatapp/config/tests.py`(新增门禁测试类)
- Modify: `CLAUDE.md`(把新门禁写进「核心契约与纪律」)
- Modify: `docs/pitfalls/backend.md`(补一节「注释规范」,指向 `docs/standards/python.md`)

**Interfaces:**
- Consumes: `config/comment_coverage.py::find_problems`(Task 0 定义)
- Produces: 无

- [ ] **Step 1: 加门禁测试**

在 `chatapp/config/tests.py` 追加(与既有 `ApiDocsCoverageTests` 并列):

```python
class CommentCoverageTests(SimpleTestCase):
    """注释规范门禁:模块头与函数/类 docstring 必须齐全(规则见 docs/standards/python.md)。"""

    def test_every_module_and_symbol_is_documented(self):
        from config.comment_coverage import find_problems

        problems = find_problems()
        self.assertEqual(
            problems, [],
            "以下位置缺少注释或含装饰符号,请按 docs/standards/python.md 修正:\n" +
            "\n".join(f"  {p}" for p in problems))
```

- [ ] **Step 2: 验证门禁真的会红(反向验证)**

临时把 `chatapp/notifications/tasks.py` 的模块 docstring 删掉,运行:

Run: `python manage.py test config.tests.CommentCoverageTests`
Expected: **FAIL**,且错误信息里出现 `notifications/tasks.py:1 缺少模块 docstring`

然后**恢复该文件**(`git checkout chatapp/notifications/tasks.py`),再跑一次:

Run: `python manage.py test config.tests.CommentCoverageTests`
Expected: **OK**

> 这一步不能省。没有反向验证的门禁,很可能因为路径写错而永远绿。

- [ ] **Step 3: 全量回归**

Run: `python manage.py test`
Expected: `Ran 36x tests ... OK`(360 基线 + Task 0 的 5 个 + 本任务 1 个)

- [ ] **Step 4: 更新项目纪律文档**

`CLAUDE.md` 的「核心契约与纪律」一节追加一条(放在「接口文档」那条之后):

```markdown
- **注释规范**:`docs/standards/python.md` 是 Python 注释的单一事实来源;新增/修改任何 `.py` 文件,**同一次改动内**必须补齐模块 docstring 与函数/类 docstring(`test_*` 用例豁免);`python manage.py test` 会跑 `CommentCoverageTests` 比对,漏写即红
```

`docs/pitfalls/backend.md` 追加一节「注释规范」,3~5 行说清:规则文档在哪、门禁在哪、为什么测试用例豁免、口语词黑名单为什么只提示不拦截。

- [ ] **Step 5: 统计成果并回填本计划**

Run:
```bash
python config/comment_coverage.py
```
Expected: `无缺口`。把 Task 0 记录的三项基线(缺模块头 57 / 缺函数 docstring 185 / 缺类 docstring 94)与最终 0 的对比写进本计划文件末尾的「成果」一节,并把所有 `- [ ]` 勾成 `- [x]`。

- [ ] **Step 6: 提交**

```bash
git add chatapp/config/tests.py CLAUDE.md docs/pitfalls/backend.md docs/superpowers/plans/2026-10-17-backend-comment-standardization.md
git commit -m "docs: 注释规范门禁落地(CommentCoverageTests)+ 纪律文档回填"
```

---

## 验收标准(全部满足才算完成)

1. `python config/comment_coverage.py` 输出 `无缺口`;
2. `python manage.py test` 全绿,用例数 = 基线 360 + 新增 6;
3. `git diff` 中**没有一行是非注释改动**(用 `git diff --stat` 看行数变化应远小于总行数;逐文件 review 确认未改签名与逻辑);
4. `docs/standards/python.md` 存在且与代码实际风格一致;
5. `CLAUDE.md` 与 `docs/pitfalls/backend.md` 已回填门禁信息;
6. `im/tasks.py::delete_account`、`im/views.py` 踢人顺序、`config/settings.py` 的 `BROKER_URL` 前缀这三处**关键结论一条不少**。

---

## 后续立项(本次不做)

| 项 | 说明 |
|---|---|
| App(Dart)注释规范 | `app/lib` 126 文件 / 1,678 成员方法 / 213 类;需先定 Dart 侧模板(dartdoc `///`,腾讯系 Flutter 项目通行做法),再分批;门禁可用 `public_member_api_docs` lint |
| Web(TS/Vue)注释规范 | `web/src` 81 文件 / 257 个函数;模板走 AlloyTeam JSDoc(`@param {Type} 名称 说明` / `@returns`);门禁可用 ESLint `jsdoc` 规则 |
| Python 格式化工具 | ruff + black(腾讯 Python 规范含格式要求),单独一次全量格式化提交,避免与本次注释改动混在一起 |
| `Args`/`Returns` 小节的结构化校验 | 需要更强的静态分析,本次只靠规范文档 + review |

## 顺带发现(不在本批次内动手)

> 执行过程中发现的代码问题记在这里,由用户决定是否单独立项。

- (待填)

---

## 成果

> Task 10 Step 5 回填。

| 指标 | 动手前 | 完成后 |
|---|---|---|
| 缺模块 docstring(生产代码) | 57 | 待填 |
| 函数 docstring 覆盖(生产代码) | 54 / 239 | 待填 |
| 类 docstring 覆盖(生产代码) | 18 / 112 | 待填 |
| 测试文件模块头 | 0 / 9 | 待填 |
| 行内注释装饰符号 | 13 处 | 待填 |
| 后端用例数 | 360 | 待填 |
