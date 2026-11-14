---
状态: 常驻
复核: `python config/comment_coverage.py`
---

# Python 注释规范

适用于 `chatapp/` 下**全部** Python 代码。

**检查入口**(两者等价,前者秒级、后者在 CI 上跑):

```bash
cd chatapp
python config/comment_coverage.py              # 全量检查,通过时打印「无缺口」(含 参数说明 小节)
python config/comment_coverage.py --app im     # 只检查某个 app
python config/comment_coverage.py --warnings   # 附带口语词提示(不拦截)
python config/comment_coverage.py --structure  # 只查公开函数的 参数说明 小节,不跑其余检查
python manage.py test config.tests.CommentCoverageTests
```

**基线**(2026-10-17 规范化之前,由本规范的检查脚本实测):

| 范围 | 模块头缺失 | 符号 docstring 缺失 | 装饰符号 | 小计 |
|---|---|---|---|---|
| 生产代码 | 57 | 275 | 5 | 337 |
| 测试代码 | 9 | 96 | 0 | 105 |
| **合计** | **66** | **371** | **5** | **442** |

> 「符号 docstring 缺失」与「装饰符号」互斥:一个函数要么没 docstring,要么有 docstring
> 但里面带了 emoji,不会同时命中。5 处装饰符号全部位于生产代码的 docstring 内。
> `--warnings` 另会报出口语词命中项(不拦截)。
> `--structure` 单独跑「公开函数带参数却没有 `参数说明:` 小节」这一条判定;它已经并入默认
> 路径,所以不加开关也会拦(见 §7)。
> 规范化前,118 个已有 docstring 中**没有一个**用过 `Args`/`Returns`/`Raises` 结构化小节;
> 该缺口已按 §3 补齐(当前 229 个 docstring 带 `Args:` 小节),自 2026-11-14 起**进硬门禁**
> (见 §7)。

**已豁免**(不计入上表):12 个 0 字节的 `__init__.py`、`migrations/` 目录、451 个 `test_*`
用例、54 个 `setUp` 类生命周期钩子、10 处函数内闭包与局部类、93 个 `Meta` 声明式内部类。

> 上表是**规范化开始前**的原始缺口。2026-10-17 规范化完成后该数字已归零,
> 并由 `CommentCoverageTests` 门禁守住(见 §7)。当前覆盖率:83 个非空生产文件
> 模块头 100%,函数 245/248、类 91/112 —— 未覆盖的 3 个函数与 21 个类全部是
> §6 明确豁免的闭包与 `Meta`。

---

## 1. 「腾讯方式」落到 Python 是什么

腾讯的公开规范里与本项目相关的有三条线。直接照搬 C++ 的 `@file`/`@author` 标签到 Python
是错的,正确的做法是**取其意、换其形**:

| 腾讯来源 | 原始形态 | 本项目落地 |
|---|---|---|
| 后台 / C++ 规范的文件头块 | `@file` / `@brief` / `@author` / `@date` / `@note` | 换成 Python 的**模块 docstring**:一句话职责 + 按需小节 |
| 腾讯 Python 规范(以 Google Python Style Guide 为基础) | 模块 / 类 / 函数三级 docstring,函数用 `Args`/`Returns`/`Raises` | **五小节函数 docstring**(`参数说明`/`返回参数`/`使用示例`/`备注信息`,与 C++ 侧字段同口径) |
| AlloyTeam 前端规范「注释解释为什么,不解释是什么」 | 行内注释只写非显然的决策依据 | 行内注释**去装饰符号、去口语、去内部编号引用** |

**明确不引入的两样东西:**

- **`@author` / `@date`。** git 已经记录了作者与时间,把它们抄进文件头只会腐烂——人员变动后
  没人会回来改,半年后文件头就是错的。腾讯那条规范的历史背景是 CVS/SVN 时代缺乏 blame 工具。
- **格式化工具(ruff / black)。** 腾讯 Python 规范确实包含格式要求,但格式化的 diff 会淹没
  注释改动。本项目的做法是**注释规范化与格式化分两次提交**,格式化单独立项。

---

## 2. 模块 docstring(即「文件头注释」)

Python 没有独立的文件头注释块,模块开头的字符串字面量就是文件头。

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

文件信息:
    文件名称          <相对 chatapp/ 的路径>
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""
```

`文件信息` 是文件头的固定字段块（与 `imserver/` 的 C++ 文件头同口径），**每个非空 `.py` 文件都必须有**。

**取舍规则:**

- **只写有内容的小节。** 一句话已说清的小模块(`apps.py`、`urls.py`、纯常量模块),只留首行。
  小节标题不是必填项,空着比凑字好。
- `设计要点` 回答「为什么这么设计」,`注意事项` 回答「用错了会怎样」,两者**不要互相搬运**。
- `关联文档` 只在**确有**对应文档时写;路径必须真实存在,不臆造。
- 首行直接说职责,不以「本模块」「该文件」开头。
- **原注释里的信息不能丢。** 例如「全项目唯一 import 自建 IM 内部 API 的文件」属于设计约束,
  必须原样保留为 `设计要点` 条目。
- 装饰符号(`⚠️`、`🔴`)一律去掉,语义改用 `注意:` 承接。

---

## 3. 函数 docstring

```python
def issue_code(phone: str) -> str:
    """生成并存储验证码。

    参数说明:
        phone: 手机号，同时作为发送间隔限流的键。

    返回参数:
        本次生成的 6 位验证码；开发模式下固定为 ``settings.SMS_DEV_CODE``。

    使用示例:
        ``code = issue_code("13800000000")``

    备注信息:
        短信入队由调用方负责（见 ``views.sms_send``）；本函数只负责限流、生成、落库三步。
        距上次发送不足 ``SMS_RESEND_INTERVAL`` 秒时抛 ``SmsSendTooFrequent``。
    """
```

**规则:**

- 首行**一句话动宾结构**,句末 `。`,不写「本函数」「该方法」。
- 首行与后续小节之间**空一行**。
- 五小节固定顺序:`参数说明:` → `返回参数:` → `使用示例:` → `备注信息:`,小节标题后紧跟缩进 4 空格的正文。
- `参数说明:` 每个参数一行,格式 `参数名: 说明。`。类型已在类型注解里,**不重复写类型**;无参数写 `无。`
  公开函数**只要带参数就必须写** `参数说明:` 小节(私有函数、`test_*` 用例、生命周期钩子、
  无参函数除外),漏写即门禁红(见 §7);过渡态下 `Args:` 与 `参数说明:` 二者其一即算合规。
- `返回参数:` 写返回值语义;返回 `None` 时写 `无返回值。`
- `使用示例:` 用双反引号包裹**真实调用形式**;方法写 `obj.method(...)`。
- `备注信息:` **必须存在**,写前置条件、异常、副作用、并发/限流约束;没有内容写 `无特殊约束。`
  原 `Raises:` 只列**本函数主动抛出**的异常,不含被调用方穿透上来的,内容并入这里。
- **私有函数**(`_` 前缀)、`@property`、`@override` 装饰的方法:**允许只写首行 + `备注信息:`**,
  不强制 `参数说明`/`返回参数`/`使用示例`。
- **Django 视图**:首行末尾注明对应接口,格式 `(GET /api/v1/discovery/candidates)`。
- **Django Model 的字段**:字段语义不显然时用行内注释,不塞进类 docstring。
- **`test_*` 用例**:维持 §6 的豁免;**若写只写首行**,不再要求 `参数说明: 无。`
  (存量两种写法都算合规,不做一次性换算)。

---

## 4. 类 docstring

- 一句话职责。Django Model 额外用 `Attributes:` 列出**语义不显然**的字段
  (状态机取值、派生属性、跨表约定)。
- `AppConfig` 子类:一行职责,**不写五小节**——类没有参数、返回值与调用形式这三样,
  五小节里只能写「无」。
- `Meta` 等声明式内部类按 §6 豁免,不要求 docstring。
- **测试类不豁免**,但只写**一行场景说明**,不写五小节——一个测试类就是一个场景分组,
  一行「这个类覆盖什么」价值很高。见 §6。

---

## 5. 行内注释

- **禁止装饰符号**:`⚠️`、`🔴`、`✅`、`❌` 一律改为 `注意:` 起头。
- **禁止口语词**:别用 / 别把 / 够用 / 我们 / 压根 / 悄悄 / 顺手 / 其实 / 干脆 / 偷懒 / 坑…,
  改为书面语。
- **禁止内部编号引用**:`spec §13`、`规则 §5.1` 改为 `详见 docs/...` 或直接删除
  (spec 文件会改名、会归档,编号引用必然失效)。
- 只解释「为什么」,不解释「是什么」。
- 统一 `# ` 前缀 + 空格;中文句末加句号。
- 分节分隔线保留 `# --- 说明 ---` 形式(`config/settings.py` 已在用)。

---

## 6. 豁免规则

| 对象 | 是否豁免 | 理由 |
|---|---|---|
| 0 字节文件(空的 `__init__.py`) | 是 | 无内容可写 |
| `migrations/` 目录 | 是 | Django 自动生成,不手改 |
| `test_*` 函数与方法 | **是** | 用例名已是完整句子,补 docstring 是纯噪音;若作者写了,只写一行首行 |
| `setUp` / `tearDown` / `setUpClass` / `tearDownClass` / `setUpTestData` | **是** | 框架调用的生命周期钩子,不是对外 API,没有外部调用者;补 docstring 纯属噪音;若作者写了,只写一行首行,不写五小节 |
| 嵌套在函数体内的函数与类(闭包、局部类) | **是** | 所属函数的实现细节。测试里大量 `fake_request` / `FakeTask` 这类 3 行打桩属于此类 |
| `Meta` 等声明式内部类 | **是** | 框架读取的配置,给 `model` + `fields` 写 docstring 只是样板;全项目 93 处 |
| 测试类 | **否** | 场景分组,一行说明价值高;且让门禁不必按文件名特判。只写一行,不写五小节 |
| `AppConfig` 子类 | **否** | 顶层类,有明确职责(说明该 app 管什么)。只写一行,不写五小节 |
| 非 `test_*` 的顶层辅助方法(`_make_user`、`login` 等) | 否 | 按正常规则写 |
| 私有函数 / `@property` | 部分 | 允许只写首行 + `备注信息:`,不强制 `参数说明`/`返回参数`/`使用示例` |

> **只写一行的四类对象**:`test_*` 用例、生命周期钩子、测试类、`AppConfig` 子类。它们的
> 共同点是「没有参数 / 返回值 / 调用形式」这三样里至少缺两样,五小节填出来只能是「无」。
> 2026-11-14 已按此口径把存量压平:测试类 20 处、生命周期钩子 19 处、`AppConfig` 子类 1 处,
> 合计 40 处。
>
> 测试类之所以不豁免,还有个工程理由:**基于文件名的特判是门禁脚本最容易出错的地方**
> (判断 `test*.py` 还是 `*tests.py`、路径分隔符、大小写)。为省 66 行注释引入这种特判不划算。
> 同理,上表全部规则都只依据**名称**与**嵌套形态**,不依据文件路径。

---

## 7. 门禁规则(AST 判定)

**硬性拦截**(不满足即 `CommentCoverageTests` 红,`python config/comment_coverage.py` 返回 1):

1. 非空 `.py` 文件(`migrations/` 除外)必须有模块 docstring;
2. 每个 `FunctionDef` / `AsyncFunctionDef` / `ClassDef` 必须有 docstring,`test_*` 名称除外;
3. 模块 docstring 与函数 / 类 docstring 中不得出现 emoji 或 `⚠` 类装饰符号;
4. 公开函数带参数却没有 `参数说明:` 小节(`find_structure_warnings`,已并入 `find_problems`,
   所以默认路径就拦,不必加 `--structure`)。

> **第 4 条为什么现在可以拦**(2026-11-14 起):它只判 `参数说明:` 小节**是否存在**,
> 判断「是否需要」只依据**名称与形态**(公开 = 非 `_` 前缀、非 `test_*`、非生命周期钩子、
> 非 `@property`、非函数内闭包),不判内容质量 —— 内容归第 6 条。此前不敢拦的理由是
> 「AST 判不出参数是否显然到可以不写」,而豁免口径按名称与形态固定之后,误报面已经收敛
> 到零,继续留在「只报告」只会让缺口长期存在(2026-11-14 实测 10 处,全部在
> `im/self_client.py`)。
>
> **过渡态**:第 4 条接受 `参数说明:` 或 `Args:` 二者其一。全仓还有 573 个符号 / 114 个
> 文件在用 `Args:`(2026-11-14 实测),换算单独立项;本门禁不因存量写法报红,也不要求
> 后人顺手换算。

**只报告不拦截**(`--warnings` 输出):

5. 口语词黑名单命中项。该黑名单**必然有误报**——「兜底」在技术语境里是合法用词,
   做成硬门禁会逼后人写 `# noqa`,反而降低规范的权威性。人工在 review 时看。

**明确不检查:**

6. `参数说明` 内容是否准确,以及 `返回参数`/`使用示例`/`备注信息` 小节写得对不对。AST 无法判断
   「这个返回值是否显然」,强做必然误报。这一条靠 review 与本文档约束。

---

## 8. 正反例

### 正例

`accounts/services.py` 规范化后的完整形态。注意 `_sent_key` **保持原签名 `def _sent_key(phone):`
不变**(本次规范化只改注释,不动签名与类型注解):

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

    参数说明:
        phone: 手机号，同时作为发送间隔限流的键。

    返回参数:
        本次生成的 6 位验证码；开发模式下固定为 ``settings.SMS_DEV_CODE``。

    使用示例:
        ``code = issue_code("13800000000")``

    备注信息:
        短信入队由调用方负责（见 ``views.sms_send``）；本函数只负责限流、生成、落库三步。
        距上次发送不足 ``SMS_RESEND_INTERVAL`` 秒时抛 ``SmsSendTooFrequent``。
    """
    if not cache.add(_sent_key(phone), 1, settings.SMS_RESEND_INTERVAL):
        raise SmsSendTooFrequent(wait=settings.SMS_RESEND_INTERVAL)
    code = settings.SMS_DEV_CODE if settings.SMS_DEV_MODE else f"{random.randint(0, 999999):06d}"
    sms_codes.store(phone, code)
    logger.info("[开发模式] 验证码 phone=%s code=%s", phone, code)
    return code


def rollback_send(phone: str) -> None:
    """短信任务入队失败时回滚。

    参数说明:
        phone: 手机号。

    返回参数:
        无返回值。

    使用示例:
        ``rollback_send("13800000000")``

    备注信息:
        删掉限流占位与验证码，让用户能立刻重试（见 ``views.sms_send`` 的异常分支）。
    """
    cache.delete(_sent_key(phone))
    sms_codes.delete(phone)


def check_code(phone: str, code: str) -> None:
    """校验验证码，成功即通过。

    参数说明:
        phone: 手机号。
        code: 用户提交的 6 位验证码。

    返回参数:
        无返回值；校验失败以异常形式抛出。

    使用示例:
        ``check_code("13800000000", "123456")``

    备注信息:
        含 60 秒重放窗口内的重复校验：窗口内重复提交同一个码仍算成功。
        验证码过期或不存在抛 ``SmsCodeExpired``；错误抛 ``SmsCodeWrong``；
        连错次数超限抛 ``SmsLocked``。
    """
    result = sms_codes.verify(phone, code)
    if result is sms_codes.CodeResult.EXPIRED:
        raise SmsCodeExpired()
    if result is sms_codes.CodeResult.WRONG:
        raise SmsCodeWrong()
    if result in (sms_codes.CodeResult.LOCKED, sms_codes.CodeResult.JUST_LOCKED):
        raise SmsLocked(wait=settings.SMS_LOCK_TTL)
```

### 反例

```python
# ⚠️ 别用 @装饰器:celery 的 Signal.connect 行为不一致      ← 装饰符号 + 口语
def _user(user_id):                                        ← 缺 docstring
    """🔴 参数是 im_user_id 不是 user_id,见 spec §13"""    ← 装饰符号 + 内部编号引用
    ...


def candidates(request):                                   ← 缺 docstring
    # order_by("?") 数据量大时会慢,MVP 阶段够用            ← 口语(「够用」)
    ...
```

**注意反例里第二条**:那条注释**内容是对的、必须保留**,错的只是措辞。正确做法是改成
「`order_by("?")` 在数据量大时性能下降。当前用户规模(数百人)可接受,后续改为预计算随机列。」——
规范化不是删注释,是让注释更专业。
