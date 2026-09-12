from django.db import transaction

from im import tasks as im_tasks


def notify_match(match):
    """配对成功后给双方各发一条 IM 灰条消息(经任务队列,失败可重试)。

    on_commit:配对真正落库后才入队;robust=True:broker 抖动不影响配对结果。
    """
    a_id, b_id = match.user_a_id, match.user_b_id
    transaction.on_commit(lambda: im_tasks.send_match_notice.delay(a_id, b_id), robust=True)
