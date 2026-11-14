"""每日运营指标快照命令:一天一行写入 ``stats.DailyMetric``。

生产上由宝塔计划任务每天 **04:30** 跑一次(排在 03:20 备份 / 03:40 轮换 /
04:00–04:20 媒体维护之后),只算昨天::

    python manage.py metrics_daily

手动排查或首次上线回填最近 30 天::

    python manage.py metrics_daily --backfill 30 --dry-run   # 先看数字
    python manage.py metrics_daily --backfill 30             # 再写库

注意事项:
    DAU / 活跃时段 / 留存依赖 ``users.activity`` 的 45 天 TTL,**只有上线之后**才有
    数据 —— 回填更早的日期时这几个字段留空(``None``),这是预期行为,不是 bug。
    命令遇到 IM 库读不到只留空消息量并**仍然退出 0**;参数非法或写库异常退出 1。

关联文档:
    - 口径表与排障:docs/ops/runbook.md §9「每日运营指标快照」

文件信息:
    文件名称          stats/management/commands/metrics_daily.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stats.metrics import RETENTION_FIELDS, build_snapshot, fill_retention, save_snapshot

DATE_FORMAT = "%Y-%m-%d"


def _show(value) -> str:
    """把缺失值渲染成 ``-``(与命令输出约定一致)。

    参数说明:
        value: 任意指标值,``None`` 表示没采到。

    返回参数:
        可打印的文本。

    使用示例:
        ``_show(None)``

    备注信息:
        只有 ``None`` 才渲染成 ``-``,整数 0 照常打印 ``0`` —— 这正是「没采到」与
        「采到了 0」在输出上的区分;``0`` 不能被写成假值判断(不能用 ``value or "-"``)。
    """
    return "-" if value is None else str(value)


def _format_line(day, snapshot) -> str:
    """拼出一天的单行输出。

    参数说明:
        day: 本地自然日。
        snapshot: :func:`stats.metrics.build_snapshot` 的返回值。

    返回参数:
        形如 ``2026-11-09 dau=12 new=3 done=1 like=40 pass=25 match=8 msg=137 d1=- d7=-``。

    使用示例:
        ``_format_line(date(2026, 11, 9), build_snapshot(date(2026, 11, 9)))``

    备注信息:
        字段顺序固定,``dau`` / ``msg`` / ``d1`` / ``d7`` 四个可能缺失的值走
        :func:`_show` 渲染成 ``-``,其余计数直接打整数;``active_hours`` 不打进单行
        (24 个数字太长),要看分布请读库或看板。
    """
    return (
        f"{day:%Y-%m-%d} dau={_show(snapshot['dau'])} new={snapshot['new_users']}"
        f" done={snapshot['profiles_completed']} like={snapshot['swipes_like']}"
        f" pass={snapshot['swipes_pass']} match={snapshot['matches']}"
        f" msg={_show(snapshot['messages'])}"
        f" d1={_show(snapshot['retention_d1'])} d7={_show(snapshot['retention_d7'])}"
    )


class Command(BaseCommand):
    """生成每日运营指标快照(幂等,可回填)。

    参数说明:
        无构造参数;命令行参数在 :meth:`add_arguments` 里注册(``--date`` /
        ``--backfill`` / ``--dry-run``)。

    返回参数:
        无返回值;每天一行打印到 ``stdout``,写库结果落 ``stats.DailyMetric``。

    使用示例:
        ``python manage.py metrics_daily --date 2026-11-09``

    备注信息:
        ``help`` 的语义是「生成每日运营指标快照到 ``stats.DailyMetric``(缺省算昨天,
        可 ``--backfill``)」—— 不带参数就只算 ``Asia/Shanghai`` 的昨天,不改历史;
        幂等靠 ``DailyMetric.date`` 唯一约束 + ``update_or_create``,同一天重跑覆盖不新增。
        生产由宝塔计划任务每天 04:30 跑一次(排在备份 / 日志轮换 / 媒体维护之后)。
    """

    help = "生成每日运营指标快照到 stats.DailyMetric(缺省算昨天,可 --backfill)"

    def add_arguments(self, parser):
        """注册命令行参数。

        参数说明:
            parser: argparse 解析器。

        返回参数:
            无返回值。

        使用示例:
            ``python manage.py metrics_daily --date 2026-11-09 --dry-run``

        备注信息:
            ``--date`` 缺省为 ``None``,由 :meth:`_parse_date` 解释成「昨天」;
            ``--backfill`` 缺省为 ``None``,表示只算 ``--date`` 那一天(不是 0);
            ``--dry-run`` 是 ``store_true``,只打印不写库,并跳过留存补算。
        """
        parser.add_argument(
            "--date", default=None,
            help="目标日期 YYYY-MM-DD;缺省 = 昨天(Asia/Shanghai)",
        )
        parser.add_argument(
            "--backfill", type=int, default=None,
            help="以 --date 为终点往前共 N 天(含端点);缺省只算 --date 当天",
        )
        parser.add_argument("--dry-run", action="store_true", help="只打印,不写库")

    def handle(self, *args, **options):
        """按窗口逐日算快照,再补前后两天的留存。

        参数说明:
            *args: 位置参数(未使用)。
            **options: 命令行选项。

        返回参数:
            None。

        使用示例:
            ``python manage.py metrics_daily --backfill 30 --dry-run``

        备注信息:
            执行顺序是:先逐日 ``build_snapshot`` 并立刻 ``save_snapshot``(同一天只算一次,
            ``snapshots`` 留一份供末尾统计),再在窗口内每天补两档留存,最后补窗口端点
            之外的前一天 / 七天前 —— 「每天只跑昨天」时,昨天那一行的次日留存只能靠
            今天这次运行的端点外补算。``--dry-run`` 时跳过所有写库与留存补算,只打印。
            IM 库读不到只留空消息量并**仍然返回**(退出码 0);日期格式非法、
            ``--backfill`` 不为正抛 ``CommandError``,写库异常包装成 ``CommandError``
            (两者都让进程退出 1,便于计划任务告警)。
        """
        dry_run = bool(options["dry_run"])
        end_day = self._parse_date(options.get("date"))
        window = self._window(end_day, options.get("backfill"))

        snapshots = {}
        for day in window:
            snapshot = build_snapshot(day)
            snapshots[day] = snapshot
            if not dry_run:
                try:
                    save_snapshot(day, snapshot)
                except Exception as exc:
                    raise CommandError(f"写库失败 {day:%Y-%m-%d}:{exc}") from exc
            self.stdout.write(_format_line(day, snapshot))

        if dry_run:
            # 留存的回填步骤要写库(只 update 已存在的行),dry-run 下直接跳过
            self.stdout.write("dry-run:未写库,留存回填步骤已跳过")
        else:
            self._fill_window_retention(window)
            self._fill_edge_retention(end_day)

        with_data = sum(1 for snapshot in snapshots.values() if snapshot["dau"] is not None)
        self.stdout.write(
            f"窗口 {len(window)} 天({window[0]:%Y-%m-%d} ~ {window[-1]:%Y-%m-%d}),"
            f"有活跃数据 {with_data} 天"
        )

    def _parse_date(self, raw):
        """解析 ``--date``;缺省取「昨天」。

        参数说明:
            raw: 命令行传入的字符串,可能为 ``None``。

        返回参数:
            本地自然日。

        使用示例:
            ``self._parse_date("2026-11-09")``

        备注信息:
            「昨天」按 ``timezone.localdate() - 1 天`` 算,时区是 ``settings.TIME_ZONE``
            (``Asia/Shanghai``),不是 UTC 的昨天。格式不是 ``YYYY-MM-DD`` 抛
            ``CommandError``(委托 ``datetime.strptime`` 判定,像 ``2026-13-01`` 这种
            月日越界也在这里被拦下)。
        """
        if not raw:
            return timezone.localdate() - timedelta(days=1)
        try:
            return datetime.strptime(raw, DATE_FORMAT).date()
        except ValueError as exc:
            raise CommandError(f"--date 需要 YYYY-MM-DD,收到:{raw}") from exc

    def _window(self, end_day, backfill):
        """算出要处理的日子,按时间升序、含 ``end_day`` 端点。

        参数说明:
            end_day: 窗口终点。
            backfill: ``--backfill`` 的值,``None`` 表示只算终点那一天。

        返回参数:
            日期列表(升序)。

        使用示例:
            ``self._window(date(2026, 11, 9), 3)``

        备注信息:
            返回 ``backfill`` 天且**含端点**:``--backfill 3 --date 2026-11-09`` 得到
            ``[11-07, 11-08, 11-09]``,不是从 11-10 往前数;``None`` 只返回终点一天。
            升序由 ``range(days - 1, -1, -1)`` 保证,打印顺序与写库顺序一致。
            ``backfill <= 0`` 抛 ``CommandError``:0 或负数会得到空窗口,静默什么都不做
            比报错更难查。
        """
        days = 1 if backfill is None else int(backfill)
        if days <= 0:
            raise CommandError(f"--backfill 需要正整数,收到:{backfill}")
        return [end_day - timedelta(days=offset) for offset in range(days - 1, -1, -1)]

    def _fill_window_retention(self, window):
        """给窗口内每一天补留存(目标日没数据就留空)。

        参数说明:
            window: 日期列表。

        返回参数:
            None。

        使用示例:
            ``self._fill_window_retention([date(2026, 11, 9)])``

        备注信息:
            每天都把 ``RETENTION_FIELDS`` 里的两档(``retention_d1`` / ``retention_d7``)
            各补一次,逐个走 ``stats.metrics.fill_retention``(只 ``update`` 已存在的行);
            目标日仍无活跃记录时该字段被写成 ``None``。回填 30 天时这一步总共多发 60 条
            ``UPDATE``,只改留存两列。
        """
        for day in window:
            for field in RETENTION_FIELDS:
                fill_retention(day, field)

    def _fill_edge_retention(self, end_day):
        """补窗口端点之外的两行:前一天(本次算出了 D+1)与七天前(本次算出了 D+7)。

        缺了这一步,「每天只跑昨天」时昨天的次日留存要等到后天那次运行才会被补上,
        而那次运行的窗口里根本没有昨天。

        参数说明:
            end_day: 窗口终点(通常是 --date)。

        返回参数:
            None。

        使用示例:
            ``self._fill_edge_retention(date(2026, 11, 9))``

        备注信息:
            只补两行、不造行:前一天补 ``retention_d1``(它的 D+1 就是 ``end_day``),
            七天前补 ``retention_d7``(它的 D+7 同样是 ``end_day``);对应行不存在时
            ``fill_retention`` 直接返回 ``False``,表里不会凭空多出记录。窗口超过 1 天时
            这两行与窗口内那轮重复计算,结果相同(幂等覆盖)。
        """
        fill_retention(end_day - timedelta(days=1), "retention_d1")
        fill_retention(end_day - timedelta(days=7), "retention_d7")
