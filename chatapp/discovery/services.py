"""配对相关的领域服务。

目前只有一件事:配对成功后给双方发 IM 灰条。之所以独立成模块而不是写在视图里,
是为了让「配对成功」这件事的副作用只有一个入口,便于后续追加(如推送、埋点)。
"""

from django.db import transaction

from im import tasks as im_tasks


def notify_match(match):
    """配对成功后给双方各发一条 IM 灰条消息(经任务队列,失败可重试)。

    on_commit:配对真正落库后才入队;robust=True:broker 抖动不影响配对结果。
    """
    a_id, b_id = match.user_a_id, match.user_b_id
    transaction.on_commit(lambda: im_tasks.send_match_notice.delay(a_id, b_id), robust=True)
