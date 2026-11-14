"""内存压力器:按 100MB 步进吃内存,直到被 OOM killer 干掉或吃满 2GB。

用途:模拟「某个进程内存泄漏」把 2C2G 打爆,观察内核选择谁当牺牲品、
以及被杀的组件能不能自己回来。

文件信息:
    文件名称          scripts/stress/oom_alloc.py
    项目名称          chat_app / 工程脚本
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11
    适用平台          Linux x86_64（本地与 CI）
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import time

chunks = []
for i in range(25):
    chunks.append(bytearray(100 * 1024 * 1024))
    print(f"allocated {(i + 1) * 100} MB", flush=True)
    time.sleep(0.3)
print("finished without OOM", flush=True)
time.sleep(60)
