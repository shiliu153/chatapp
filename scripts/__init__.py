"""scripts 包:仓库根级别的运维/工程脚本。

设计要点:
    这里的脚本不属于 Django 项目(chatapp/),也不属于 App 或 Web 工程,而是跨栈的
    工程纪律工具;自测用标准库 ``unittest``,由 CI 直接跑 ``python -m unittest``。
"""
