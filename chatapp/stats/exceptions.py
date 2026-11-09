"""使用报告接口的业务码与异常:统计周期取值非法。

业务码目录见 ``config/error_codes.py``;错误信封由 ``config.exceptions`` 统一生成。
"""

from rest_framework.exceptions import APIException

from config import error_codes


class InvalidPeriod(APIException):
    """统计周期不是 ``week`` / ``month`` / ``year``。

    为什么是 400 而不是 404:``period`` 是查询参数的**取值**不合法,不是资源不存在
    —— 取值只有三种,写错就是客户端 bug,按参数校验失败返回,便于客户端定位。
    业务码沿用批次 P 工单口径 ``40001``,与「验证码已过期」同码,两者分属不同接口,
    客户端按调用上下文解读(见 docs/api/errors.md「业务码总表」的备注)。
    """

    status_code = 400
    default_detail = "统计周期只能是 week / month / year"
    default_code = "invalid_period"
    detail_code = error_codes.INVALID_PERIOD
