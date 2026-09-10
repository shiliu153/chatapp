"""开发期最小违规词库。上线前替换为腾讯云文本审核 API(M3),调用点保持不变。"""

BLOCKED_WORDS = ("赌博", "色情", "代开发票", "刷单", "贷款", "毒品")


def find_blocked_word(text: str) -> str | None:
    if not text:
        return None
    normalized = "".join(text.lower().split())   # 去掉空格/换行,防 "代 开发票" 绕过
    for word in BLOCKED_WORDS:
        if word in normalized:
            return word
    return None
