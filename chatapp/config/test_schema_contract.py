"""OpenAPI 契约与 ``docs/api`` 字段表的双向门禁(D-5 第 2 步)。

覆盖场景:
    - 47 个操作的「请求参数 / 响应参数」与 ``@extend_schema`` 生成结果逐字段对齐;
    - 比对逻辑自测:故意改掉一个字段名必须报错,防止门禁本身静默失效;
    - 文档解析规则:``tags[]`` / ``photos[]`` 这类子结构表不算顶层字段,
      ``同 [X.Y ...]`` 引用能继承另一小节的字段表;
    - 豁免表只允许 DELETE 请求体(OpenAPI 3.0 表达不了),防止它变成万能白名单。

文件信息:
    文件名称          config/test_schema_contract.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import copy

from django.test import SimpleTestCase

from config.api_schema_contract import (SCHEMA_INEXPRESSIBLE, docs_fields, find_problems,
                                        generate_schema)


class SchemaContractTests(SimpleTestCase):
    """门禁本体:文档字段 ↔ schema 字段双向比对。"""

    schema: dict = {}

    @classmethod
    def setUpClass(cls):
        """生成一次 schema,供本类各用例复用(生成有固定开销)。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``SchemaContractTests.setUpClass()``(由 ``unittest`` 在类内用例执行前自动调用)

        备注信息:
            结果挂在类属性 ``cls.schema`` 上;自测用例都先 ``deepcopy`` 再改字段,
            因此共用同一份 schema 不会互相污染。
        """
        super().setUpClass()
        cls.schema = generate_schema()

    def test_docs_and_schema_agree(self):
        """真实文档字段表与 schema 字段双向一致(漏写/多写即红)。

        参数说明:
            无。
        """
        problems = find_problems(schema=self.schema)
        self.assertEqual(problems, [], "字段级契约不一致:\n" + "\n".join(problems))

    def test_renamed_field_is_reported(self):
        """把 ``target_user_id`` 改名,门禁必须报出「文档里有、OpenAPI 里没有」。"""
        mutated = copy.deepcopy(self.schema)
        swipe = next(
            schema for schema in mutated["components"]["schemas"].values()
            if {"target_user_id", "action"} <= set(schema.get("properties", {}))
        )
        swipe["properties"]["target_id"] = swipe["properties"].pop("target_user_id")

        problems = find_problems(schema=mutated)
        self.assertTrue(any("target_user_id" in problem for problem in problems), problems)

    def test_added_field_is_reported(self):
        """代码多出一个文档没写的字段,门禁也必须报出来(反方向)。"""
        mutated = copy.deepcopy(self.schema)
        swipe = next(
            schema for schema in mutated["components"]["schemas"].values()
            if {"target_user_id", "action"} <= set(schema.get("properties", {}))
        )
        swipe["properties"]["unexpected_field"] = {"type": "string"}

        problems = find_problems(schema=mutated)
        self.assertTrue(any("unexpected_field" in problem for problem in problems), problems)

    def test_inexpressible_exemption_is_delete_only(self):
        """豁免表只能用于 DELETE 请求体,防止它变成绕开门禁的万能白名单。"""
        for method, path in SCHEMA_INEXPRESSIBLE:
            self.assertEqual(method, "DELETE", f"{method} {path} 不能进豁免表")


class DocsFieldParsingTests(SimpleTestCase):
    """文档解析规则自测(纯文本,不依赖 schema 生成)。"""

    def test_nested_tables_are_not_top_level_fields(self):
        """``users.md §2.1`` 的 ``tags[]`` / ``photos[]`` 子表不算顶层字段。"""
        fields = docs_fields()
        response = fields[("GET", "/api/v1/users/me")]["response"]
        self.assertIn("tags", response)
        self.assertIn("photos", response)
        self.assertNotIn("icon", response)   # tags[] 子表里的字段
        self.assertNotIn("order", response)  # photos[] 子表里的字段

    def test_reference_line_inherits_response_fields(self):
        """``同 [5.1 动态流]`` 引用让小节的响应字段与 5.1 完全一致。"""
        fields = docs_fields()
        self.assertEqual(fields[("GET", "/api/v1/posts/mine")]["response"],
                         fields[("GET", "/api/v1/posts")]["response"])

    def test_pagination_envelope_is_not_compared(self):
        """分页信封(count / next_cursor / ...)不写进单接口表,也不该出现在文档字段里。"""
        fields = docs_fields()
        response = fields[("GET", "/api/v1/matches")]["response"]
        self.assertNotIn("next_cursor", response)
        self.assertNotIn("has_more", response)
