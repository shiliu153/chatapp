"""查询参数的统一校验。

设计要点:
    1. 非法参数一律变成 400(统一错误信封),不允许把 ``ValueError`` 漏成 500;
    2. 数值参数越界时**收敛到边界**而不是报错 —— 老客户端可能传 ``limit=999``,
       收敛比直接拒绝更兼容;
    3. 只处理「可选过滤条件」的场景(如审核台的 ``user``):非法值返回 ``None``,
       由调用方决定「忽略该过滤」还是「报错」。

文件信息:
    文件名称          config/params.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from rest_framework.exceptions import ValidationError


def _raw(request, name: str):
    """从 DRF 请求或 Django 请求里取原始查询参数。

    备注信息:
        优先用 ``query_params``,没有则退回 ``GET``;不做类型转换,
        缺失返回 ``None``,与空串区分开由调用方处理。
    """
    source = getattr(request, "query_params", None)
    if source is None:
        source = request.GET
    return source.get(name)


def int_param(request, name: str, *, default: int, minimum: int | None = None,
              maximum: int | None = None) -> int:
    """读取一个整数查询参数,越界收敛到边界。

    参数说明:
        request: DRF/Django 请求对象。
        name: 参数名。
        default: 参数缺省或为空串时的返回值。
        minimum: 允许的最小值;``None`` 表示不限制。
        maximum: 允许的最大值;``None`` 表示不限制。

    返回参数:
        校验后的整数。

    使用示例:
        ``int_param(request, "limit", default=20, minimum=1, maximum=100)``

    备注信息:
        参数存在但不是整数时抛 ``ValidationError``(DRF 会转成 400);
        越界不报错而是收敛到边界,兼容老客户端传 ``limit=999`` 这类写法。
    """
    raw = _raw(request, name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as error:
        raise ValidationError({name: "必须是整数"}) from error
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def optional_id(value) -> int | None:
    """把可选的主键过滤参数转成正整数。

    参数说明:
        value: 原始参数值(可能为 ``None`` / 空串 / 非数字)。

    返回参数:
        正整数;非法值返回 ``None``,调用方据此忽略该过滤条件。

    使用示例:
        ``optional_id(request.query_params.get("user"))``

    备注信息:
        非数字与 ``<= 0`` 的取值一律返回 ``None`` 而不抛异常,和
        :func:`int_param` 的「非法即 400」口径不同,按可选过滤条件选择用哪个。
    """
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
