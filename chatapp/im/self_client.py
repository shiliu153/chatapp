"""自建 IM 的管理端客户端:HMAC 内部 API。

设计要点:
    1. 对外函数**永不抛异常**,失败只记日志并返回 ``False``(与已删除的腾讯客户端保持同一契约);
    2. 标识符仍是 ``u<id>``,``system_notice`` 映射为 ``uid=0``;
    3. 不 import ``client.py``,避免循环依赖;文案常量在本文件本地定义。

文件信息:
    文件名称          im/self_client.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import hashlib
import hmac
import json
import logging
import time

import requests
from django.conf import settings

from config import metrics

logger = logging.getLogger(__name__)

SYSTEM_NOTICE_IDENTIFIER = "system_notice"
BAN_LIFTED_TEXT = "您的账号限制已解除,所有功能已恢复。请遵守社区规范。"
REPORT_HANDLED_TEXT = "您提交的举报已处理,感谢您对社区安全的支持。"


def _uid(identifier: str) -> int:
    """把 IM 账号转成用户 id。

    参数说明:
        identifier: ``u9`` 或 ``system_notice``。

    返回参数:
        用户 id;系统通知为 0。

    使用示例:
        ``_uid("u9")``

    备注信息:
        ``system_notice`` 直接映射 0;其余按去掉 ``u`` 前缀后转 ``int``,格式不合法会抛
        ``ValueError`` —— 这是本文件唯一可能向调用方抛异常的地方,调用方传的都是库内
        ``accounts.models.im_user_id`` 生成的值。
    """
    if identifier == SYSTEM_NOTICE_IDENTIFIER:
        return 0
    return int(identifier.removeprefix("u"))


def _post(path: str, payload: dict) -> bool:
    """调用一次内部 API。

    参数说明:
        path: 以 ``/internal/`` 开头的路径。
        payload: JSON 请求体。

    返回参数:
        2xx 返回 ``True``;网络/HTTP 错误返回 ``False``。

    使用示例:
        ``_post("/internal/kick", {"uid": 9, "block": False})``

    备注信息:
        签名串是 ``f"{timestamp}\nPOST\n{path}\n{body}"``,用 ``settings.IM_SELF_INTERNAL_SECRET``
        做 HMAC-SHA256 取十六进制;``body`` 先序列化再签名,签名覆盖的字节与实际发送的字节
        完全相同。超时 5 秒;任何异常都被吞掉,只记日志并打 ``metrics.im_call(path, False)``,
        不向调用方抛。
    """
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    timestamp = str(int(time.time()))
    signing = f"{timestamp}\nPOST\n{path}\n{body}".encode()
    signature = hmac.new(
        settings.IM_SELF_INTERNAL_SECRET.encode(), signing, hashlib.sha256
    ).hexdigest()
    try:
        response = requests.post(
            settings.IM_SELF_URL + path,
            data=body.encode(),
            headers={
                "Content-Type": "application/json",
                "X-IM-Timestamp": timestamp,
                "X-IM-Signature": signature,
            },
            timeout=5,
        )
        response.raise_for_status()
        metrics.im_call(path, True)
        return True
    except Exception:
        metrics.im_call(path, False)
        logger.exception("自建 IM 调用失败 path=%s", path)
        return False


def ensure_account(identifier: str, nickname: str = "") -> bool:
    """幂等建号。

    参数说明:
        identifier: IM 账号,如 ``u9``。
        nickname: 初始昵称;账号已存在时不起作用。

    返回参数:
        账号已存在或新建成功返回 ``True``;失败返回 ``False``。

    使用示例:
        ``ensure_account("u9", "小明")``

    备注信息:
        调 ``/internal/accounts/ensure``;已存在则不动 IM 侧资料,不覆盖昵称与头像。
        失败只记日志返回 ``False``,不抛异常。
    """
    return _post("/internal/accounts/ensure",
                 {"uid": _uid(identifier), "nickname": nickname})


def set_profile_nick(identifier: str, nickname: str) -> bool:
    """同步昵称。

    参数说明:
        identifier: IM 账号,如 ``u9``。
        nickname: 要写入的昵称。

    返回参数:
        成功返回 ``True``;失败返回 ``False``。

    使用示例:
        ``set_profile_nick("u9", "小明")``

    备注信息:
        与 ``set_profile_avatar`` 是同一个接口 ``/internal/profile``,只传要改的字段,不会把
        另一个字段冲掉;失败只记日志返回 ``False``。
    """
    return _post("/internal/profile", {"uid": _uid(identifier), "nickname": nickname})


def set_profile_avatar(identifier: str, avatar_url: str) -> bool:
    """同步头像。

    参数说明:
        identifier: IM 账号,如 ``u9``。
        avatar_url: 头像的绝对 URL。

    返回参数:
        成功返回 ``True``;失败返回 ``False``。

    使用示例:
        ``set_profile_avatar("u9", "https://cdn.test/media/avatar/a.jpg")``

    备注信息:
        与 ``set_profile_nick`` 共用 ``/internal/profile``,请求体里只带 ``avatar`` 字段;
        失败只记日志返回 ``False``。
    """
    return _post("/internal/profile", {"uid": _uid(identifier), "avatar": avatar_url})


def send_custom_elem(from_identifier: str, to_identifier: str, data: dict,
                     desc: str = "") -> bool:
    """发送自定义消息(灰条/系统通知)。

    参数说明:
        from_identifier: 发送方 IM 账号,系统通知传 ``system_notice``。
        to_identifier: 接收方 IM 账号。
        data: 自定义消息体;``type`` 决定客户端渲染类型,缺省 ``other``。
        desc: 会话列表预览文案。

    返回参数:
        成功返回 ``True``;失败返回 ``False``。

    使用示例:
        ``send_custom_elem("system_notice", "u10", {"type": "ban_lifted"}, BAN_LIFTED_TEXT)``

    备注信息:
        请求体是 ``{"from","to","kind":"custom","custom":{"type","desc","data"}}``,整个
        ``data`` 原样放进 ``custom.data``;``data`` 不是 dict 时 ``.get`` 会失败,调用方必须先
        组装成 dict。
    """
    return _post(
        "/internal/send",
        {
            "from": _uid(from_identifier),
            "to": _uid(to_identifier),
            "kind": "custom",
            "custom": {"type": data.get("type", "other"), "desc": desc, "data": data},
        },
    )


def send_text(from_identifier: str, to_identifier: str, text: str) -> bool:
    """发送文本消息(手测/联调用)。

    参数说明:
        from_identifier: 发送方 IM 账号。
        to_identifier: 接收方 IM 账号。
        text: 文本内容。

    返回参数:
        成功返回 ``True``;失败返回 ``False``。

    使用示例:
        ``send_text("u9", "u10", "hello")``

    备注信息:
        业务文本消息由 App 直接走 WebSocket 发出,本函数只给手测与联调使用,业务代码不要
        调它;失败只记日志返回 ``False``。
    """
    return _post(
        "/internal/send",
        {"from": _uid(from_identifier), "to": _uid(to_identifier),
         "kind": "text", "text": text},
    )


def black_list_add(owner_identifier: str, other_identifier: str) -> bool:
    """加入 IM 黑名单。

    参数说明:
        owner_identifier: 拉黑发起方 IM 账号。
        other_identifier: 被拉黑方 IM 账号。

    返回参数:
        成功返回 ``True``;失败返回 ``False``。

    使用示例:
        ``black_list_add("u9", "u10")``

    备注信息:
        调 ``/internal/blacklist``,``action=add``;与 ``black_list_delete`` 共用同一接口,
        失败只记日志返回 ``False``。
    """
    return _post("/internal/blacklist",
                 {"owner": _uid(owner_identifier), "peer": _uid(other_identifier),
                  "action": "add"})


def black_list_delete(owner_identifier: str, other_identifier: str) -> bool:
    """移出 IM 黑名单。

    参数说明:
        owner_identifier: 解除拉黑的操作方 IM 账号。
        other_identifier: 被解除拉黑方 IM 账号。

    返回参数:
        成功返回 ``True``;失败返回 ``False``。

    使用示例:
        ``black_list_delete("u9", "u10")``

    备注信息:
        调 ``/internal/blacklist``,``action=remove``;与 ``black_list_add`` 共用同一接口,
        失败只记日志返回 ``False``。
    """
    return _post("/internal/blacklist",
                 {"owner": _uid(owner_identifier), "peer": _uid(other_identifier),
                  "action": "remove"})


def kick_user(identifier: str, block: bool = False,
              client_type: str | None = None) -> bool:
    """踢下线;``block=True`` 同时写入封禁键。

    请求体里的 ``client_type`` 只在按端踢时出现:不带它 = **踢全部端**
    (封禁 / 注销的语义),带上就只踢该端(同类端顶号)。

    参数说明:
        identifier: 目标 IM 账号,如 ``u9``。
        block: 是否同时写入封禁键。
        client_type: ``app`` / ``web``;``None`` 表示踢全部端。

    返回参数:
        成功返回 ``True``;网络/HTTP 错误返回 ``False``。

    使用示例:
        ``kick_user("u9", block=True)`` 或 ``kick_user("u9", client_type="web")``

    备注信息:
        ``client_type`` 只在非 ``None`` 时进请求体,不带它就是踢全部端(封禁 / 注销语义);
        失败只记日志返回 ``False``。
    """
    body = {"uid": _uid(identifier), "block": block}
    if client_type is not None:
        body["client_type"] = client_type
    return _post("/internal/kick", body)


def set_session_version(identifier: str, version: int,
                        client_type: str = "app") -> bool:
    """把账号在某一端上的会话版本同步给自建 IM。

    imserver 在 WS 鉴权时比对 token 里的 ``sv``;不一致即拒绝旧 token(H3)。

    参数说明:
        identifier: IM 账号,如 ``u9``。
        version: 该端当前的会话版本。
        client_type: ``app`` 或 ``web``;imserver 按 ``(uid, ct)`` 落库。

    返回参数:
        同步成功返回 ``True``;网络/HTTP 错误返回 ``False``。

    使用示例:
        ``set_session_version("u9", 3, client_type="app")``

    备注信息:
        ``version`` 强制转 ``int`` 再发;失败只记日志返回 ``False``,调用方(``im/tasks.py``)
        按 fail-closed 处理。
    """
    return _post("/internal/session_version",
                 {"uid": _uid(identifier), "version": int(version),
                  "client_type": client_type})


def pair_add(user_a_identifier: str, user_b_identifier: str) -> bool:
    """建立聊天权限(配对成功)。

    参数说明:
        user_a_identifier: 一方 IM 账号。
        user_b_identifier: 另一方 IM 账号。

    返回参数:
        同步成功返回 ``True``;失败返回 ``False``。

    使用示例:
        ``pair_add("u9", "u10")``

    备注信息:
        调 ``/internal/pair``,``action=add``;失败只记日志返回 ``False``,不抛异常。
    """
    return _post("/internal/pair", {"a": _uid(user_a_identifier),
                                    "b": _uid(user_b_identifier), "action": "add"})


def pair_remove(user_a_identifier: str, user_b_identifier: str) -> bool:
    """移除聊天权限(解除配对/拉黑)。

    参数说明:
        user_a_identifier: 一方 IM 账号。
        user_b_identifier: 另一方 IM 账号。

    返回参数:
        同步成功返回 ``True``;失败返回 ``False``。

    使用示例:
        ``pair_remove("u9", "u10")``

    备注信息:
        调 ``/internal/pair``,``action=remove``;失败只记日志返回 ``False``,不抛异常。
    """
    return _post("/internal/pair", {"a": _uid(user_a_identifier),
                                    "b": _uid(user_b_identifier), "action": "remove"})


def unblock_user(identifier: str) -> bool:
    """清除封禁键。

    参数说明:
        identifier: IM 账号,如 ``u9``。

    返回参数:
        成功返回 ``True``;失败返回 ``False``。

    使用示例:
        ``unblock_user("u9")``

    备注信息:
        调 ``/internal/unblock``,只清封禁键、不发任何通知;带通知的解封走
        ``send_ban_lifted``;失败只记日志返回 ``False``。
    """
    return _post("/internal/unblock", {"uid": _uid(identifier)})


def delete_account(identifier: str) -> bool:
    """删除该账号的全部 IM 数据。

    参数说明:
        identifier: 待删除的 IM 账号,如 ``u12``。

    返回参数:
        成功返回 ``True``;失败返回 ``False``。

    使用示例:
        ``delete_account("u12")``

    备注信息:
        调 ``/internal/delete_account``,删除后不可恢复;调用方须传注销前取好的
        ``im_user_id``(用户行删除后就取不到了)。失败只记日志返回 ``False``。
    """
    return _post("/internal/delete_account", {"uid": _uid(identifier)})


def send_ban_lifted(to_identifier: str) -> bool:
    """解封通知:先发灰条,再清封禁键。

    参数说明:
        to_identifier: 被解封用户的 IM 账号。

    返回参数:
        两者都成功才返回 ``True``;任一失败返回 ``False``。

    使用示例:
        ``send_ban_lifted("u9")``

    备注信息:
        执行顺序是「先发灰条,再清封禁键」,返回式是 ``unblock_user(...) and sent``;两步是
        独立请求,不会回滚:灰条失败但清键成功时返回 ``False``(人已被解封,通知可能没送到),
        由 ``im/tasks.py`` 的重试策略再补一次通知。
    """
    sent = send_custom_elem(SYSTEM_NOTICE_IDENTIFIER, to_identifier,
                            {"type": "ban_lifted"}, BAN_LIFTED_TEXT)
    return unblock_user(to_identifier) and sent
