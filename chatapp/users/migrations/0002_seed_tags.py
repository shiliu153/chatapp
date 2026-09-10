from django.db import migrations

TAGS = [
    ("运动", "sports"), ("音乐", "music"), ("电影", "movie"), ("旅行", "travel"),
    ("美食", "food"), ("宠物", "pet"), ("游戏", "game"), ("读书", "book"),
    ("摄影", "camera"), ("健身", "fitness"), ("动漫", "anime"), ("咖啡", "coffee"),
]


def seed(apps, schema_editor):
    Tag = apps.get_model("users", "Tag")
    for name, icon in TAGS:
        Tag.objects.get_or_create(name=name, defaults={"icon": icon})


def unseed(apps, schema_editor):
    Tag = apps.get_model("users", "Tag")
    Tag.objects.filter(name__in=[name for name, _ in TAGS]).delete()


class Migration(migrations.Migration):
    dependencies = [("users", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
