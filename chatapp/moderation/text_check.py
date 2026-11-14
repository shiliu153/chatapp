"""开发期最小违规词库。

设计要点:
    只做子串匹配,不是内容审核系统。上线前应替换为腾讯云文本审核 API ——
    调用方只认 ``find_blocked_word`` 这一个入口,替换时业务代码不需要改。

文件信息:
    文件名称          moderation/text_check.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

# 命中即拒的违规词;只做子串匹配,大小写与空白由 ``find_blocked_word`` 归一化
BLOCKED_WORDS = ("赌博", "色情", "代开发票", "刷单", "贷款", "毒品")


def find_blocked_word(text: str) -> str | None:
    """检查文本是否命中违规词库。

    参数说明:
        text: 待检查文本(昵称、简介等)。

    返回参数:
        命中的第一个违规词;未命中或文本为空时返回 ``None``。

    使用示例:
        ``find_blocked_word("喜欢音乐和旅行的设计师")``

    备注信息:
        先去掉所有空白字符再匹配,所以「代 开发票」同样命中;词库按
        ``BLOCKED_WORDS`` 顺序逐个比对,返回的是**词库里的原词**,不是原文片段。
        只返回第一个命中词,不做位置与次数统计。
    """
    if not text:
        return None
    normalized = "".join(text.lower().split())   # 去掉空格/换行,防 "代 开发票" 绕过
    for word in BLOCKED_WORDS:
        if word in normalized:
            return word
    return None
