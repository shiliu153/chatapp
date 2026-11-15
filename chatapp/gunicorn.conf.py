"""gunicorn 配置:只为 Prometheus 多进程指标服务(其他参数仍走命令行)。

为什么需要(2026-11-05,E-4 复查时发现的既有缺陷):
    现网 gunicorn 是 ``-w 2``,而 ``prometheus_client`` 的计数器默认是**进程内**的:
    每个 worker 各记一份,Prometheus 每次抓取只落在其中一个 worker 上。实测 20 次请求后
    两个 worker 分别记到 10 和 12,抓取结果在两者之间跳 —— ``rate()`` 还会把「另一个
    worker 的数更小」当成计数器重置,于是 QPS/p99 全都不准(业务指标更是有一半事件看不见)。

做法(``prometheus_client`` 官方方案):
    * 设 ``PROMETHEUS_MULTIPROC_DIR``(生产指向 /dev/shm 下的目录,tmpfs 不占磁盘);
    * 各 worker 把数值写进共享 mmap 文件;``config/metrics.py::render`` 用
      ``MultiProcessCollector`` 合并;
    * 本文件负责两件生命周期的事:master 启动前清空残留文件、worker 退出时删掉自己的文件
      (否则死进程的数值会一直参与合计,计数器只增不减)。

**本文件绝对不能在模块顶层 import prometheus_client**(2026-11-05 上线时踩过):
    ``prometheus_client`` 在 import 时按环境变量决定用 mmap 还是进程内字典
    (``values.ValueClass``),这个判断**只做一次**。master 一旦先 import 了它再 fork,
    worker 继承的就是「进程内」那个实现 —— .env 里的 ``PROMETHEUS_MULTIPROC_DIR`` 形同虚设,
    /metrics 只剩旧文件里的残值。实测现象:配置全对、抓取 200,但输出只有两行
    (没有 http_requests_total)。所以只在真正要用的函数里**延迟导入**,让每个 worker
    自己(在 Django 读完 .env 之后)首次导入 prometheus_client。

部署:supervisor 的 gunicorn 命令加 ``-c gunicorn.conf.py``(见 docs/ops/observability.md §2.3)。
命令行里的 ``-b / -w / --threads`` 优先级高于本文件,不会被覆盖。
"""

import glob
import os


def _multiproc_dir() -> str:
    """读取多进程指标目录。

    返回参数:
        ``PROMETHEUS_MULTIPROC_DIR`` 的值;未配置时返回空串(此时本配置什么也不做)。

    使用示例:
        ``path = _multiproc_dir()``

    备注信息:
        每次调用都重读环境变量,不在模块顶层缓存:gunicorn 的 hook 可能在本进程
        读到 .env 之前就被触发。
    """
    return os.environ.get("PROMETHEUS_MULTIPROC_DIR", "")


def on_starting(server):
    """master 启动前准备 mmap 目录。

    参数说明:
        server: gunicorn 的 Arbiter 实例(未使用,由 gunicorn 传入)。

    返回参数:
        无返回值。

    使用示例:
        ``gunicorn config.wsgi:application -c gunicorn.conf.py -b 127.0.0.1:8000 -w 2``
        启动时由 Arbiter 自动调用,无需手工调用。

    备注信息:
        未配置 ``PROMETHEUS_MULTIPROC_DIR`` 时直接返回,不做任何改动。
        会删除目录下所有 ``*.db``(上次 ``kill -9`` 留下的残留),失败静默跳过。
    """
    path = _multiproc_dir()
    if not path:
        return
    os.makedirs(path, exist_ok=True)
    # 上一次若被 kill -9,worker 的 .db 文件会留在原地:不清掉的话,新进程会带着旧数值
    # 继续累加(计数器看起来凭空多了一截)。
    for name in glob.glob(os.path.join(path, "*.db")):
        try:
            os.remove(name)
        except OSError:
            pass


def child_exit(server, worker):
    """worker 退出时删掉它自己的 mmap 文件。

    参数说明:
        server: gunicorn 的 Arbiter 实例(未使用)。
        worker: 退出的 worker,``worker.pid`` 是该进程号。

    返回参数:
        无返回值。

    使用示例:
        worker 退出时由 gunicorn 自动调用 ``child_exit(server, worker)``,无需手工调用。

    备注信息:
        未配置 ``PROMETHEUS_MULTIPROC_DIR`` 时直接返回。``prometheus_client``
        在函数体内延迟导入,理由见模块头的「绝对不能顶层 import」一段。
    """
    if not _multiproc_dir():
        return
    from prometheus_client import multiprocess  # 延迟导入,理由见模块头

    multiprocess.mark_process_dead(worker.pid)
