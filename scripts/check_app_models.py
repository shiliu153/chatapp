"""校验 App 侧手写模型读取的字段名都存在于 OpenAPI 契约里(D-5 第 3 步)。

设计要点:
    App 的模型是手写的 ``fromJson``,字段名以 ``json['snake_case']`` 的形式出现;
    Dart 端没有 YAML 解析器,也不值得为一次检查引入代码生成,所以这里做**静态扫描**:
    把 ``app/lib/features/**/models.dart`` 里所有 ``json['...']`` 的键抓出来,断言它们都能在
    ``docs/api/openapi.yml`` 里找到(组件属性或参数名)。

    为什么值得单独检查:App 的 ``fromJson`` 是容错写法(``json['x'] ?? ''``),后端改名后
    **不会崩、也不会报错**,只会静默变成空值 —— 这是最难发现的一类事故。

    Dart 端刻意**不生成模型代码**(手写模型带 ``copyWith``/枚举映射等业务方法,
    替换成本远高于收益),所以用这份契约检查替代生成器。

用法:
    python scripts/check_app_models.py           # 退出码 0 = 全部字段都在契约里
    python scripts/check_app_models.py --verbose # 额外打印扫描到的文件与字段数

注意事项:
    只扫 ``lib/features/**/models.dart``(对接口的模型);``lib/im/`` 解析的是 IM 帧,
    不属于 ``/api/v1`` 契约,不在检查范围。

文件信息:
    文件名称          scripts/check_app_models.py
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
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
OPENAPI = REPO_ROOT / "docs" / "api" / "openapi.yml"
APP_ROOT = REPO_ROOT / "app"
MODEL_GLOB = "lib/features/**/models.dart"

# json['field'] / json["field"]
JSON_KEY_RE = re.compile(r"""json\[\s*['"]([^'"]+)['"]\s*\]""")


def load_contract_fields(path: Path = OPENAPI) -> set[str]:
    """从 OpenAPI 文档里收集全部字段名(组件属性 + 参数名,递归)。

    参数说明:
        path: ``docs/api/openapi.yml`` 路径。

    返回参数:
        字段名集合;文档缺失或解析失败时抛 ``SystemExit``。

    使用示例:
        ``load_contract_fields(path)``

    备注信息:
        失败时抛 ``SystemExit``,由调用方处理。
    """
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        print(f"[App 契约] 读不到 {path}:{error}", file=sys.stderr)
        raise SystemExit(1) from error
    names: set[str] = set()
    _collect(document, names)
    return names


def _collect(node, names: set[str]) -> None:
    """递归收集 ``properties`` 的键与 ``parameters[].name``。

    参数说明:
        node: OpenAPI 文档里的任意片段(字典/列表/标量)。
        names: 收集结果(原地写入)。

    返回参数:
        无返回值。

    使用示例:
        ``_collect(node, names)``

    备注信息:
        无特殊约束。
    """
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            names.update(properties)
        for value in node.values():
            _collect(value, names)
    elif isinstance(node, list):
        for item in node:
            _collect(item, names)


def model_files() -> list[Path]:
    """列出 App 侧需要检查的模型文件。

    参数说明:
        无。

    返回参数:
        排序后的 ``models.dart`` 路径列表。

    使用示例:
        ``model_files()``

    备注信息:
        无特殊约束。
    """
    return sorted(APP_ROOT.glob(MODEL_GLOB))


def read_json_keys(path: Path) -> set[str]:
    """取出一个 Dart 文件里所有 ``json['...']`` 的键。

    参数说明:
        path: Dart 源文件路径。

    返回参数:
        字段名集合。

    使用示例:
        ``read_json_keys(path)``

    备注信息:
        无特殊约束。
    """
    return set(JSON_KEY_RE.findall(path.read_text(encoding="utf-8")))


def find_problems(contract: set[str] | None = None) -> list[str]:
    """列出 App 读取了、但契约里没有的字段。

    参数说明:
        contract: 契约字段集合;``None`` 表示从 ``docs/api/openapi.yml`` 现读。

    返回参数:
        问题描述列表;空列表表示全部对得上。

    使用示例:
        ``find_problems(contract)``

    备注信息:
        无特殊约束。
    """
    contract = load_contract_fields() if contract is None else contract
    problems = []
    for path in model_files():
        unknown = sorted(read_json_keys(path) - contract)
        if unknown:
            relative = path.relative_to(REPO_ROOT).as_posix()
            problems.append(f"{relative} 读取了契约里没有的字段:{', '.join(unknown)}")
    return problems


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    参数说明:
        argv: 命令行参数;``None`` 表示取 ``sys.argv[1:]``。

    返回参数:
        退出码:0 一致,1 存在契约里没有的字段。

    使用示例:
        ``python scripts/check_app_models.py``

    备注信息:
        无特殊约束。
    """
    parser = argparse.ArgumentParser(description="App 手写模型字段 ↔ OpenAPI 契约一致性检查")
    parser.add_argument("--verbose", action="store_true", help="打印扫描范围与统计")
    args = parser.parse_args(argv)

    contract = load_contract_fields()
    files = model_files()
    if not files:
        print(f"[App 契约] 在 {APP_ROOT} 下没找到 {MODEL_GLOB}", file=sys.stderr)
        return 1
    if args.verbose:
        print(f"[App 契约] 契约字段 {len(contract)} 个,扫描 {len(files)} 个模型文件")

    problems = find_problems(contract)
    if problems:
        for problem in problems:
            print(f"[App 契约] {problem}", file=sys.stderr)
        print("[App 契约] 后端改了字段名?先改 docs/api/ 与视图注解,再同步 App 模型", file=sys.stderr)
        return 1
    print(f"[App 契约] {len(files)} 个模型文件读取的字段全部存在于 OpenAPI 契约中")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
