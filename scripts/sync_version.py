"""发版版本号与发版记录的单一来源同步器(D-5 第 3 步)。

设计要点:
    版本号的事实来源**只有一个**:``app/pubspec.yaml`` 的 ``version:`` 行(形如
    ``1.0.4+5``,``+5`` 是构建号)。另外两处必须与它的**版本名**部分一致:

    - ``app/lib/core/app_info.dart`` 的 ``appVersion``(App 关于页展示 + 测试守卫);
    - ``web/package.json`` 的 ``version``(网页端关于页与发版)。

    以前这三处靠人手改,漏改的表现很隐蔽(关于页显示旧版本 / 网页端版本号对不上),
    所以这里收敛成一个脚本 + CI 的 ``--check``:

        python scripts/sync_version.py --check   # 只校验,CI 用;不一致退出码 1
        python scripts/sync_version.py --write   # 以 pubspec.yaml 为准写回另外两处

    2026-11-05 起 ``--check`` 还校验**发版记录**:当前版本必须在
    ``docs/releases.yml`` 里有一条,且 ``tag`` 含 ``v<版本>``、``Release`` 非空。理由见
    ``docs/ops/release.md`` §6 —— 版本号、tag、Release 是同一件事的三个面,只做前两件时
    半年后无法回答「线上这个包是哪份代码」。

    2026-11-14(治理第 5 节,C8)起,发版记录从「``release.md`` §5 的 Markdown 表格」
    迁成结构化数据 ``docs/releases.yml``:本脚本只**读**它(``scripts/lib/docs.py``),
    表格由 ``scripts/releases.py`` 渲染。判定语义一字未变,只是不再猜表头。

注意事项:
    只同步「版本名」(``1.0.4``),不同步构建号(``+5``):构建号只在 App 侧有意义。
    读 / 写原语都在 ``scripts/lib/version.py``(``release_prep`` 用的是同一份实现);
    ``--write`` 只做**字符串替换**,不改动文件其余内容与换行风格;发版记录是人工维护的,
    ``--write`` 不会替你写它,只会提示。

文件信息:
    文件名称          scripts/sync_version.py
    项目名称          chat_app / 工程脚本
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11
    适用平台          Linux x86_64（本地与 CI）
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# `python scripts/sync_version.py` 时 sys.path[0] 是 scripts/,显式把仓库根放进去,
# 这样 `from scripts.lib import ...` 在直接跑与 unittest 两种方式下都成立(见 lib/__init__.py)。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib import docs, version  # noqa: E402  (必须在 sys.path 修好之后)


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    参数说明:
        argv: 命令行参数;``None`` 表示取 ``sys.argv[1:]``。

    返回参数:
        退出码:0 一致(或已写回),1 不一致 / 发版记录缺失(``--check`` 模式)。

    使用示例:
        ``python scripts/sync_version.py --check``

    备注信息:
        无特殊约束。
    """
    parser = argparse.ArgumentParser(description="发版版本号同步(app/pubspec.yaml 为准)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="只校验,不一致时退出码 1(默认)")
    mode.add_argument("--write", action="store_true", help="以 pubspec.yaml 为准写回另外两处")
    args = parser.parse_args(argv)

    try:
        expected = version.read_pubspec_version()
    except version.VersionError as error:
        print(f"[版本号] {error}", file=sys.stderr)
        return 1

    if args.write:
        changed = [version.write_app_info_version(expected), version.write_web_version(expected)]
        print(f"[版本号] 已按 {expected} 同步;改动 {sum(changed)} 个文件")
        print(
            f"[发版] 还差三步:① 打 tag 并推送 git tag -a v{expected};"
            f"② 建/更新远端 Release;"
            f"③ 在 docs/releases.yml 加 {expected} 一条,再跑 python scripts/releases.py --render"
        )
        return 0

    try:
        problems = version.collect_mismatches() + docs.check_current(expected)
    except (version.VersionError, docs.DocsError) as error:
        print(f"[版本号] 判不出来:{error}", file=sys.stderr)
        return 1
    if problems:
        for problem in problems:
            print(f"[版本号] {problem}", file=sys.stderr)
        return 1
    print(f"[版本号] 三处一致:{expected};发版记录已留痕")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
