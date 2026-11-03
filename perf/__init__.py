"""perf 包:可复现的容量测试脚本(`run.py` 跑场景,`report.py` 出表并对比基线)。

声明成包只为一件事:让 CI 能用 `python -m unittest perf.test_run` 导入自测脚本。
两个入口仍按脚本方式使用(`python3 perf/run.py ...`),不依赖包机制。
"""
