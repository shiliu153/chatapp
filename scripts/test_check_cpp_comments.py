"""``scripts/check_cpp_comments.py`` 的自测(纯离线,临时目录造样本)。

进 CI 的 `contract` 轨。两边都要钉住,否则门禁要么把人烦死、要么形同虚设:

- **正例**:合规文件(1 个头文件声明 + 1 个 ``.cpp`` 定义 + 1 个类内 inline + 1 个 ``TEST``)
  必须退出 ``0`` 且**一个字都不打印**;
- **反例**:缺块 / 缺字段 / 分隔线宽度差一个 ``-`` / ``文件名称`` 写错 / 块与签名之间夹空行 /
  块落进函数体,每类各命中一次,**错误信息必须带 ``文件:行``**;
- **豁免反例**:lambda、``= delete``、``struct`` 字段、``#define``、函数体内局部对象 ——
  这些多报一次都是误报(误报比漏报更贵,cpp.md §4);
- **fail-closed**:缺 wheel / ``--root`` 指错 / 解析出 ``ERROR`` 节点时退出 ``2``,
  不许把「跑不了」伪装成「全绿」。

样本一律现造,不读真实 ``imserver/``:门禁的正确性不该依赖仓库当时的注释状态。
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import check_cpp_comments

#: 分隔线:``//`` + 115 个 ``-``(cpp.md §3.1 的规范形态)。
SEPARATOR = "//" + "-" * 115
#: 写错一格的宽度(反例用):少一个 ``-``。
SHORT_SEPARATOR = "//" + "-" * 114


def header(relative_name: str) -> str:
    """造一份合规的文件头(22 行块的两个特例除外,见 cpp.md §2.1)。

    Args:
        relative_name: 该文件相对 ``imserver/`` 的路径(写进 ``文件名称`` 字段)。

    Returns:
        文件头的多行文本(以换行结尾)。
    """
    return (
        "/" + "*" * 117 + "\n"  # 收尾行是 "*" * 116 + "/"(见函数末尾)
        "* chat_app 自建 IM 服务端（imserver）是本项目唯一的 IM 后端，C++20 实现，"
        "对外提供 WebSocket :9100 与 HTTP :9101\n"
        "* Copyright (c) 2026 shiliu153\n"
        "*\n"
        "* 本文件是 chat_app 自建 IM 服务端的一部分\n"
        "*\n"
        "* 额外注明：\n"
        "* 本文件使用 MIT 开源许可证协议 许可申明英文版见仓库根目录 LICENSE 文件\n"
        "* 欢迎各位使用并传播本程序 但修改内容时必须保留作者的版权声明（即本声明）\n"
        "*\n"
        f"* 文件名称          {relative_name}\n"
        "* 项目名称          chat_app / imserver\n"
        "* 公司名称          个人项目（shiliu153）\n"
        "* 版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明\n"
        "* 开发环境          CMake 3.22 + g++ (C++20) Linux x86_64\n"
        "* 适用平台          Linux x86_64 服务端\n"
        "* 仓库地址          https://github.com/shiliu153/chatapp\n"
        "*\n"
        "* 修改记录\n"
        "* 日期              作者               备注\n"
        "* 2026-11-14        shiliu153          补齐文件头与函数注释\n"
        + "*" * 116
        + "/\n"
    )


def block(summary: str = "做一件可验证的事", fields: tuple[str, ...] | None = None) -> str:
    """造一个合规的 5 字段注释块(cpp.md §3.3)。

    Args:
        summary: ``函数简介`` 的值。
        fields: 要写的字段子集(反例用);``None`` 表示 5 个字段全写。

    Returns:
        注释块的多行文本(以换行结尾)。
    """
    wanted = fields if fields is not None else check_cpp_comments.FIELDS
    values = {
        "函数简介": summary,
        "参数说明": "无",
        "返回参数": "void             无返回值",
        "使用示例": "demo();",
        "备注信息": "自测样本",
    }
    lines = [SEPARATOR]
    lines += [f"// {name}     {values[name]}" for name in wanted]
    lines += [SEPARATOR]
    return "\n".join(lines) + "\n"


class SampleCase(unittest.TestCase):
    """公共脚手架:临时目录里搭一个假的 ``imserver/``,按需写文件后跑脚本。"""

    def setUp(self):
        """建临时目录骨架 ``<tmp>/imserver/{src,tests}``。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.imserver = self.root / "imserver"
        (self.imserver / "src").mkdir(parents=True)
        (self.imserver / "tests").mkdir(parents=True)

    def tearDown(self):
        """删除临时目录。"""
        self.tmp.cleanup()

    def write(self, relative: str, text: str) -> Path:
        """把内容写进 ``<tmp>/imserver/<relative>``。

        Args:
            relative: 相对 ``imserver/`` 的路径(如 ``src/demo.h``)。
            text: 文件内容。

        Returns:
            写出的路径。
        """
        path = self.imserver / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_check(self, *extra: str) -> tuple[int, str, str]:
        """跑 ``main`` 并收集退出码与两路输出(``--root`` 指向临时 ``imserver/``)。

        Args:
            *extra: 追加的命令行参数。

        Returns:
            ``(退出码, stdout, stderr)``。
        """
        out, err = io.StringIO(), io.StringIO()
        argv = ["--check", "--root", str(self.imserver), *extra]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = check_cpp_comments.main(argv)
        return code, out.getvalue(), err.getvalue()

    def find_line(self, text: str, needle: str) -> int:
        """取 ``text`` 里第一处含 ``needle`` 的行号(1 起),造样本时用它对齐行号断言。

        Args:
            text: 文件全文。
            needle: 要找的子串。

        Returns:
            1 起的行号。

        Raises:
            AssertionError: 找不到。
        """
        for index, line in enumerate(text.splitlines(), start=1):
            if needle in line:
                return index
        self.fail(f"样本里没有 {needle!r}")

    def sample_positive(self) -> dict[str, str]:
        """造一套合规样本(声明 / 定义 / 类内 inline / TEST / 常量 / struct)。

        Returns:
            相对路径 → 文件内容。
        """
        header_demo = header("src/demo.h")
        source = (
            header_demo
            + "#pragma once\n"
            + "class Demo {\n"
            + " public:\n"
            + block("构造演示对象")
            + "  Demo() = default;\n"
            + block("取自增后的值")
            + "  int value() const { return value_; }\n"
            + "  Demo(const Demo&) = delete;\n"
            + "  Demo& operator=(const Demo&) = delete;\n"
            + " private:\n"
            + "  int value_ = 0;\n"
            + "};\n"
            + block("累加一个数")
            + "int add(int left, int right);\n"
        )
        source_cpp = (
            header("src/demo.cpp")
            + '#include "demo.h"\n'
            + block("累加一个数")
            + "int add(int left, int right) { return left + right; }\n"
        )
        test_cpp = (
            header("tests/demo_test.cpp")
            + '#include <string>\n'
            + "namespace {\n"
            + "std::string helper(const std::string& value) { return value; }\n"
            + "}  // namespace\n"
            + block("用例 验证加法")
            + "TEST(DemoTest, Adds) { EXPECT_EQ(add(1, 2), 3); }\n"
        )
        return {"src/demo.h": source, "src/demo.cpp": source_cpp, "tests/demo_test.cpp": test_cpp}


class CompliantSampleTests(SampleCase):
    """正例:合规样本必须退出 0 且零输出。"""

    def test_compliant_sample_is_green_and_silent(self):
        """声明 + 定义 + 类内 inline + TEST 都带块 → 退出 0,stdout 与 stderr 都没有内容。"""
        for relative, text in self.sample_positive().items():
            self.write(relative, text)
        code, out, err = self.run_check()
        self.assertEqual(code, 0, out + err)
        self.assertEqual(out, "")
        self.assertEqual(err, "")

    def test_two_space_indented_block_is_legal(self):
        """类成员块整体缩进 2 空格(``src/util/media_sign.h`` 的写法)合法,不按 117 硬卡。"""
        body = (
            header("src/indented.h")
            + "#pragma once\n"
            + "class Indented {\n"
            + " public:\n"
            + "".join("  " + line + "\n" for line in block("判断是否可用").splitlines())
            + "  bool enabled() const { return true; }\n"
            + "};\n"
        )
        self.write("src/indented.h", body)
        code, out, err = self.run_check()
        self.assertEqual(code, 0, out + err)
        self.assertEqual(out, "")

    def test_template_function_block_goes_above_template_line(self):
        """模板函数的块写在 ``template <…>`` 上方(不是内层声明上方),不能被误报成缺块。"""
        body = (
            header("src/templated.h")
            + "#pragma once\n"
            + block("取较小值")
            + "template <typename T>\n"
            + "const T& smaller(const T& left, const T& right);\n"
        )
        self.write("src/templated.h", body)
        code, out, err = self.run_check()
        self.assertEqual(code, 0, out + err)
        self.assertEqual(out, "")

    def test_verbose_prints_baseline_counts(self):
        """``--verbose`` 才打基线计数(默认零输出,CI 日志才干净)。"""
        for relative, text in self.sample_positive().items():
            self.write(relative, text)
        code, _, err = self.run_check("--verbose")
        self.assertEqual(code, 0)
        self.assertIn("合规", err)
        self.assertIn("3 个文件", err)


class ViolationTests(SampleCase):
    """反例:每类各命中一次,且信息里带 ``文件:行``。"""

    def test_missing_block(self):
        """缺块:``.cpp`` 里的函数定义上方没有块。"""
        body = (
            header("src/missing.cpp")
            + "int naked(int value) { return value; }\n"
        )
        self.write("src/missing.cpp", body)
        code, out, _ = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn(f"imserver/src/missing.cpp:{self.find_line(body, 'int naked')}:", out)
        self.assertIn("缺函数注释块", out)

    def test_missing_field(self):
        """缺某个字段:块里没有 ``使用示例``。"""
        body = (
            header("src/field.h")
            + block("缺一个字段", ("函数简介", "参数说明", "返回参数", "备注信息"))
            + "void partial();\n"
        )
        self.write("src/field.h", body)
        code, out, _ = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("注释块缺字段:使用示例", out)
        self.assertIn(f"imserver/src/field.h:{self.find_line(body, 'void partial')}:", out)

    def test_separator_width_off_by_one(self):
        """分隔线宽度不对(少一个 ``-``):判据是 ``//`` + 115 个 ``-``,少一格也算缺块。"""
        body = (
            header("src/width.h")
            + SEPARATOR
            + "\n// 函数简介     宽度差一格\n// 参数说明     无\n// 返回参数     void             无返回值\n"
            + "// 使用示例     narrow();\n// 备注信息     无\n"
            + SHORT_SEPARATOR
            + "\nvoid narrow();\n"
        )
        self.write("src/width.h", body)
        code, out, _ = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("缺函数注释块", out)
        self.assertIn(f"imserver/src/width.h:{self.find_line(body, 'void narrow')}:", out)

    def test_file_name_field_mismatch(self):
        """``文件名称`` 写错:值必须是该文件相对 ``imserver/`` 的路径。"""
        body = header("src/wrong_name.h") + block("随便") + "void here();\n"
        self.write("src/actual.h", body)
        code, out, _ = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("文件名称", out)
        self.assertIn("src/actual.h", out)
        self.assertIn(f"imserver/src/actual.h:{self.find_line(body, '文件名称')}:", out)

    def test_blank_line_between_block_and_signature(self):
        """块与签名之间夹了空行:块必须紧贴签名上方。"""
        body = (
            header("src/blank.h")
            + block("夹了空行")
            + "\nvoid separated();\n"
        )
        self.write("src/blank.h", body)
        code, out, _ = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("缺函数注释块", out)
        self.assertIn(f"imserver/src/blank.h:{self.find_line(body, 'void separated')}:", out)

    def test_block_inside_function_body(self):
        """块落进函数体:分隔线缩进 ≥4 空格判红(现库全部注释块都在函数体外)。"""
        body = (
            header("src/inside.cpp")
            + block("外层的函数")
            + "void outer() {\n"
            + "".join("    " + line + "\n" for line in block("函数体里的块").splitlines())
            + "}\n"
        )
        self.write("src/inside.cpp", body)
        code, out, _ = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("落进了函数体", out)
        self.assertIn(f"imserver/src/inside.cpp:{self.find_line(body, '函数体里的块') - 1}:", out)
        # 提示语里不许再写死基线个数(「现库 N 个块」那种字面量):每加一个 C++ 函数就漂
        # 一次,而 facts.py 的哨兵只覆盖 docs/**,漂了没人会发现。判据不钉具体值 —— 钉值
        # 本身就是同一种病 —— 只要求「现库」后面不跟数字。
        self.assertNotRegex(out, r"现库\s*\d")

    def test_missing_header(self):
        """缺文件头:文件直接从 ``#include`` 开始。"""
        self.write("src/noheader.h", "#pragma once\nvoid bare();\n")
        code, out, _ = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("imserver/src/noheader.h:1:", out)
        self.assertIn("缺文件头", out)

    def test_summary_line_counts_findings(self):
        """末尾有一行汇总计数(条数等于逐条报出的行数)。"""
        self.write("src/a.cpp", header("src/a.cpp") + "int a() { return 1; }\n")
        self.write("src/b.cpp", header("src/b.cpp") + "int b() { return 2; }\n")
        code, out, _ = self.run_check()
        self.assertEqual(code, 1)
        details = [line for line in out.splitlines() if line.startswith("imserver/")]
        summary = [line for line in out.splitlines() if line.startswith("C++ 注释门禁:")]
        self.assertEqual(len(summary), 1)
        self.assertIn(f"发现 {len(details)} 处问题", summary[0])


class ExemptionTests(SampleCase):
    """豁免反例:lambda / ``= delete`` / ``struct`` / 宏 / 函数体内局部对象 —— 零误报。"""

    def test_exempt_constructs_are_silent(self):
        """这五类都不该要块:多报一次就是误报,而误报会让规范被关掉(cpp.md §4)。"""
        body = (
            header("src/exempt.cpp")
            + "#define DEMO_MAX 20\n"
            + "namespace {\n"
            + block("把回调交给事件循环")
            + "void wire(int& counter) {\n"
            + "  auto handler = [&counter](int delta) { counter += delta; };\n"
            + "  std::vector<std::thread> threads;\n"
            + "  threads.emplace_back([&counter] { counter = 0; });\n"
            + "  handler(1);\n"
            + "}\n"
            + "}  // namespace\n"
            + "struct Point {\n"
            + "  int x = 0;\n"
            + "  int y = 0;\n"
            + "};\n"
            + "class Counter {\n"
            + " public:\n"
            + block("构造计数器(= default 按定义处处理:要有块)")
            + "  Counter() = default;\n"
            + "  Counter(const Counter&) = delete;\n"
            + "  Counter& operator=(const Counter&) = delete;\n"
            + "};\n"
        )
        self.write("src/exempt.cpp", body)
        code, out, err = self.run_check()
        self.assertEqual(code, 0, out + err)
        self.assertEqual(out, "")

    def test_struct_member_function_still_needs_a_block(self):
        """``struct`` 的**字段**不加块,但它的成员函数加 —— 豁免只覆盖字段。"""
        body = (
            header("src/point.h")
            + "struct Point {\n"
            + "  int x = 0;\n"
            + "  int sum() const { return x; }\n"
            + "};\n"
        )
        self.write("src/point.h", body)
        code, out, _ = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("缺函数注释块", out)

    def test_tests_helper_is_not_forced(self):
        """``tests/`` 的 helper 函数按现库惯例不强制(``--verbose`` 会把它们列出来)。"""
        body = (
            header("tests/helper_test.cpp")
            + "namespace { int helper(int value) { return value; } }\n"
            + block("用例 验证 helper")
            + "TEST(HelperTest, Works) { EXPECT_EQ(helper(1), 1); }\n"
        )
        self.write("tests/helper_test.cpp", body)
        code, out, err = self.run_check()
        self.assertEqual(code, 0, out + err)
        self.assertEqual(out, "")
        _, _, verbose = self.run_check("--verbose")
        self.assertIn("豁免", verbose)


class ToolingTests(SampleCase):
    """fail-closed:工具自身出错一律退出 2,不许冒充绿。"""

    def test_missing_dependency_exits_two(self):
        """缺 wheel → 退出 2,并打印安装命令(CI 与本地的安装口径是同一份 requirements)。"""
        self.write("src/demo.cpp", header("src/demo.cpp") + "int demo() { return 0; }\n")
        with mock.patch.object(
            check_cpp_comments,
            "load_parser",
            side_effect=check_cpp_comments.ToolingError(
                f"缺依赖 tree_sitter(本门禁需要它)。安装:{check_cpp_comments.INSTALL_COMMAND}"
            ),
        ):
            code, out, err = self.run_check()
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("scripts/requirements-gates.txt", err)

    def test_root_must_be_imserver_dir(self):
        """``--root`` 指到没有 ``src/`` ``tests/`` 的目录 → 退出 2(判不了就说判不了)。"""
        empty = self.root / "empty"
        empty.mkdir()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = check_cpp_comments.main(["--check", "--root", str(empty)])
        self.assertEqual(code, 2)
        self.assertIn("没有 src/ 或 tests/", err.getvalue())

    def test_unparsable_file_exits_two(self):
        """解析出 ``ERROR`` 节点 → 退出 2(判不准的文件不许被静默放过)。"""
        self.write("src/broken.cpp", header("src/broken.cpp") + "int broken( { return 0; }\n")
        code, _, err = self.run_check()
        self.assertEqual(code, 2)
        self.assertIn("解析失败", err)

    def test_repository_itself_is_green(self):
        """真实 ``imserver/`` 必须零输出零退出 —— 门禁的第一口径是零误报。

        文件数与块数不写在这里:每次加 C++ 代码都会变,要现算就 ``--verbose``。
        """
        if not (check_cpp_comments.DEFAULT_ROOT / "src").is_dir():
            self.skipTest("没有真实仓库内容(只跑了 scripts/ 的副本)")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = check_cpp_comments.main(["--check"])
        self.assertEqual(code, 0, out.getvalue() + err.getvalue())
        self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
