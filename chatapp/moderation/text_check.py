"""开发期最小违规词库。

设计要点:
    只做子串匹配,不是内容审核系统。上线前应替换为腾讯云文本审核 API ——
    调用方只认 ``find_blocked_word`` 这一个入口,替换时业务代码不需要改。
"""

BLOCKED_WORDS = ("赌博", "色情", "代开发票", "刷单", "贷款", "毒品")


def find_blocked_word(text: str) -> str | None:
    """检查文本是否命中违规词库。

    参数说明:
        text: 待检查文本(昵称、简介等)。

    返回参数:
        命中的第一个违规词;未命中或文本为空时返回 ``None``。

    使用示例:
        ``if find_blocked_word(value): raise serializers.ValidationError(...)``(见
        ``users/serializers.py`` 的昵称/简介校验与 ``feed/serializers.py`` 的正文校验);
        ``self.assertEqual(find_blocked_word("专业代 开发票"), "代开发票")``(见
        ``moderation/tests.py`` 的 ``TextCheckTests``)

    备注信息:
        只做子串匹配,不是内容审核系统;匹配前先去掉空格与换行,防「代 开发票」这类绕过。
        ``BLOCKED_WORDS`` 是开发期最小词库,上线前应替换为文本审核 API —— 调用方只认本函数
        这一个入口,替换时业务代码不需要改。
    """
    if not text:
        return None
    normalized = "".join(text.lower().split())   # 去掉空格/换行,防 "代 开发票" 绕过
    for word in BLOCKED_WORDS:
        if word in normalized:
            return word
    return None
