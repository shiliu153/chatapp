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
"""

from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stats.metrics import RETENTION_FIELDS, build_snapshot, fill_retention, save_snapshot

DATE_FORMAT = "%Y-%m-%d"


def _show(value) -> str:
    """把缺失值渲染成 ``-``(与命令输出约定一致)。

    Args:
        value: 任意指标值,``None`` 表示没采到。

    Returns:
        可打印的文本。
    """
    return "-" if value is None else str(value)


def _format_line(day, snapshot) -> str:
    """拼出一天的单行输出。

    Args:
        day: 本地自然日。
        snapshot: :func:`stats.metrics.build_snapshot` 的返回值。

    Returns:
        形如 ``2026-11-09 dau=12 new=3 done=1 like=40 pass=25 match=8 msg=137 d1=- d7=-``。
    """
    return (
        f"{day:%Y-%m-%d} dau={_show(snapshot['dau'])} new={snapshot['new_users']}"
        f" done={snapshot['profiles_completed']} like={snapshot['swipes_like']}"
        f" pass={snapshot['swipes_pass']} match={snapshot['matches']}"
        f" msg={_show(snapshot['messages'])}"
        f" d1={_show(snapshot['retention_d1'])} d7={_show(snapshot['retention_d7'])}"
    )


class Command(BaseCommand):
    """生成每日运营指标快照(幂等,可回填)。"""

    help = "生成每日运营指标快照到 stats.DailyMetric(缺省算昨天,可 --backfill)"

    def add_arguments(self, parser):
        """注册命令行参数。

        Args:
            parser: argparse 解析器。
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

        Args:
            *args: 位置参数(未使用)。
            **options: 命令行选项。

        Returns:
            None。

        Raises:
            CommandError: 日期格式非法、``--backfill`` 不为正,或写库失败。
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

        Args:
            raw: 命令行传入的字符串,可能为 ``None``。

        Returns:
            本地自然日。

        Raises:
            CommandError: 格式不是 ``YYYY-MM-DD``。
        """
        if not raw:
            return timezone.localdate() - timedelta(days=1)
        try:
            return datetime.strptime(raw, DATE_FORMAT).date()
        except ValueError as exc:
            raise CommandError(f"--date 需要 YYYY-MM-DD,收到:{raw}") from exc

    def _window(self, end_day, backfill):
        """算出要处理的日子,按时间升序、含 ``end_day`` 端点。

        Args:
            end_day: 窗口终点。
            backfill: ``--backfill`` 的值,``None`` 表示只算终点那一天。

        Returns:
            日期列表(升序)。

        Raises:
            CommandError: ``--backfill`` 不为正数。
        """
        days = 1 if backfill is None else int(backfill)
        if days <= 0:
            raise CommandError(f"--backfill 需要正整数,收到:{backfill}")
        return [end_day - timedelta(days=offset) for offset in range(days - 1, -1, -1)]

    def _fill_window_retention(self, window):
        """给窗口内每一天补留存(目标日没数据就留空)。

        Args:
            window: 日期列表。

        Returns:
            None。
        """
        for day in window:
            for field in RETENTION_FIELDS:
                fill_retention(day, field)

    def _fill_edge_retention(self, end_day):
        """补窗口端点之外的两行:前一天(本次算出了 D+1)与七天前(本次算出了 D+7)。

        缺了这一步,「每天只跑昨天」时昨天的次日留存要等到后天那次运行才会被补上,
        而那次运行的窗口里根本没有昨天。

        Args:
            end_day: 窗口终点(通常是 --date)。

        Returns:
            None。
        """
        fill_retention(end_day - timedelta(days=1), "retention_d1")
        fill_retention(end_day - timedelta(days=7), "retention_d7")
