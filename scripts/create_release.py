"""创建 / 更新 GitHub Release 并上传 APK(只用标准库)。

为什么需要它
------------
``docs/ops/release.md`` 要求「版本号、tag、Release 三者对齐」,但本机**没有 `gh` CLI**;
以前的做法是「Release 待建,材料写进文档等人工网页创建」,结果 1.0.4 / 1.0.7 两版都留了
待办。本机其实一直有 GitHub 凭据(DSH 的 ``mcp-github`` 用的就是同一个 classic PAT,
``repo`` 权限,存在 ``~/.dsh/github-mcp-token.txt``),所以把这一步脚本化:
读取同一个 token → 调 GitHub REST → 建/更新 Release → 传 APK 附件。

用法
----
    python scripts/create_release.py --notes-file /tmp/notes-1.0.7.md \
        --apk app/build/app/outputs/flutter-apk/app-release.apk
    python scripts/create_release.py --dry-run          # 只打印将要做什么

凭据来源(按顺序)
-----------------
1. ``GITHUB_TOKEN`` / ``GITHUB_PERSONAL_ACCESS_TOKEN`` 环境变量;
2. ``~/.dsh/github-mcp-token.txt``(与 ``mcp-github`` 同一个 PAT;文件不存在才回落到环境变量之外)。

设计取舍
--------
- **幂等**:已有同 tag 的 Release 就 PATCH 更新标题/正文,不重复建;
- **附件同名覆盖**:默认先删同名 asset 再上传,避免 ``already_exists`` 报错;
- **不打印 token**:所有输出只出现仓库、tag、Release URL 与附件大小;
- **不依赖 ``gh`` / 第三方库**:标准库 ``urllib`` 就够,CI 与任意 Python 3.10+ 都能跑。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBSPEC = REPO_ROOT / "app" / "pubspec.yaml"
DEFAULT_TOKEN_FILE = Path.home() / ".dsh" / "github-mcp-token.txt"
DEFAULT_REPO = "shiliu153/chatapp"
DEFAULT_APK = REPO_ROOT / "app" / "build" / "app" / "outputs" / "flutter-apk" / "app-release.apk"
API = "https://api.github.com"
UPLOAD_API = "https://uploads.github.com"
PUBSPEC_VERSION_RE = re.compile(r"^version:\s*([0-9][^\s+]*)", re.MULTILINE)


def read_version() -> str:
    """读取 ``app/pubspec.yaml`` 的版本名(不含构建号)。

    Returns:
        版本名,如 ``1.0.7``。

    Raises:
        SystemExit: 文件或 ``version:`` 行不存在。
    """
    try:
        text = PUBSPEC.read_text(encoding="utf-8")
    except OSError as error:
        _fail(f"读不到 {PUBSPEC}:{error}")
    match = PUBSPEC_VERSION_RE.search(text)
    if not match:
        _fail(f"{PUBSPEC} 里找不到 version: 行")
    return match.group(1)


def read_token() -> str:
    """按优先级取 GitHub token。

    Returns:
        PAT 字符串。

    Raises:
        SystemExit: 环境变量与 token 文件都没有。
    """
    for name in ("GITHUB_TOKEN", "GITHUB_PERSONAL_ACCESS_TOKEN"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    if DEFAULT_TOKEN_FILE.exists():
        value = DEFAULT_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if value:
            return value
    _fail(
        "找不到 GitHub token:请设 GITHUB_TOKEN,或把 PAT 写到 "
        f"{DEFAULT_TOKEN_FILE}(与 mcp-github 用的是同一个文件)")
    return ""  # 不可达;让类型检查安心


def _request(method: str, url: str, token: str, *, payload: dict | None = None,
             raw: bytes | None = None, content_type: str = "application/json") -> tuple[int, dict]:
    """发一次 GitHub API 请求。

    Args:
        method: HTTP 方法。
        url: 完整 URL。
        token: GitHub PAT。
        payload: JSON body(与 ``raw`` 二选一)。
        raw: 二进制 body(上传附件用)。
        content_type: ``Content-Type``。

    Returns:
        ``(HTTP 状态码, 解析后的 JSON)``;空响应体返回 ``{}``。

    Raises:
        SystemExit: 网络错误或非 2xx/404 之外的不可恢复错误。
    """
    body = raw if raw is not None else (
        json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None)
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("User-Agent", "chatapp-release-script")
    if body is not None:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            text = response.read().decode("utf-8")
            return response.status, (json.loads(text) if text.strip() else {})
    except urllib.error.HTTPError as error:
        text = error.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = {"message": text}
        return error.code, parsed
    except urllib.error.URLError as error:
        _fail(f"网络错误:{error.reason}")


def find_release(repo: str, tag: str, token: str) -> dict | None:
    """查同 tag 的 Release。

    Args:
        repo: ``owner/name``。
        tag: tag 名,如 ``v1.0.7``。
        token: GitHub PAT。

    Returns:
        Release JSON;不存在时返回 ``None``。
    """
    status, data = _request("GET", f"{API}/repos/{repo}/releases/tags/{urllib.parse.quote(tag)}",
                            token)
    if status == 404:
        return None
    if status != 200:
        _fail(f"查询 Release 失败:{status} {data.get('message', '')}")
    return data


def create_or_update_release(repo: str, tag: str, title: str, notes: str, token: str,
                             *, dry_run: bool = False) -> dict:
    """创建或更新 Release(标题与正文)。

    Args:
        repo: ``owner/name``。
        tag: tag 名。
        title: Release 标题。
        notes: notes 正文(markdown)。
        token: GitHub PAT。
        dry_run: 只打印,不写。

    Returns:
        Release JSON(``dry_run`` 时为 ``{"html_url": "(dry-run)"}``)。
    """
    existing = find_release(repo, tag, token)
    if dry_run:
        action = "更新" if existing else "创建"
        print(f"[dry-run] 将{action} Release {tag}({title});notes {len(notes)} 字符")
        return {"html_url": "(dry-run)"}
    if existing:
        status, data = _request("PATCH", f"{API}/repos/{repo}/releases/{existing['id']}", token,
                                payload={"name": title, "body": notes})
        if status != 200:
            _fail(f"更新 Release 失败:{status} {data.get('message', '')}")
        print(f"[release] 已更新 {tag}:{data['html_url']}")
        return data
    status, data = _request("POST", f"{API}/repos/{repo}/releases", token,
                            payload={"tag_name": tag, "name": title, "body": notes,
                                     "draft": False, "prerelease": False})
    if status != 201:
        _fail(f"创建 Release 失败:{status} {data.get('message', '')}")
    print(f"[release] 已创建 {tag}:{data['html_url']}")
    return data


def upload_asset(repo: str, release: dict, apk: Path, token: str, *, dry_run: bool = False,
                 asset_name: str | None = None) -> None:
    """上传 APK 附件(同名先删后传,保证幂等)。

    Args:
        repo: ``owner/name``。
        release: Release JSON(需要 ``id`` 与 ``assets``)。
        apk: 本地 APK 路径。
        token: GitHub PAT。
        dry_run: 只打印,不写。
        asset_name: 附件名;默认用文件名(发版规范要求 ``chatapp-<版本>.apk``)。
    """
    name = asset_name or apk.name
    size = apk.stat().st_size
    if dry_run:
        print(f"[dry-run] 将上传附件 {name}({size} 字节)到 Release {release.get('tag_name', '')}")
        return
    for asset in release.get("assets", []):
        if asset.get("name") == name:
            status, data = _request("DELETE", f"{API}/repos/{repo}/releases/assets/{asset['id']}",
                                    token)
            if status not in (204, 404):
                _fail(f"删除旧附件失败:{status} {data.get('message', '')}")
            print(f"[release] 已删除同名旧附件 {name}")
    query = urllib.parse.urlencode({"name": name})
    status, data = _request(
        "POST", f"{UPLOAD_API}/repos/{repo}/releases/{release['id']}/assets?{query}", token,
        raw=apk.read_bytes(), content_type="application/vnd.android.package-archive")
    if status != 201:
        _fail(f"上传附件失败:{status} {data.get('message', '')}")
    print(f"[release] 已上传附件 {name}({size} 字节)")
    print(f"[release] 下载地址:{data.get('browser_download_url', '')}")


def _fail(message: str) -> None:
    """打印错误并以退出码 1 结束。

    Args:
        message: 错误描述。

    Raises:
        SystemExit: 总是抛出,退出码 1。
    """
    print(f"[release] {message}", file=sys.stderr)
    raise SystemExit(1)


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    Args:
        argv: 参数列表;``None`` 表示取 ``sys.argv[1:]``。

    Returns:
        退出码:0 成功,1 失败。
    """
    parser = argparse.ArgumentParser(description="创建/更新 GitHub Release 并上传 APK")
    parser.add_argument("--version", help="版本名;默认读 app/pubspec.yaml")
    parser.add_argument("--title", help="Release 标题;默认 `v<版本> — <主题>` 需要 --topic")
    parser.add_argument("--topic", help="一句话主题(标题里的破折号后半段)")
    parser.add_argument("--notes-file", type=Path, help="notes 文件(markdown)")
    parser.add_argument("--notes", help="notes 正文(与 --notes-file 二选一)")
    parser.add_argument("--apk", type=Path, default=DEFAULT_APK, help="APK 路径;不存在则跳过上传")
    parser.add_argument("--asset-name", help="附件名;默认 <版本>.apk 之外的 APK 文件名,发版请传 chatapp-<版本>.apk")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="owner/name,默认 shiliu153/chatapp")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要做什么")
    args = parser.parse_args(argv)

    version = args.version or read_version()
    tag = f"v{version}"
    title = args.title or (f"{tag} — {args.topic}" if args.topic else tag)
    if args.notes_file:
        notes = args.notes_file.read_text(encoding="utf-8")
    elif args.notes:
        notes = args.notes
    else:
        _fail("请用 --notes-file 或 --notes 给出 Release 正文(与 docs/ops/release.md §6 的草稿一致)")

    token = read_token()
    release = create_or_update_release(args.repo, tag, title, notes, token, dry_run=args.dry_run)
    if args.apk and args.apk.exists():
        upload_asset(args.repo, release, args.apk, token, dry_run=args.dry_run,
                     asset_name=args.asset_name)
    elif args.apk:
        print(f"[release] 跳过附件:找不到 {args.apk}")
    print(f"[release] 完成。请把 Release 链接回填到 docs/ops/release.md §5。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
