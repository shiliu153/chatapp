"""查询参数的统一校验。

设计要点:
    1. 非法参数一律变成 400(统一错误信封),不允许把 ``ValueError`` 漏成 500;
    2. 数值参数越界时**收敛到边界**而不是报错 —— 老客户端可能传 ``limit=999``,
       收敛比直接拒绝更兼容;
    3. 只处理「可选过滤条件」的场景(如审核台的 ``user``):非法值返回 ``None``,
       由调用方决定「忽略该过滤」还是「报错」。
"""

from rest_framework.exceptions import ValidationError


def _raw(request, name: str):
    """从 DRF 请求或 Django 请求里取原始查询参数。

    参数说明:
        request: DRF 请求对象(有 ``query_params``)或 Django 请求对象(只有 ``GET``)。
        name: 参数名。

    返回参数:
        原始字符串;不存在时返回 ``None``。

    使用示例:
        ``raw = _raw(request, "limit")``(见 ``params.int_param``)

    备注信息:
        不 strip、不做类型转换:清洗与校验留给调用方,空串与缺省由调用方区分。
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
        ``limit = int_param(request, "limit", default=default_limit, minimum=1,
        maximum=max_limit)``(见 ``config/cursor.py::slice_page``)

    备注信息:
        参数存在但不是整数时抛 ``ValidationError``,DRF 按统一错误信封转成 400。
        数值超界**不报错**,收敛到 ``minimum`` / ``maximum``。
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
        ``user_id = optional_id(request.GET.get("user"))``(见 ``ops/views.py`` 的聊天图片抽审列表)

    备注信息:
        不抛异常:审核台的过滤参数非法时静默忽略,避免后台列表因为一个脏参数打不开。
    """
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
