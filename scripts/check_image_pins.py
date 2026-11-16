"""镜像引用钉死门禁(第五轮审计 L-3)。

为什么需要它
------------
`deploy/**` 与 `imserver/**` 里的镜像引用决定「下一次构建或部署拿到的到底是什么」。
裸 tag(`redis:7-alpine`、`certbot/certbot:latest`、`ubuntu:24.04`)是**可变**的:registry 上
同名 tag 被重推,同一份 compose 文件就会拉出另一份内容,而供应链漂移不会报任何错。

L-3 的整改把 deploy 侧六个镜像与 imserver 侧三处都钉成了「版本 tag + 多架构 index digest」
(#381 / #382 / #383)。这条门禁的唯一目的,是让那件事**不会因为下一个新加的服务而退化** ——
「钉 digest」靠人记得,等于没钉。

判定口径(只有三条)
--------------------
1. 扫描范围:`deploy/` 与 `imserver/` 下名为 `Dockerfile*` / `*.Dockerfile` 的文件(取 `FROM`),
   以及**名字里含 `.yml` / `.yaml`** 的文件(取 `image:`)—— 后者刻意不用文件后缀判,
   否则 `deploy/docker-compose.yml.tmpl` 会被漏掉,而它正是最该守的那份模板;
2. 引用必须形如 `<名称>:<tag>@sha256:<64 位十六进制>`;
3. 三类豁免:自建镜像(名称形如 `chatapp-xxx` / `imserver`,由 compose 的 `build:` 产出)、
   `FROM` 里的 stage 别名与 `scratch`、含 `${...}` 插值的引用(值来自 compose 变量,静态判不了)。

用法(仓库根目录):

    python scripts/check_image_pins.py --check     # 门禁入口:0 通过,1 有裸 tag
    python scripts/check_image_pins.py --list      # 人读:逐个引用打印判定与原因

备注信息:
    本脚本**不联网、不读 registry**,只判断「有没有写 digest」。digest 是否真实存在、是否
    指向预期的架构,由部署侧的 `docker buildx imagetools inspect` / `docker pull` 保证。
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: 参与扫描的子树(相对仓库根)。刻意只收这两处:`.github/workflows/` 的 `services:` 镜像
#: 属另一条轨,收进来会顺手把 CI 配置也纳入本门禁,超出 L-3 的范围。
SCAN_ROOTS = ("deploy", "imserver")

#: `@sha256:` 后面必须是 64 位十六进制 —— 只写 `@sha256:` 而不带值要判红。
PINNED_RE = re.compile(r"@sha256:[0-9a-f]{64}$")

#: 自建镜像:由 compose 的 `build:` 产出,天然没有 digest。
LOCAL_IMAGE_RE = re.compile(r"^(?:chatapp-[a-z0-9]+|imserver)(?::[A-Za-z0-9._-]+)?$")

#: Dockerfile 的 `FROM`,允许前置 `--platform=` 之类的 flag 与行尾注释。
FROM_RE = re.compile(r"^\s*FROM\s+(?P<rest>.+?)(?:\s+#.*)?$", re.IGNORECASE)

#: compose 的 `image:`,值可能带引号,行尾可能跟注释。
IMAGE_RE = re.compile(r"^\s*-?\s*image:\s*(?P<value>\S+)(?:\s+#.*)?\s*$")

#: `FROM <ref> AS <stage>` 里的 stage 名。
AS_RE = re.compile(r"\bAS\s+(?P<stage>[A-Za-z0-9_.-]+)\s*$", re.IGNORECASE)


def iter_target_files(root: Path = REPO_ROOT) -> Iterator[Path]:
    """列出参与扫描的文件。

    参数说明:
        root: 仓库根目录,默认本文件所在仓库。

    返回参数:
        逐个产出 `deploy/` 与 `imserver/` 下的 Dockerfile 与 YAML 文件路径(已排序)。

    使用示例:
        ``for path in iter_target_files():``

    备注信息:
        不存在的子树直接跳过 —— 自测会用只造了一半目录的临时仓库。
    """
    found: list[Path] = []
    for name in SCAN_ROOTS:
        base = root / name
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            file_name = path.name
            if file_name.startswith("Dockerfile") or file_name.endswith(".Dockerfile"):
                found.append(path)
            elif ".yml" in file_name or ".yaml" in file_name:
                # 用「名字里含 .yml/.yaml」而不是 `suffix in {".yml",".yaml"}`:
                # deploy/docker-compose.yml.tmpl 的 suffix 是 `.tmpl`,按 suffix 判会**静默漏掉
                # 整个主 compose 模板** —— 那正是本门禁最该守的文件(自测里钉住了这一条)。
                found.append(path)
    yield from sorted(found)


def references_in(path: Path) -> list[tuple[int, str]]:
    """取一个文件里的镜像引用。

    参数说明:
        path: 待扫描的文件(Dockerfile 或 YAML)。

    返回参数:
        ``(行号, 引用)`` 列表;行号从 1 开始。Dockerfile 只看 `FROM`,YAML 只看 `image:`。

    使用示例:
        ``references_in(Path("deploy/docker-compose.yml.tmpl"))``

    备注信息:
        只做行级匹配,不解析 YAML —— 门禁要的是「这条引用有没有写 digest」,不是完整的
        compose 语义;真解析反而会把 `x-app` 锚点、profile 之类无关结构卷进来。
    """
    refs: list[tuple[int, str]] = []
    stages: set[str] = set()
    text = path.read_text(encoding="utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), start=1):
        from_match = FROM_RE.match(line)
        if from_match:
            tokens = [
                token for token in from_match.group("rest").split() if not token.startswith("--")
            ]
            if not tokens:
                continue
            ref = tokens[0]
            stage_match = AS_RE.search(from_match.group("rest"))
            if stage_match:
                stages.add(stage_match.group("stage").lower())
            if ref.lower() in stages or ref.lower() == "scratch":
                continue
            refs.append((lineno, ref))
            continue
        image_match = IMAGE_RE.match(line)
        if image_match:
            refs.append((lineno, image_match.group("value").strip("\"'")))
    return refs


def verdict(ref: str) -> tuple[bool, str]:
    """判定一条引用是否合格。

    参数说明:
        ref: 镜像引用,例如 ``mysql:8.0.46@sha256:...``。

    返回参数:
        ``(是否合格, 原因)``。合格时原因为空串;不合格时是给人看的短句。

    使用示例:
        ``verdict("redis:7-alpine")`` → ``(False, "裸 tag...")``

    备注信息:
        判定顺序是「先豁免、后要求 digest」:豁免项(自建镜像 / 插值)本来就不该有 digest,
        先判 digest 会把它们报成违规。
    """
    if "${" in ref or "$(" in ref:
        return True, ""
    if LOCAL_IMAGE_RE.match(ref):
        return True, ""
    if PINNED_RE.search(ref):
        return True, ""
    if "@sha256:" in ref:
        return False, "digest 格式不对(要 @sha256: + 64 位小写十六进制)"
    return False, "裸 tag,没有 @sha256: digest"


def find_unpinned(root: Path = REPO_ROOT) -> list[str]:
    """找出所有没钉 digest 的引用。

    参数说明:
        root: 仓库根目录,默认本文件所在仓库。

    返回参数:
        违例描述列表,每条形如 ``deploy/x.yml:12: redis:7-alpine —— 裸 tag…``。

    使用示例:
        ``problems = find_unpinned()``

    备注信息:
        只返回违例,合格项不占输出 —— 门禁日志要能一眼看出要改哪一行。
    """
    problems: list[str] = []
    for path in iter_target_files(root):
        for lineno, ref in references_in(path):
            ok, reason = verdict(ref)
            if ok:
                continue
            relative = path.relative_to(root).as_posix()
            problems.append(f"{relative}:{lineno}: {ref} —— {reason}")
    return problems


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    参数说明:
        argv: 参数列表,默认取 ``sys.argv[1:]``。

    返回参数:
        进程退出码:0 通过,1 有违例。

    使用示例:
        ``python scripts/check_image_pins.py --check``

    备注信息:
        ``--list`` 只打印、不判红,便于排查「为什么这条被判成自建镜像」。
    """
    parser = argparse.ArgumentParser(description="镜像引用必须带 @sha256: digest")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="门禁入口(默认):有违例退出码 1")
    group.add_argument("--list", action="store_true", help="逐个打印引用与判定,不判红")
    args = parser.parse_args(argv)

    if args.list:
        for path in iter_target_files():
            for lineno, ref in references_in(path):
                ok, reason = verdict(ref)
                relative = path.relative_to(REPO_ROOT).as_posix()
                mark = "OK  " if ok else "BARE"
                print(f"{mark} {relative}:{lineno}: {ref}{'' if ok else ' —— ' + reason}")
        return 0

    problems = find_unpinned()
    if problems:
        print("镜像引用没钉 digest(第五轮审计 L-3;口径见 deploy/README.md §12.1):")
        for problem in problems:
            print(f"  - {problem}")
        print("修法:docker buildx imagetools inspect <tag> 取 Digest: 那一行,写成 <tag>@sha256:<digest>")
        return 1

    print("镜像引用全部钉了 digest(deploy/ 与 imserver/ 下的 Dockerfile 与 YAML)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
