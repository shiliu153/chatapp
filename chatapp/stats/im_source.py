"""只读访问 IM 库(``chatapp_im``)拿消息量:一条 ``COUNT``,失败即降级。

消息在 imserver 自己的库里,Django 侧没有连接;运营看板只需要「某天有多少条消息」
这一个数字,所以本模块只做一件事:按 DSN 连一次、跑一条 ``SELECT COUNT(*)``、断开。

设计要点:
    1. ``im_message.created_at`` 是 **epoch 毫秒**(BIGINT),不是 datetime,因此查询参数
       是 ``int(start.timestamp() * 1000)`` / ``int(end.timestamp() * 1000)`` ——
       imserver 写库用的是 ``now_ms()``(毫秒),按秒传边界会让区间恒为空、消息量永远是 0;
    2. DSN 形如 ``mysql://user:pass@host:port/db``,**按最后一个 ``@`` 切分** ——
       密码里可能有 ``@``(与 ``deploy/ops/chatapp-backup.sh`` 同一处理);
    3. 该账号**只需要** ``chatapp_im`` 的 SELECT 权限;本模块不写、不改 IM 库任何东西。

注意事项:
    DSN 为空、连不上、查询报错一律返回 ``None`` 并记日志,**绝不抛异常** ——
    看板不能因为 IM 库挂了而整页空白。调用方(``stats.metrics``)只把它填进
    ``DailyMetric.messages``,``None`` 表示「当天没采到」。

文件信息:
    文件名称          stats/im_source.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import logging
from datetime import date
from urllib.parse import unquote

from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_PORT = 3306
CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 10

_COUNT_SQL = "SELECT COUNT(*) FROM im_message WHERE created_at >= %s AND created_at < %s"

# 「DSN 没配」只提示一次:回填 30 天会调 30 次,每次都打日志只会把有用的行挤掉
_dsn_missing_logged = False


def _parse_dsn(dsn: str) -> dict:
    """把 ``mysql://user:pass@host:port/db`` 拆成连接参数。

    参数说明:
        dsn: 数据库连接串;``mysql://`` 前缀可省略。

    返回参数:
        含 ``user`` / ``password`` / ``host`` / ``port`` / ``database`` 的字典。

    使用示例:
        ``_parse_dsn("mysql://u:p@127.0.0.1/chatapp_im")``

    备注信息:
        按**最后一个** ``@`` 切分(``rpartition``):密码里可能带 ``@``,按第一个切会把
        密码截断(与 ``deploy/ops/chatapp-backup.sh`` 同一处理);用户名与密码都过
        ``unquote``,所以 DSN 里可以写百分号转义;没写端口时回落 ``DEFAULT_PORT``
        (3306)。DSN 里缺少 ``@`` 或库名时抛 ``ValueError``,由调用方
        :func:`count_messages` 统一降级为 ``None``。
    """
    # 去掉 ``mysql://`` 前缀;按最后一个 @ 切分:密码里可能带 @(与备份脚本同一处理)
    rest = dsn.split("://", 1)[-1]
    userinfo, sep, hostpart = rest.rpartition("@")
    if not sep or not userinfo:
        raise ValueError("DSN 缺少 user:pass@ 段")
    user, _, password = userinfo.partition(":")
    hostport, _, database = hostpart.partition("/")
    if not hostport or not database:
        raise ValueError("DSN 缺少主机或库名")
    host, _, port = hostport.rpartition(":")
    if not host:
        # 没有冒号 ⇒ rpartition 把整串塞进了 port
        host, port = port, ""
    return {
        "user": unquote(user),
        "password": unquote(password),
        "host": host,
        "port": int(port) if port else DEFAULT_PORT,
        "database": database,
    }


def count_messages(day: date) -> int | None:
    """统计 IM 库某一天的消息条数。

    日期区间取 ``Asia/Shanghai`` 自然日(复用 ``stats.metrics.day_range``,避免两套
    切日口径;函数内导入是因为 ``stats.metrics`` 在顶层导入本模块)。

    参数说明:
        day: ``Asia/Shanghai`` 自然日。

    返回参数:
        当天的消息条数;DSN 未配 / 连接或查询失败返回 ``None``(调用方据此留空)。

    使用示例:
        ``count_messages(date(2026, 11, 2))``

    备注信息:
        查询条件是 ``created_at >= 起点 AND created_at < 终点``,两个边界都按
        **epoch 毫秒**传入(``int(start.timestamp() * 1000)``):``im_message.created_at``
        是 imserver 用 ``now_ms()`` 写入的 BIGINT 毫秒,按秒传边界会让区间恒为空、
        消息量永远是 0(2026-11-11 上线后发现并修复)。连接使用
        ``CONNECT_TIMEOUT_SECONDS`` / ``READ_TIMEOUT_SECONDS`` 两个短超时,``finally``
        里关连接;DSN 为空只在本次进程首次调用时记一条 ``info``(回填 30 天会调 30 次),
        其余异常记 ``warning`` 并返回 ``None``,**绝不抛异常**。``pymysql`` 是延迟导入,
        没装或没用到时本模块仍可正常加载。
    """
    from .metrics import day_range   # 局部导入:metrics 顶层导入本模块,避免循环导入

    global _dsn_missing_logged

    dsn = getattr(settings, "IM_MYSQL_DSN", "") or ""
    if not dsn:
        if not _dsn_missing_logged:
            _dsn_missing_logged = True
            logger.info("IM_MYSQL_DSN 未配置,消息量留空(本次运行不再重复提示)")
        return None
    try:
        import pymysql

        params = _parse_dsn(dsn)
        start, end = day_range(day)
        conn = pymysql.connect(
            user=params["user"], password=params["password"],
            host=params["host"], port=params["port"], database=params["database"],
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            read_timeout=READ_TIMEOUT_SECONDS,
            charset="utf8mb4",
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    _COUNT_SQL,
                    (int(start.timestamp() * 1000), int(end.timestamp() * 1000)),
                )
                row = cursor.fetchone()
        finally:
            conn.close()
    except Exception:
        logger.warning("IM 库读取失败 day=%s,消息量留空", day, exc_info=True)
        return None
    return int(row[0]) if row else 0
