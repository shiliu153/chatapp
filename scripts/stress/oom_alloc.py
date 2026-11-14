"""内存压力器:按 100MB 步进吃内存,直到被 OOM killer 干掉或吃满 2GB。

用途:模拟「某个进程内存泄漏」把 2C2G 打爆,观察内核选择谁当牺牲品、
以及被杀的组件能不能自己回来。
"""

import time

chunks = []
for i in range(25):
    chunks.append(bytearray(100 * 1024 * 1024))
    print(f"allocated {(i + 1) * 100} MB", flush=True)
    time.sleep(0.3)
print("finished without OOM", flush=True)
time.sleep(60)
