"""``scripts/check_image_pins.py`` 的自测(纯离线,临时目录里造 compose / Dockerfile / workflow)。

进 CI 的 `contract` 轨。它守的是「镜像引用必须带 digest」这一条供应链纪律,而这类门禁
两个方向都会坏:

- **少报**:新加的服务(或新加的 workflow `services:`)用裸 tag 却没人拦 —— 门禁等于没写,漂移照旧;
- **多报**:自建镜像(`chatapp-web:local`)、`FROM` 的 stage 别名、compose 变量插值、workflow 的
  `uses:` 被误判成裸 tag —— 人被迫在门禁里加白名单,门禁慢慢被关掉。

两边都由下面钉住。
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from scripts import check_image_pins

#: 一个格式完全合法的 digest,只用来测判定逻辑,不对应任何真实镜像。
GOOD_DIGEST = "sha256:" + "a1" * 32


class VerdictTests(unittest.TestCase):
    """单条引用的判定口径。"""

    def test_pinned_reference_passes(self):
        """版本 tag + 合法 digest 通过。"""
        self.assertEqual(check_image_pins.verdict(f"mysql:8.0.46@{GOOD_DIGEST}"), (True, ""))

    def test_bare_tag_is_flagged(self):
        """只有 tag、没有 digest 判红。"""
        ok, reason = check_image_pins.verdict("redis:7-alpine")
        self.assertFalse(ok)
        self.assertIn("digest", reason)

    def test_latest_is_flagged(self):
        """`latest` 是最典型的裸 tag。"""
        self.assertFalse(check_image_pins.verdict("certbot/certbot:latest")[0])

    def test_truncated_digest_is_flagged(self):
        """写了 `@sha256:` 但值不对(长度/字符)也要红 —— 半钉比没钉更危险。"""
        self.assertFalse(check_image_pins.verdict("redis:7-alpine@sha256:deadbeef")[0])

    def test_uppercase_digest_is_flagged(self):
        """digest 必须小写十六进制(registry 的规范形态)。"""
        self.assertFalse(check_image_pins.verdict(f"redis:7-alpine@sha256:{'A1' * 32}")[0])

    def test_local_build_image_is_exempt(self):
        """自建镜像没有 digest,必须豁免。"""
        for ref in ("chatapp-web:local", "chatapp-imserver:local", "chatapp-nginx:local", "imserver:latest"):
            with self.subTest(ref=ref):
                self.assertEqual(check_image_pins.verdict(ref), (True, ""))

    def test_interpolated_reference_is_exempt(self):
        """compose 变量插值的引用静态判不了,豁免。"""
        self.assertTrue(check_image_pins.verdict("${IMSERVER_IMAGE:-imserver:latest}")[0])

    def test_lookalike_local_name_is_flagged(self):
        """豁免只认 `chatapp-*` / `imserver`,别把 `chatappfoo` 也放过。"""
        self.assertFalse(check_image_pins.verdict("chatappfoo:1.0")[0])


class ReferenceParsingTests(unittest.TestCase):
    """从文件里取引用:该取到的取到,该跳过的不算。"""

    def setUp(self):
        """建一个临时仓库根。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        """清理临时目录。"""
        self.tmp.cleanup()

    def _write(self, relative: str, text: str) -> Path:
        """写一个文件。

        参数说明:
            relative: 相对临时仓库根的路径。
            text: 文件内容。

        返回参数:
            写入的文件路径。
        """
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_compose_image_is_read(self):
        """`image:` 的值被取到,行号是 1 起算的真实行号。"""
        path = self._write("deploy/a.yml", "services:\n  x:\n    image: redis:7-alpine\n")
        self.assertEqual(check_image_pins.references_in(path), [(3, "redis:7-alpine")])

    def test_quoted_and_commented_image_is_read(self):
        """带引号、行尾带注释的写法都要取到(漏了就等于放过)。"""
        path = self._write(
            "deploy/a.yml",
            "services:\n  x:\n    image: \"mysql:8.0\"  # 主库\n",
        )
        self.assertEqual(check_image_pins.references_in(path), [(3, "mysql:8.0")])

    def test_dockerfile_from_and_stage_alias(self):
        """`FROM` 取到;`FROM build AS final` 这种 stage 别名不算镜像。"""
        path = self._write(
            "imserver/Dockerfile",
            "FROM ubuntu:24.04 AS build\nFROM build AS final\n",
        )
        self.assertEqual(check_image_pins.references_in(path), [(1, "ubuntu:24.04")])

    def test_dockerfile_platform_flag(self):
        """`FROM --platform=...` 的 flag 不能被当成镜像名。"""
        path = self._write(
            "deploy/docker/Dockerfile",
            "FROM --platform=linux/amd64 python:3.11-slim-bookworm\n",
        )
        self.assertEqual(check_image_pins.references_in(path), [(1, "python:3.11-slim-bookworm")])

    def test_scratch_is_skipped(self):
        """`FROM scratch` 不是 registry 镜像。"""
        path = self._write("deploy/docker/Dockerfile", "FROM scratch\n")
        self.assertEqual(check_image_pins.references_in(path), [])

    def test_python_from_import_in_workflow_is_not_a_base_image(self):
        """workflow 里 `from django.db import connections` 不是 `FROM django.db`。

        `.github/` 加进扫描面后实测到的假红:CI 用 `python -c '...'` 等 MySQL,脚本里有一行
        `from django.db import connections`,而 `FROM` 正则不区分大小写。假红比漏报更伤 ——
        人会去给门禁加白名单。
        """
        path = self._write(
            ".github/workflows/backend.yml",
            "      - run: |\n"
            "          python -c '\n"
            "          from django.db import connections\n"
            "          from django.db import transaction\n"
            "          '\n",
        )
        self.assertEqual(check_image_pins.references_in(path), [])

    def test_yaml_from_line_is_not_a_base_image(self):
        """YAML 里任何 `from xxx` 行都不按 Dockerfile 口径判。"""
        path = self._write("deploy/a.yml", "services:\n  x:\n    from: ubuntu:24.04\n")
        self.assertEqual(check_image_pins.references_in(path), [])

    def test_dockerfile_image_key_is_not_read(self):
        """反向也分流:Dockerfile 里只有 `FROM` 算引用,`image:` 那一行不算。

        这不是「现实里会写」的形态,而是分流本身的钉子:两个正则各归各的文件类型,
        判定不再依赖「这一行长什么样」。
        """
        path = self._write("imserver/Dockerfile", "image: ubuntu:24.04\n")
        self.assertEqual(check_image_pins.references_in(path), [])


class FindUnpinnedTests(unittest.TestCase):
    """整仓库口径:扫哪些文件、报不报、报得对不对。"""

    def setUp(self):
        """建一个临时仓库根。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        """清理临时目录。"""
        self.tmp.cleanup()

    def _write(self, relative: str, text: str) -> None:
        """写一个文件。

        参数说明:
            relative: 相对临时仓库根的路径。
            text: 文件内容。
        """
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_pinned_repo_is_clean(self):
        """全部钉住时没有违例。"""
        self._write("deploy/docker-compose.yml.tmpl", f"services:\n  r:\n    image: redis:7.4.12@{GOOD_DIGEST}\n")
        self._write("deploy/docker/Dockerfile", f"FROM python:3.11.18-slim@{GOOD_DIGEST}\n")
        self.assertEqual(check_image_pins.find_unpinned(self.root), [])

    def test_bare_tag_is_reported_with_location(self):
        """违例要带「文件:行号」,否则门禁日志没法定位。"""
        self._write("deploy/docker-compose.yml.tmpl", "services:\n  r:\n    image: redis:7-alpine\n")
        problems = check_image_pins.find_unpinned(self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("deploy/docker-compose.yml.tmpl:3", problems[0])
        self.assertIn("redis:7-alpine", problems[0])

    def test_yaml_template_suffix_is_scanned(self):
        """`docker-compose.yml.tmpl` 必须被扫到 —— 按文件后缀判会把它整个漏掉。"""
        self._write("deploy/docker-compose.yml.tmpl", "services:\n  r:\n    image: redis:7-alpine\n")
        problems = check_image_pins.find_unpinned(self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("deploy/docker-compose.yml.tmpl:3", problems[0])

    def test_workflow_bare_tag_is_reported(self):
        """`.github/workflows/` 也在扫描面内:CI 的 services 镜像裸 tag 必须报红。

        CI 里换的是「跑测试用的那一对数据库 / 缓存」,漂移同样不报错 —— 只是把
        `bash scripts/verify.sh contract` 与本机跑的容器悄悄换成了另一份内容。
        """
        self._write(".github/workflows/x.yml", "services:\n  db:\n    image: mysql:8.0\n")
        problems = check_image_pins.find_unpinned(self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn(".github/workflows/x.yml:3", problems[0])
        self.assertIn("mysql:8.0", problems[0])

    def test_pinned_workflow_is_clean(self):
        """workflow 里钉好的引用不报红(否则人只能给 CI 加白名单)。"""
        self._write(
            ".github/workflows/x.yml",
            f"services:\n  db:\n    image: mysql:8.0.46@{GOOD_DIGEST}\n"
            f"  cache:\n    image: redis:7.4.12-alpine@{GOOD_DIGEST}\n",
        )
        self.assertEqual(check_image_pins.find_unpinned(self.root), [])

    def test_workflow_uses_and_other_keys_are_not_images(self):
        """workflow 里只有 `image:` 算镜像引用:`uses:` / `runs-on:` 里的 `@` 不是 digest。"""
        self._write(
            ".github/workflows/x.yml",
            "jobs:\n"
            "  a:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1\n"
            "      - uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0\n"
            "        with:\n"
            "          python-version: '3.11'\n"
            "    env:\n"
            "      DB_IMAGE: mysql:8.0\n"
            "      # image: redis:7-alpine\n"
            "    # from: ubuntu:24.04\n",
        )
        self.assertEqual(check_image_pins.find_unpinned(self.root), [])

    def test_yaml_outside_scope_roots_is_ignored(self):
        """仓库根下的 YAML 也不在范围内。"""
        self._write("docker-compose.yml", "services:\n  r:\n    image: redis:7-alpine\n")
        self.assertEqual(check_image_pins.find_unpinned(self.root), [])


class CommandLineTests(unittest.TestCase):
    """命令行契约:退出码与 `--list` 不判红。"""

    def test_list_mode_never_fails(self):
        """`--list` 只打印,永远退出码 0(排查用)。"""
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(check_image_pins.main(["--list"]), 0)
        self.assertIn("OK", buffer.getvalue())

    def test_unknown_flag_exits_two(self):
        """未知参数交给 argparse 退出码 2 —— 拼错参数的调用不能被当成「通过」。"""
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as context:
            check_image_pins.main(["--nope"])
        self.assertEqual(context.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
