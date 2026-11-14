"""perf 包:可复现的容量测试脚本(`run.py` 跑场景,`report.py` 出表并对比基线)。

声明成包只为一件事:让 CI 能用 `python -m unittest perf.test_run` 导入自测脚本。
两个入口仍按脚本方式使用(`python3 perf/run.py ...`),不依赖包机制。

文件信息:
    文件名称          perf/__init__.py
    项目名称          chat_app / 工程脚本
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11
    适用平台          Linux x86_64（本地与 CI）
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""
