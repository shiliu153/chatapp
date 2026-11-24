"""App release 清单的 INTERNET 权限门禁。

为什么需要它
------------
``app/android/app/src/main/AndroidManifest.xml`` 是 release 包**唯一**会合并的清单;
Flutter 模板只把 ``android.permission.INTERNET`` 写在 ``debug/`` 与 ``profile/`` 的清单里
(那里是给热重载用的,release 构建不合并)。于是「main 里少写一行」在本地完全无感 ——
模拟器上装 debug 包一切正常,装 release 包则 socket 一律 EPERM,Dio 统一翻成
「网络不给力,请检查网络后重试」,服务端一条请求都收不到。

1.0.1–1.0.14 的**每一个** release 包都是这样(排查记录见
``docs/pitfalls/android-emulator.md`` 的 2026-11-24 条目);#483 把这一行补回了 main,
但补回来之后**没有任何机械手段防止它再次消失** —— 有人把它挪回 ``debug/``、合并冲突时
丢掉、或者照着旧模板重写清单,症状都会在发版后出现在手机上。这条门禁守的就是这一行。

判定口径
--------
1. ``main/AndroidManifest.xml`` 必须声明 ``android.permission.INTERNET``;
2. ``debug/`` 与 ``profile/`` 的清单**不是**唯一声明处 —— main 里有了就够,它们保留是给
   热重载用的,不影响 release。main 缺、只有这两份有时判红,并把这条区别说清楚;
3. 解析失败(清单不存在 / 不是合法 XML)一律判红:判不出来不等于合规。

用法(仓库根目录):

    python scripts/check_app_manifest.py           # 门禁入口:0 通过,1 有违例
    python scripts/check_app_manifest.py --list    # 人读:逐份清单打印判定,不判红

备注信息:
    判据走 XML 解析而不是正则扫文本:被 ``<!-- -->`` 注释掉的 ``<uses-permission>`` 在
    正则下照样命中,而在 XML 解析里它只是注释 —— 那正是「以为守住了其实没有」的形态。
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

#: 仓库根目录(本文件在 ``scripts/`` 下)。
REPO_ROOT = Path(__file__).resolve().parent.parent

#: 三份清单的共同祖先(相对仓库根)。
MANIFEST_BASE = Path("app") / "android" / "app" / "src"

#: release 构建唯一会合并的清单。
MAIN_MANIFEST = "main/AndroidManifest.xml"

#: 只服务热重载的两份清单 —— 它们有 INTERNET 不能代替 main 有。
DEV_MANIFESTS = ("debug/AndroidManifest.xml", "profile/AndroidManifest.xml")

#: 本门禁守的那条权限。
INTERNET_PERMISSION = "android.permission.INTERNET"

#: ``<uses-permission>`` 的 ``android:name`` 属性(带命名空间)。
ANDROID_NAME_ATTR = "{http://schemas.android.com/apk/res/android}name"

#: 违例时指向的排查手册(事故经过与判据都在那里)。
PITFALL_DOC = "docs/pitfalls/android-emulator.md"


class ManifestError(RuntimeError):
    """清单读不出来或不是合法 XML —— 判不出来,按违例处理(不冒充合规)。"""


def manifest_path(relative: str, root: Path | None = None) -> Path:
    """把清单的相对路径拼成绝对路径。

    参数说明:
        relative: 形如 ``main/AndroidManifest.xml`` 的相对路径(相对 ``app/android/app/src``)。
        root: 仓库根目录;``None`` 表示本文件所在仓库。

    返回参数:
        清单的绝对路径(不保证存在)。

    使用示例:
        ``manifest_path("main/AndroidManifest.xml")``

    备注信息:
        自测在临时目录里造清单,所以仓库根参数化;生产路径不参数化。
    """
    return (REPO_ROOT if root is None else Path(root)) / MANIFEST_BASE / relative


def declares_internet(path: Path) -> bool:
    """判断一份清单是否声明了 INTERNET 权限。

    参数说明:
        path: 清单文件路径。

    返回参数:
        `True` 表示声明了;`False` 表示没有声明。

    使用示例:
        ``declares_internet(manifest_path("main/AndroidManifest.xml"))``

    备注信息:
        抛 `ManifestError` 表示文件不存在或不是合法 XML —— 调用方必须把它当违例,
        不能当成 `False` 之外的第三种「无所谓」。
        标签名按 ``}`` 切开后取本地名再判 ``uses-permission`` 前缀:``uses-permission``
        与 ``uses-permission-sdk-23`` 都算声明(后者在 sdk 23+ 生效,权限同样落进包里)。
        被注释掉的声明不算 —— XML 解析不会把注释当成元素,这正是要用它而不是正则的原因。
    """
    if not path.is_file():
        raise ManifestError(f"找不到清单:{path.as_posix()}")
    try:
        tree = ET.fromstring(path.read_text(encoding="utf-8"))
    except (OSError, ET.ParseError) as exc:
        raise ManifestError(f"清单不是合法 XML:{path.as_posix()}({exc})") from exc
    for element in tree.iter():
        if not element.tag.split("}")[-1].startswith("uses-permission"):
            continue
        if element.get(ANDROID_NAME_ATTR) == INTERNET_PERMISSION:
            return True
    return False


def audit(root: Path | None = None) -> list[str]:
    """检查三份清单,返回违例描述。

    参数说明:
        root: 仓库根目录;``None`` 表示本文件所在仓库。

    返回参数:
        违例描述列表;空列表表示合规。每条形如
        ``app/.../main/AndroidManifest.xml 没有 android.permission.INTERNET —— …``。

    使用示例:
        ``problems = audit()``

    备注信息:
        只返回违例:门禁日志要能一眼看出要改哪一行。
        ``debug/`` 与 ``profile/`` 本身缺 INTERNET 不算违例 —— 它们只是热重载用的,
        本门禁关心的是「main 有没有」。main 缺、而这两份有时,违例里会点名这一点,
        因为那正是「以为在 debug 里写了就够」的误判来源。
    """
    problems: list[str] = []
    base = REPO_ROOT if root is None else Path(root)
    main = manifest_path(MAIN_MANIFEST, base)
    relative_main = main.relative_to(base).as_posix()

    try:
        main_ok = declares_internet(main)
    except ManifestError as exc:
        return [f"{exc};main 清单读不出来就无法证明 release 包能联网"]

    if main_ok:
        return problems

    problems.append(
        f"{relative_main} 没有 {INTERNET_PERMISSION}"
        f" —— 缺 INTERNET → release 包会完全没网,见 {PITFALL_DOC}"
    )
    also_declared = [
        name
        for name in DEV_MANIFESTS
        if _declares_quietly(manifest_path(name, base))
    ]
    if also_declared:
        problems.append(
            f"{'、'.join(also_declared)} 里有声明,但那份清单只服务热重载"
            "(release 构建不合并 debug/ 与 profile/),main 里有了才够"
        )
    return problems


def _declares_quietly(path: Path) -> bool:
    """同 `declares_internet`,但把任何异常都当成「没有声明」。

    参数说明:
        path: 清单文件路径。

    返回参数:
        声明了 `True`;没声明或读不出来 `False`。

    使用示例:
        ``_declares_quietly(manifest_path("debug/AndroidManifest.xml"))``

    备注信息:
        只在**已经判红**之后用来补充说明,而缺失的 debug/profile 清单本身不是问题:
        那是 Flutter 模板的自由,不是 release 包能不能联网的证据。
    """
    try:
        return declares_internet(path)
    except ManifestError:
        return False


def render_list(root: Path | None = None) -> list[str]:
    """逐份清单打印判定(人读,不判红)。

    参数说明:
        root: 仓库根目录;``None`` 表示本文件所在仓库。

    返回参数:
        每份清单一行的文本列表,形如 ``OK    app/.../main/AndroidManifest.xml: 声明了 …``。

    使用示例:
        ``print("\\n".join(render_list()))``

    备注信息:
        输出带 `relative_to(root)` 的路径,自测在临时目录里跑时也能对照。
    """
    base = REPO_ROOT if root is None else Path(root)
    lines: list[str] = []
    for name in (MAIN_MANIFEST, *DEV_MANIFESTS):
        path = manifest_path(name, base)
        shown = path.relative_to(base).as_posix()
        try:
            declared = declares_internet(path)
        except ManifestError as exc:
            lines.append(f"MISS  {shown}: {exc}")
            continue
        mark = "OK  " if declared else "NONE"
        note = "声明了 INTERNET" if declared else "没有 INTERNET"
        if name != MAIN_MANIFEST:
            note += "(只服务热重载,不代替 main)"
        lines.append(f"{mark}  {shown}: {note}")
    return lines


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    参数说明:
        argv: 参数列表,默认取 ``sys.argv[1:]``。

    返回参数:
        进程退出码:0 通过,1 有违例。

    使用示例:
        ``python scripts/check_app_manifest.py``

    备注信息:
        ``--list`` 只打印、不判红,便于排查「这份清单到底有没有声明」。
    """
    parser = argparse.ArgumentParser(
        description="App release 清单必须声明 android.permission.INTERNET"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="门禁入口(默认):违例退出码 1")
    group.add_argument("--list", action="store_true", help="逐份清单打印判定,不判红")
    args = parser.parse_args(argv)

    if args.list:
        print("\n".join(render_list()))
        return 0

    problems = audit()
    if problems:
        print("App release 清单没声明 INTERNET(1.0.1–1.0.14 线上包全部因此没网):")
        for problem in problems:
            print(f"  - {problem}")
        print(
            "修法:在 app/android/app/src/main/AndroidManifest.xml 里加 "
            f'<uses-permission android:name="{INTERNET_PERMISSION}" />;'
            " 不要把它挪进 debug/ 或 profile/。"
        )
        return 1

    shown = manifest_path(MAIN_MANIFEST).relative_to(REPO_ROOT).as_posix()
    print(
        f"main 清单声明了 {INTERNET_PERMISSION}({shown};"
        "debug/ 与 profile/ 的声明只服务热重载,main 里有了就够)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
