"""动态举报去重键(L-2)。

背景:``PostReport`` 之前只有应用层的 ``get_or_create``,并发提交会落两条待处理举报。
本迁移加一个可空唯一键,并给存量待处理举报回填;同一 ``(举报人, 动态)`` 的重复行
合并为「已处理」,避免加唯一索引失败。
"""

from django.db import migrations, models

PENDING = "pending"
HANDLED = "handled"


def fill_dedupe_keys(apps, schema_editor):
    """给存量待处理举报补去重键;同键重复行标记为已处理。

    Args:
        apps: 迁移期应用注册表。
        schema_editor: 迁移期数据库编辑器(未使用)。
    """
    PostReport = apps.get_model("feed", "PostReport")
    seen = set()
    for report in PostReport.objects.filter(status=PENDING).order_by("id"):
        key = f"{report.reporter_id}:{report.post_id}:{PENDING}"
        if key in seen:
            report.status = HANDLED
            report.handled_note = "重复举报自动合并"
            report.dedupe_key = None
        else:
            seen.add(key)
            report.dedupe_key = key
        report.save(update_fields=["status", "handled_note", "dedupe_key"])


class Migration(migrations.Migration):
    """加去重键并回填存量数据。"""

    dependencies = [("feed", "0003_postimage_bytes")]

    operations = [
        migrations.AddField(
            model_name="postreport",
            name="dedupe_key",
            field=models.CharField(blank=True, editable=False, max_length=80,
                                   null=True, unique=True, verbose_name="去重键"),
        ),
        migrations.RunPython(fill_dedupe_keys, migrations.RunPython.noop),
    ]
