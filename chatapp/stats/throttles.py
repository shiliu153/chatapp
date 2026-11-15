"""个人使用报告接口的限流。

第五轮审计 M-1:``GET /api/v1/stats/me`` 是只读聚合,但 ``period=year`` 时七个标量子查询
各自扫一整年,单请求的成本远高于普通读接口,因此必须与既有读接口同档按用户限流。

设计要点:
    额度配在 ``settings.DEFAULT_THROTTLE_RATES["stats"]``(240 次/小时),``TESTING`` 下放宽
    —— 同一账号在一个测试进程里会连续请求多次,不放宽会跨用例累积触发 429。

关联文档:
    - 接口契约:docs/api/stats.md

文件信息:
    文件名称          stats/throttles.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-16        shiliu153          新增:个人使用报告按用户限流(第五轮 M-1)
"""

from config.throttling import UserScopedThrottle


class StatsThrottle(UserScopedThrottle):
    """按用户限流个人使用报告;额度见 ``settings.DEFAULT_THROTTLE_RATES["stats"]``。

    报告页只在打开「我的数据」时请求一次,``week`` / ``month`` 两个周期很便宜;
    真正贵的是 ``period=year`` —— 七个 ``COUNT(*)`` 标量子查询各自扫一整年,
    单请求查询预算 8 条(见 ``stats/services.py``)。额度按账号计而不是按 IP:
    同一出口 IP 下可能有多台设备,按 IP 会让正常用户互相牵连。
    """

    scope = "stats"
