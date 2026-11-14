"""``scripts/`` 的公共层(治理方案第 5 节:C7 / C8 / C9)。

为什么需要它
------------
2026-11-14 之前,四个发版脚本各自抄了一份 GitHub 常量(仓库名 / token 文件路径 / API 基址 /
token 解析逻辑),三个脚本各自抄了一份 ``app/pubspec.yaml`` 的路径与版本正则;
``release_prep`` 甚至已经把 ``sync_version`` 当 lib 用(import + 复用 3 个函数)——
那条依赖是**隐式**的,而 ``create_release`` / ``deploy_gate`` 是孤岛。

这一层只做一件事:**同一条事实只留一份实现**。

    repo.py       仓库名 / token 文件 / API 基址 / token 解析(环境变量 → 文件)
    version.py    pubspec 路径、版本正则、三处版本号的读 / 写 / 比对
    docs.py       发版记录(``docs/releases.yml``)的解析 / 渲染 / 校验(C8)
    artifacts.py  「生成物 == HEAD」的比对语义(忽略行尾,C9;可独立执行)

导入约定(不各抄一套 ``try/except ImportError``)
------------------------------------------------
入口脚本一律用**同一段两行样板**:

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.lib import repo  # noqa: E402

这两行同时满足两种调用方式:``python scripts/x.py``(此时 ``sys.path[0]`` 是 ``scripts/``)
与 ``python -m unittest scripts.test_x``(仓库根已在 ``sys.path`` 里)。``docs_index.py``
从第 3 节起就是这么写的;这里把它写成约定,而不是第五份手抄。

``artifacts.py`` 是**例外**:它要能被 ``python scripts/lib/artifacts.py <路径>`` 直接执行
(门禁注册表的 ``kind = "artifact"`` 就是这么跑它的),所以它不 import 本包里的任何模块,
仓库根由它自己的 ``__file__`` 推出来。
"""

from __future__ import annotations

from pathlib import Path

#: 仓库根目录。``scripts/lib/__init__.py`` 往上三层:``lib`` → ``scripts`` → 仓库根。
REPO_ROOT = Path(__file__).resolve().parents[2]
