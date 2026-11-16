#!/usr/bin/env python3
"""统一发信内核:主题规范 + SMTP 投递 + 去重 + 配额 + 发送日志。

为什么需要它
------------
2026-11-16 之前,发信实现有三套(服务器 ``/opt/notify``、WSL 的
``scripts/superagent-health/notify.sh``、Alertmanager 的 ``alert_relay.py``),
主题各自拼:``[日报]`` 前缀写死在 ini 里、``[superagent] …`` 硬编码在脚本里。
结果是收件箱里「哪一类 / 哪个对象 / 什么结论」三个字段都不稳定 —— 一份服务器日报
和一条 MySQL 宕机告警长得一模一样,按类别筛不出来,也看不出这台机器今天报了几次。

本模块把「主题怎么拼」与「怎么投出去」各收成一份:

    1. 主题只由 :func:`render_subject` 生成,格式 ``[chatapp·<类别>] <对象> — <结论>``;
       类别是封闭枚举(:data:`CATEGORIES`),非法类别直接抛错 —— 防的是「顺手新造一类」;
    2. 投递 / 去重 / 配额 / 发送日志都走 :class:`Mailer`,调用方只关心「发成了没有」。

设计要点:
    1. **主题里不许有数字**:数字每轮都变(落后几分钟、几条、几秒),混进主题就等于
       没有去重。数字进正文,主题只留稳定的「类别 + 对象 + 结论」。
    2. **发不出去必须让调用方知道**:一切失败抛 :class:`MailError`,退出码由调用方定。
       巡检发不出去要 exit 1 让 systemd 标红 —— 静默成功比没有告警更糟。
    3. **去重与配额写同一个状态库**(sqlite):去重命中返回 :data:`DEDUPED`(不算失败,
       本轮确实不需要再发一封);配额耗尽抛 :class:`MailError`(算失败:那一刻我们
       真的没把告警发出去)。
    4. **不读 http 代理**:smtplib 本来就不走代理,而 mihomo 是 HTTP 代理,邮件也过不去。

注意事项:
    - 主题与正文一律 UTF-8;主题里的 CR/LF 会被拒(防 header 注入)。
    - 投递函数 ``transport`` 可注入,自测完全不联网。

关联文档:
    - 主题规范表与各发信点:docs/ops/mail.md

用法::

    python3 scripts/lib/mail.py send --category 巡检 --subject worker \\
        --verdict 游标停摆 --body-file - --level error
    python3 scripts/lib/mail.py subject --category 告警 --subject MySQL看门狗 --verdict 已自动拉起
    python3 scripts/lib/mail.py check          # 只校验配置齐不齐,不联网
"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate
from typing import Callable, Dict, List, Optional

#: 邮件主题里的项目标签。全部发信点共用一个,收件箱里一眼能按项目筛。
PROJECT_TAG = "chatapp"

#: 类别**封闭枚举**:主题里出现的类别只能取这些值。
#:
#: ``CI`` 与 ``巡检`` 分开,是因为它们指向两种不同的处置:前者要去看代码/门禁,
#: 后者要去看这台机器还能不能干活。合成一类等于没分类。
#:
#: ``会话`` 是 2026-11-17 补的:服务器上还有一路「DSH 会话通知」(dsh-email-push 插件经 SSH
#: 调服务器的 notify),它既不是日报也不是告警 —— 原先落到默认配置上,于是每封都顶着
#: 「服务器日报」的名字。规范要覆盖全部发信方,不能只覆盖仓库这一路。
CATEGORIES = ("日报", "巡检", "告警", "CI", "备份", "部署", "会话")

#: 级别只影响正文首行与日志,不进主题(主题三段固定,便于排序与去重)。
LEVELS = ("info", "warn", "error")

#: 对象名 / 结论的长度上限:超过就截断,防止一个异常标题撑爆收件箱列表。
SUBJECT_NAME_MAX = 40
VERDICT_MAX = 60

#: 去重窗口默认值(分钟);调用方可以逐条覆盖。
DEDUP_DEFAULT_MINUTES = 60

#: 配额默认值,与阿里云邮件推送的共享额度对齐(见 docs/ops/mail.md 的配额预算)。
PER_MINUTE_DEFAULT = 5
PER_DAY_DEFAULT = 50

#: 投递重试:经宿主兜底代理时偶发单次失败,一次失败就放弃等于白丢一条告警。
RETRY_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 5

#: 投递结果(``SendResult.outcome`` 的取值)。
SENT = "sent"
DEDUPED = "deduped"
DRY_RUN = "dry-run"

#: 一次投递的默认超时(秒)。SMTP 建连+认证+投递的总预算。
SMTP_TIMEOUT_SECONDS = 30


class MailError(RuntimeError):
    """发不出去(配置不全 / 传输失败 / 配额耗尽 / 主题非法)。

    Attributes:
        detail: 给运维看的补充说明;没有时为空串。
    """

    def __init__(self, message: str, detail: str = "") -> None:
        """保存错误文案。

        参数说明:
            message: 一句话说清「哪一步没成」。
            detail: 可选的补充(通常是底层异常的类型与原文)。
        """
        super().__init__(message)
        self.detail = detail


def _one_line(text: str, field_name: str, limit: int) -> str:
    """把一段自由文本压成「一行、定长、无换行」的主题片段。

    参数说明:
        text: 原始文本。
        field_name: 出错时怎么称呼它(``对象`` / ``结论``)。
        limit: 最大字符数,超出截断并补省略号。

    返回参数:
        去掉首尾空白、内部连续空白压成一个空格后的文本。

    使用示例:
        ``_one_line("游标  停摆", "结论", 60)`` → ``"游标 停摆"``

    备注信息:
        含 CR/LF 直接抛 :class:`MailError` —— 主题是邮件头,换行等于让人往头里塞
        额外字段(header 注入)。这里宁可发不出去,也不发一封能注入的信。
    """
    raw = "" if text is None else str(text)
    if "\r" in raw or "\n" in raw:
        raise MailError(f"主题的{field_name}不能含换行(会变成邮件头注入)")
    collapsed = " ".join(raw.split())
    if not collapsed:
        raise MailError(f"主题的{field_name}不能为空")
    if len(collapsed) > limit:
        collapsed = collapsed[: limit - 1] + "…"
    return collapsed


def render_subject(category: str, subject: str, verdict: str) -> str:
    """拼出唯一合法的邮件主题。

    参数说明:
        category: 类别,必须落在 :data:`CATEGORIES` 里。
        subject: 对象(哪台机器 / 哪个服务 / 哪条告警),会被压成一行并截断。
        verdict: 结论(发生了什么 / 处理到什么程度),同样压成一行。

    返回参数:
        形如 ``[chatapp·告警] MySQL 看门狗 — 已自动拉起`` 的主题行。

    使用示例:
        ``render_subject("巡检", "worker", "游标停摆")``

    备注信息:
        类别非法抛 :class:`MailError`。数字不要进 ``verdict``:它每轮都变,
        会让「同一故障」在收件箱里看起来像两条不同的信。
    """
    if category not in CATEGORIES:
        raise MailError(
            f"类别 {category!r} 不在封闭枚举里(只能是 {' / '.join(CATEGORIES)})"
        )
    name = _one_line(subject, "对象", SUBJECT_NAME_MAX)
    tail = _one_line(verdict, "结论", VERDICT_MAX)
    return f"[{PROJECT_TAG}·{category}] {name} — {tail}"


@dataclass(frozen=True)
class MailMessage:
    """一封待发的邮件。

    Attributes:
        category: 类别(见 :data:`CATEGORIES`)。
        subject: 对象名。
        verdict: 结论。
        body: 正文(纯文本;数字与明细都放这里)。
        level: ``info`` / ``warn`` / ``error``,进正文首行与日志。
        dedup_key: 去重键;``None`` 表示不参与去重(由调用方自己负责抑制重复)。
        dedup_window_minutes: 同键多少分钟内只发一封。
    """

    category: str
    subject: str
    verdict: str
    body: str = ""
    level: str = "info"
    dedup_key: Optional[str] = None
    dedup_window_minutes: int = DEDUP_DEFAULT_MINUTES

    def subject_line(self) -> str:
        """渲染主题行(等价于对该消息调 :func:`render_subject`)。

        返回参数:
            主题行字符串。

        使用示例:
            ``MailMessage("巡检", "worker", "游标停摆").subject_line()``

        备注信息:
            类别非法或字段含换行时抛 :class:`MailError`。
        """
        if self.level not in LEVELS:
            raise MailError(f"级别 {self.level!r} 不在 {' / '.join(LEVELS)} 里")
        return render_subject(self.category, self.subject, self.verdict)

    def body_text(self) -> str:
        """渲染正文:首行带级别与类别,其余原样。

        返回参数:
            正文文本。

        使用示例:
            ``MailMessage("告警", "MySQL", "已拉起", body="详情").body_text()``

        备注信息:
            首行固定成 ``级别: warn · 类别: 告警``,便于在纯文本客户端里一眼看出
            这封信有多急 —— 主题只承载稳定的三段,级别不进主题。
        """
        head = f"级别: {self.level} · 类别: {self.category}"
        return f"{head}\n\n{self.body.strip()}\n" if self.body.strip() else f"{head}\n"


@dataclass
class MailConfig:
    """一次发信所需的全部配置(默认从环境变量读)。

    Attributes:
        smtp_url: ``smtps://host:465``(隐式 TLS)或 ``smtp://host:587``(STARTTLS)。
        mail_from: 发信地址。
        mail_to: 收信地址。
        username: SMTP 登录名;空表示不认证。
        password: SMTP 口令(阿里云用发信密码,QQ 用授权码)。
        state_db: 去重与配额的状态库(sqlite)路径。
        log_path: 发送日志(JSONL)路径。
        per_minute: 每分钟发信上限。
        per_day: 每日发信上限。
        dry_run: 只打印不投递(自测 / 演练)。
    """

    smtp_url: str = ""
    mail_from: str = ""
    mail_to: str = ""
    username: str = ""
    password: str = ""
    state_db: str = field(
        default_factory=lambda: os.path.expanduser("~/.local/state/mail/state.db")
    )
    log_path: str = field(
        default_factory=lambda: os.path.expanduser("~/.local/state/mail/mail.jsonl")
    )
    per_minute: int = PER_MINUTE_DEFAULT
    per_day: int = PER_DAY_DEFAULT
    dry_run: bool = False

    @classmethod
    def from_env(cls, env: Optional[Dict[str, str]] = None) -> "MailConfig":
        """从环境变量读配置(名字见本模块文档与 docs/ops/mail.md)。

        参数说明:
            env: 环境变量字典;默认 ``os.environ``(自测注入用)。

        返回参数:
            配置对象;缺项留空,由 :meth:`missing` 报出来。

        使用示例:
            ``MailConfig.from_env({"MAIL_SMTP_URL": "smtps://smtpdm.aliyun.com:465"})``

        备注信息:
            坏值(比如 ``MAIL_PER_DAY=abc``)退回默认而不是抛错:配置手误不该让
            巡检连「跑都没跑」,配额判断偏保守即可。
        """
        source = os.environ if env is None else env

        def text(name: str, default: str = "") -> str:
            return str(source.get(name, default) or "").strip()

        def number(name: str, default: int) -> int:
            try:
                return int(text(name) or default)
            except ValueError:
                return default

        return cls(
            smtp_url=text("MAIL_SMTP_URL"),
            mail_from=text("MAIL_FROM"),
            mail_to=text("MAIL_TO"),
            username=text("MAIL_USER"),
            password=text("MAIL_PASS"),
            state_db=os.path.expanduser(text("MAIL_STATE_DB") or cls().state_db),
            log_path=os.path.expanduser(text("MAIL_LOG") or cls().log_path),
            per_minute=number("MAIL_PER_MINUTE", PER_MINUTE_DEFAULT),
            per_day=number("MAIL_PER_DAY", PER_DAY_DEFAULT),
            dry_run=text("MAIL_DRY_RUN").lower() in ("1", "on", "true", "yes", "y"),
        )

    def missing(self) -> List[str]:
        """列出还缺哪些必填项。

        返回参数:
            环境变量名列表;空列表表示配置齐全。

        使用示例:
            ``MailConfig.from_env({}).missing()`` → ``["MAIL_SMTP_URL", "MAIL_FROM", "MAIL_TO"]``

        备注信息:
            只判「投递必需」的三项;``MAIL_USER`` / ``MAIL_PASS`` 允许为空
            (内网中继或免认证中继)。
        """
        absent: List[str] = []
        if not self.smtp_url:
            absent.append("MAIL_SMTP_URL")
        if not self.mail_from:
            absent.append("MAIL_FROM")
        if not self.mail_to:
            absent.append("MAIL_TO")
        return absent


@dataclass
class SendResult:
    """一次投递的结果。

    Attributes:
        outcome: :data:`SENT` / :data:`DEDUPED` / :data:`DRY_RUN`。
        subject_line: 实际(或本应)发出的主题行。
        detail: 人读的补充说明。
    """

    outcome: str
    subject_line: str
    detail: str = ""

    def delivered(self) -> bool:
        """这一轮是否真的把信投出去了。

        返回参数:
            仅 :data:`SENT` 为 ``True``(去重跳过与 dry-run 都没投递)。

        使用示例:
            ``Mailer(cfg).send(msg).delivered()``

        备注信息:
            调用方判「要不要记指纹」用这个:**没投递就不能记**,否则那条告警
            在去重窗口内再也不会报。
        """
        return self.outcome == SENT


def _parse_smtp_url(url: str) -> tuple:
    """把 ``smtps://host:port`` / ``smtp://host:port`` 拆成 (主机, 端口, 是否隐式 TLS)。

    参数说明:
        url: 带 scheme 的 SMTP 地址。

    返回参数:
        ``(host, port, implicit_tls)`` 三元组。

    使用示例:
        ``_parse_smtp_url("smtps://smtpdm.aliyun.com:465")`` → ``("smtpdm.aliyun.com", 465, True)``

    备注信息:
        只认这两个 scheme:``smtps`` = 465 隐式 TLS,``smtp`` = 587 STARTTLS。
        不写 scheme 或端口直接抛 :class:`MailError` —— 猜错一个字母就是「永远发不出去
        却没人知道」,宁可配置时当场红。
    """
    if "://" not in url:
        raise MailError(
            f"MAIL_SMTP_URL 必须带 scheme(smtps://host:465 或 smtp://host:587),现在是 {url!r}"
        )
    scheme, rest = url.split("://", 1)
    scheme = scheme.lower()
    if scheme not in ("smtps", "smtp"):
        raise MailError(f"MAIL_SMTP_URL 的 scheme 只支持 smtp / smtps,现在是 {scheme!r}")
    host, _, port_text = rest.partition(":")
    if not host:
        raise MailError(f"MAIL_SMTP_URL 里没有主机名:{url!r}")
    default_port = 465 if scheme == "smtps" else 587
    try:
        port = int(port_text or default_port)
    except ValueError as exc:
        raise MailError(f"MAIL_SMTP_URL 的端口不是整数:{url!r}") from exc
    return host, port, scheme == "smtps"


def _smtp_transport(config: MailConfig, subject: str, body: str, level: str) -> None:
    """把一封信投给 SMTP 服务器(默认投递实现)。

    参数说明:
        config: 发信配置。
        subject: 已渲染好的主题行。
        body: 正文。
        level: 级别,写进 ``X-Mail-Level`` 头便于服务端侧过滤。

    返回参数:
        无返回值;失败抛异常(由 :class:`Mailer` 统一翻译成 :class:`MailError`)。

    使用示例:
        ``_smtp_transport(cfg, "[chatapp·巡检] worker — 游标停摆", "详情", "error")``

    备注信息:
        465 走 ``SMTP_SSL``,587 走 ``SMTP`` + ``starttls()``;两者都要显式超时,
        否则一次黑洞连接会把 systemd 单元拖到 5 分钟超时。
    """
    message = EmailMessage()
    message["From"] = config.mail_from
    message["To"] = config.mail_to
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=False)
    message["X-Mail-Level"] = level
    message.set_content(body)

    host, port, implicit_tls = _parse_smtp_url(config.smtp_url)
    client_class = smtplib.SMTP_SSL if implicit_tls else smtplib.SMTP
    with client_class(host, port, timeout=SMTP_TIMEOUT_SECONDS) as client:
        if not implicit_tls:
            client.starttls()
        if config.username:
            client.login(config.username, config.password)
        client.send_message(message)


class Mailer:
    """一次配置下的发信器:去重 → 配额 → 投递 → 记账。

    Attributes:
        config: 发信配置。
    """

    def __init__(
        self,
        config: MailConfig,
        transport: Optional[Callable[[MailConfig, str, str, str], None]] = None,
        now: Optional[Callable[[], datetime]] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ) -> None:
        """装配发信器。

        参数说明:
            config: 发信配置。
            transport: 投递实现;默认 :func:`_smtp_transport`。自测注入假实现即可完全不联网。
            now: 取当前时间的函数;默认 UTC now(自测注入以验证去重窗口)。
            sleep: 重试间隔函数;默认 ``time.sleep``(自测注入成空函数以免拖慢用例)。

        返回参数:
            无返回值。

        使用示例:
            ``Mailer(MailConfig.from_env(), transport=fake)``

        备注信息:
            状态库与日志目录在首次发信时按需创建,不在构造期落盘 —— 构造期写文件会让
            「只渲染主题」这类只读用法也产生副作用。
        """
        self.config = config
        self._transport = transport or _smtp_transport
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep or time.sleep

    # --- 状态库 ---------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """打开(必要时创建)去重与配额的状态库。

        返回参数:
            sqlite 连接(表已就绪)。

        使用示例:
            ``conn = self._connect()``

        备注信息:
            每次发信开一次、用完即关:巡检 15 分钟才跑一轮,连接复用的收益远小于
            跨线程持有连接的风险。
        """
        parent = os.path.dirname(os.path.abspath(self.config.state_db))
        os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(self.config.state_db)
        conn.execute("create table if not exists sent (at real not null)")
        conn.execute("create table if not exists dedup (key text primary key, at real not null)")
        return conn

    def _log(self, message: MailMessage, subject_line: str, outcome: str, detail: str) -> None:
        """追加一行发送日志(JSONL)。

        参数说明:
            message: 本次消息。
            subject_line: 渲染出的主题行。
            outcome: 投递结果。
            detail: 补充说明。

        返回参数:
            无返回值。

        使用示例:
            ``self._log(msg, subject, SENT, "")``

        备注信息:
            日志写不进去不能影响「发没发出去」这个结论:邮件已经投出去了,日志盘满
            只该被忽略 —— 所以这里吞掉 OSError。
        """
        record = {
            "ts": self._now().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "category": message.category,
            "subject": subject_line,
            "level": message.level,
            "dedup_key": message.dedup_key or "",
            "outcome": outcome,
            "detail": detail,
        }
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.config.log_path)), exist_ok=True)
            with open(self.config.log_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # --- 发信 -----------------------------------------------------------

    def send(self, message: MailMessage) -> SendResult:
        """按「去重 → 配额 → 投递 → 记账」的顺序发一封信。

        参数说明:
            message: 待发的邮件。

        返回参数:
            :class:`SendResult`;去重命中返回 :data:`DEDUPED`,dry-run 返回 :data:`DRY_RUN`。

        使用示例:
            ``result = Mailer(cfg).send(MailMessage("巡检", "worker", "游标停摆"))``

        备注信息:
            传输失败抛 :class:`MailError` 且**不记去重**、不占配额 —— 没发出去的信
            下一轮必须还能重发。配额耗尽同样抛错(那一刻确实没发出去),但**不**写
            去重键:配额是环境问题,不该把一条告警压掉 6 小时。
        """
        subject_line = message.subject_line()
        absent = self.config.missing()
        if absent:
            raise MailError(f"发信配置不全,缺:{', '.join(absent)}")

        now_ts = self._now().timestamp()
        conn = self._connect()
        try:
            if message.dedup_key:
                row = conn.execute(
                    "select at from dedup where key = ?", (message.dedup_key,)
                ).fetchone()
                if row and now_ts - float(row[0]) < message.dedup_window_minutes * 60:
                    detail = f"同键 {message.dedup_key} 在去重窗口内已发过,本轮跳过"
                    self._log(message, subject_line, DEDUPED, detail)
                    return SendResult(DEDUPED, subject_line, detail)

            self._check_quota(conn, now_ts)

            if self.config.dry_run:
                detail = "dry-run:只渲染不投递"
                self._log(message, subject_line, DRY_RUN, detail)
                return SendResult(DRY_RUN, subject_line, detail)

            self._deliver(message, subject_line)

            conn.execute("insert into sent (at) values (?)", (now_ts,))
            if message.dedup_key:
                conn.execute(
                    "insert into dedup (key, at) values (?, ?) "
                    "on conflict(key) do update set at = excluded.at",
                    (message.dedup_key, now_ts),
                )
            conn.commit()
        finally:
            conn.close()

        self._log(message, subject_line, SENT, "")
        return SendResult(SENT, subject_line)

    def _check_quota(self, conn: sqlite3.Connection, now_ts: float) -> None:
        """按分钟与按日两个窗口查配额,超了抛错。

        参数说明:
            conn: 状态库连接。
            now_ts: 当前时间戳(秒)。

        返回参数:
            无返回值;超限抛 :class:`MailError`。

        使用示例:
            ``self._check_quota(conn, time.time())``

        备注信息:
            计数直接数 ``sent`` 表,不维护计数器列 —— 计数器会在崩溃与并发下漂移,
            而这张表每天最多几十行。
        """
        per_minute = conn.execute(
            "select count(*) from sent where at > ?", (now_ts - 60,)
        ).fetchone()[0]
        if per_minute >= self.config.per_minute:
            raise MailError(
                f"每分钟配额已满({per_minute}/{self.config.per_minute}),本轮不发",
            )
        per_day = conn.execute(
            "select count(*) from sent where at > ?", (now_ts - 86400,)
        ).fetchone()[0]
        if per_day >= self.config.per_day:
            raise MailError(f"每日配额已满({per_day}/{self.config.per_day}),本轮不发")

    def _deliver(self, message: MailMessage, subject_line: str) -> None:
        """按 :data:`RETRY_ATTEMPTS` 次重试投递,全失败抛 :class:`MailError`。

        参数说明:
            message: 待发的邮件。
            subject_line: 已渲染的主题行。

        返回参数:
            无返回值。

        使用示例:
            ``self._deliver(msg, "[chatapp·巡检] worker — 游标停摆")``

        备注信息:
            重试是为了吞掉单次网络抖动;两次都失败就说明通道真不通,交给调用方
            让 systemd 标红 —— 那正是「巡检自身失灵」唯一的机械信号。
        """
        last_error = ""
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                self._transport(self.config, subject_line, message.body_text(), message.level)
                return
            except Exception as exc:  # noqa: BLE001 - 任何异常都算「这次没发出去」
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < RETRY_ATTEMPTS:
                    self._sleep(RETRY_DELAY_SECONDS)
        raise MailError(f"投递失败(重试 {RETRY_ATTEMPTS} 次):{last_error}")


def load_env_file(path: str, env: Optional[Dict[str, str]] = None) -> List[str]:
    """把 `KEY=VALUE` 配置文件补进环境变量(**已存在的键不覆盖**)。

    参数说明:
        path: 配置文件路径(每行 `KEY=VALUE`,允许 `#` 注释、空行、值两侧引号)。
        env: 目标字典;默认 ``os.environ``(自测注入用)。

    返回参数:
        实际补上的键名列表(已存在的键不计入)。

    使用示例:
        ``load_env_file("/root/.dsh/superagent-health.env")``

    备注信息:
        「shell 里显式 export 的值优先、文件只补缺」——这样同一个文件既能当运维的默认配置,
        又能在临时排障时用一条 `MAIL_DRY_RUN=1 mail.py check --env-file …` 覆盖掉。
        读不到文件抛 :class:`MailError`:静默当成「没配」会让排障绕远路。
    """
    target = os.environ if env is None else env
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError as exc:
        raise MailError(f"读不到配置文件 {path}:{exc}") from exc
    loaded: List[str] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in target:
            continue
        cleaned = value.strip().strip("\"'")
        target[key] = cleaned
        loaded.append(key)
    return loaded


def _read_body(path: Optional[str]) -> str:
    """读正文:``-`` 表示 stdin,``None`` 表示空正文。

    参数说明:
        path: 文件路径、``-``(stdin)或 ``None``。

    返回参数:
        正文文本。

    使用示例:
        ``_read_body("-")``

    备注信息:
        读不到文件抛 :class:`MailError`:静默发一封空正文的信,比发不出去更难查。
    """
    if path is None:
        return ""
    if path == "-":
        return sys.stdin.read()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError as exc:
        raise MailError(f"读不到正文文件 {path}:{exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器。

    返回参数:
        已配置好的 ``ArgumentParser``。

    使用示例:
        ``build_parser().parse_args(["check"])``

    备注信息:
        子命令刻意只有三个:``send``(真发)、``subject``(只渲染主题)、``check``
        (只校验配置)。运维排查时用后两个就能定位「主题对不对 / 配置齐不齐」,
        不必真发一封邮件。
    """
    parser = argparse.ArgumentParser(description="统一发信内核(主题规范 + SMTP + 去重 + 配额)")
    # `--env-file` 挂成「子命令也能带」的公共参数:运维习惯写成
    # `mail.py check --env-file <env>`,放在子命令前面反而别扭。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--env-file",
        default=None,
        help="配置文件(每行 KEY=VALUE;只补缺,shell 里已 export 的键优先)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_message_args(target: argparse.ArgumentParser) -> None:
        target.add_argument("--category", required=True, help="类别:" + " / ".join(CATEGORIES))
        target.add_argument("--subject", required=True, help="对象(哪台机器 / 哪个服务)")
        target.add_argument("--verdict", required=True, help="结论(发生了什么 / 处理到哪一步)")

    send = sub.add_parser("send", parents=[common], help="发一封(走配置里的 SMTP)")
    add_message_args(send)
    send.add_argument("--body", default="", help="正文(短文本直接给)")
    send.add_argument("--body-file", default=None, help="正文文件;`-` 表示 stdin")
    send.add_argument("--level", default="info", choices=LEVELS, help="级别(默认 info)")
    send.add_argument("--dedup-key", default=None, help="去重键;不给就不去重")
    send.add_argument(
        "--dedup-window",
        type=int,
        default=DEDUP_DEFAULT_MINUTES,
        help=f"同键去重窗口(分钟,默认 {DEDUP_DEFAULT_MINUTES})",
    )

    subject = sub.add_parser("subject", parents=[common], help="只渲染主题行(不联网、不发信)")
    add_message_args(subject)

    sub.add_parser("check", parents=[common], help="只校验配置齐不齐(不联网)")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """入口:按子命令执行,返回退出码。

    参数说明:
        argv: 命令行参数;默认取 ``sys.argv[1:]``。

    返回参数:
        ``0`` = 已发 / 已去重跳过 / 校验通过;``1`` = 发不出去或配置不全。

    使用示例:
        ``sys.exit(main(["subject", "--category", "巡检", "--subject", "worker", "--verdict", "游标停摆"]))``

    备注信息:
        退出码只有两级:对调用方来说「发了」与「去重跳过」都是成功(这一轮不需要
        再发),而配置缺失 / 传输失败 / 配额耗尽都是「没发出去」,必须让上层看见。
    """
    args = build_parser().parse_args(argv)

    try:
        if args.env_file:
            load_env_file(args.env_file)
        config = MailConfig.from_env()

        if args.command == "subject":
            print(render_subject(args.category, args.subject, args.verdict))
            return 0
        if args.command == "check":
            absent = config.missing()
            if absent:
                print(f"mail: 配置不全,缺:{', '.join(absent)}", file=sys.stderr)
                return 1
            print(
                f"mail: 配置齐全 · {config.smtp_url} · {config.mail_from} → {config.mail_to}"
                f" · 配额 {config.per_minute}/分钟 {config.per_day}/天"
                f" · 状态库 {config.state_db}"
            )
            return 0

        body = _read_body(args.body_file) if args.body_file else args.body
        message = MailMessage(
            category=args.category,
            subject=args.subject,
            verdict=args.verdict,
            body=body,
            level=args.level,
            dedup_key=args.dedup_key,
            dedup_window_minutes=args.dedup_window,
        )
        result = Mailer(config).send(message)
        print(f"mail: {result.outcome} · {result.subject_line}")
        if result.detail:
            print(f"      {result.detail}")
        return 0
    except MailError as exc:
        detail = f"({exc.detail})" if exc.detail else ""
        print(f"mail: {exc}{detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
