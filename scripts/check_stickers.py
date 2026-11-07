"""贴纸资源一致性门禁(批次 J-2)。

贴纸是**打包进客户端**的静态资源:App 放 `app/assets/stickers/`,Web 放
`web/public/stickers/`,两边的文件名与字节必须完全一致 —— 否则同一条贴纸消息在
两端会渲染出不同的图(或一端渲染不出来),而这类问题在单元测试里看不出来
(测试用的都是同一份 id 列表)。

三条断言:

1. 两边的文件名集合相同(多一个/少一个都红);
2. 同名文件逐字节相同;
3. 每张图都是 512×512 的 PNG(只读 IHDR,不依赖 Pillow:CI 的 `contract.yml`
   只装了 PyYAML)。

用法(仓库根目录):

    python scripts/check_stickers.py

退出码 0 = 通过;1 = 有缺口(逐条打印原因)。
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "app" / "assets" / "stickers"
WEB_DIR = REPO_ROOT / "web" / "public" / "stickers"

EXPECTED_SIZE = (512, 512)

# PNG 文件头 8 字节 + IHDR 长度/类型 8 字节,宽度与高度是紧接着的两个大端 uint32。
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def png_size(path: Path) -> tuple[int, int]:
    """读 PNG 的 IHDR 拿宽高。

    Args:
        path: PNG 文件路径。

    Returns:
        ``(宽, 高)``。

    Raises:
        ValueError: 不是合法 PNG(魔数或 IHDR 对不上)。
    """
    raw = path.read_bytes()
    if len(raw) < 24 or not raw.startswith(PNG_MAGIC):
        raise ValueError(f"{path} 不是 PNG")
    if raw[12:16] != b"IHDR":
        raise ValueError(f"{path} 缺少 IHDR")
    width, height = struct.unpack(">II", raw[16:24])
    return width, height


def names_in(directory: Path) -> set[str]:
    """列出一个贴纸目录里的 PNG 文件名。

    Args:
        directory: 贴纸目录。

    Returns:
        文件名集合(含扩展名)。
    """
    if not directory.is_dir():
        return set()
    return {item.name for item in directory.iterdir() if item.is_file()}


def main() -> int:
    """执行三条断言并打印结论。

    Returns:
        进程退出码:0 通过,1 有缺口。
    """
    problems: list[str] = []

    app_names = names_in(APP_DIR)
    web_names = names_in(WEB_DIR)
    if not app_names:
        problems.append(f"App 侧没有贴纸资源: {APP_DIR}")
    if not web_names:
        problems.append(f"Web 侧没有贴纸资源: {WEB_DIR}")

    for name in sorted(app_names - web_names):
        problems.append(f"App 有、Web 没有: {name}")
    for name in sorted(web_names - app_names):
        problems.append(f"Web 有、App 没有: {name}")

    for name in sorted(app_names & web_names):
        app_file = APP_DIR / name
        web_file = WEB_DIR / name
        if app_file.read_bytes() != web_file.read_bytes():
            problems.append(f"两端字节不一致: {name}")
        for directory, label in ((APP_DIR, "App"), (WEB_DIR, "Web")):
            try:
                size = png_size(directory / name)
            except ValueError as error:
                problems.append(str(error))
                continue
            if size != EXPECTED_SIZE:
                problems.append(f"{label} 侧 {name} 尺寸是 {size},应为 {EXPECTED_SIZE}")

    if problems:
        print("贴纸资源不一致:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(f"贴纸资源一致:{len(app_names)} 张,两端逐字节相同,均为 {EXPECTED_SIZE[0]}×{EXPECTED_SIZE[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
