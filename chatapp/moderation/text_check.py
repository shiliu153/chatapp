"""开发期最小违规词库。

设计要点:
    只做子串匹配,不是内容审核系统。上线前应替换为腾讯云文本审核 API ——
    调用方只认 ``find_blocked_word`` 这一个入口,替换时业务代码不需要改。
"""

BLOCKED_WORDS = ("赌博", "色情", "代开发票", "刷单", "贷款", "毒品")


def find_blocked_word(text: str) -> str | None:
    """检查文本是否命中违规词库。

    Args:
        text: 待检查文本(昵称、简介等)。

    Returns:
        命中的第一个违规词;未命中或文本为空时返回 ``None``。
    """
    if not text:
        return None
    normalized = "".join(text.lower().split())   # 去掉空格/换行,防 "代 开发票" 绕过
    for word in BLOCKED_WORDS:
        if word in normalized:
            return word
    return None
