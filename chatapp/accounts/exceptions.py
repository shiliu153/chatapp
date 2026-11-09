"""账号与短信验证码相关的业务异常。

设计要点:
    每个异常通过 ``detail_code`` 携带业务码(定义在 ``config/error_codes.py``),
    由 ``config.exceptions.api_exception_handler`` 统一转成
    ``{code, message, request_id}`` 信封;没有 ``detail_code`` 的异常则退化为
    HTTP 状态码作业务码。
"""

from rest_framework.exceptions import APIException, Throttled

from config import error_codes


class SingleDeviceSessionConflict(APIException):
    """账号已在其他设备登录(单设备登录策略)。"""

    status_code = 401
    default_detail = "账号已在其他设备登录,请重新登录"
    default_code = "single_device"
    detail_code = error_codes.SESSION_CONFLICT


class SmsCodeExpired(APIException):
    """验证码已过期或不存在。"""

    status_code = 400
    default_detail = "验证码已过期,请重新获取"
    detail_code = error_codes.SMS_CODE_EXPIRED


class SmsCodeWrong(APIException):
    """验证码错误(尚未触发锁定)。"""

    status_code = 400
    default_detail = "验证码错误"
    detail_code = error_codes.SMS_CODE_WRONG


class SmsLocked(APIException):
    """连续错误次数超限,验证码校验被临时锁定。"""

    status_code = 429
    default_detail = "错误次数过多,请稍后再试"
    detail_code = error_codes.SMS_TOO_MANY_ATTEMPTS

    def __init__(self, wait=None):
        """记录剩余锁定秒数。

        Args:
            wait: 还需等待的秒数;DRF 的异常处理器见到 ``wait`` 属性会给响应
                加上 ``Retry-After`` 头。
        """
        self.wait = wait      # DRF 全局处理器见到 wait 会给响应加 Retry-After
        super().__init__()


class SmsSendTooFrequent(Throttled):
    """同一手机号在重发间隔内再次请求验证码。"""

    default_detail = "发送太频繁,请稍后再试"
    detail_code = error_codes.SMS_SEND_TOO_FREQUENT


class SmsServiceUnavailable(APIException):
    """短信任务入队失败,按 fail-closed 拒绝本次请求。"""

    status_code = 503
    default_detail = "短信服务暂时不可用,请稍后重试"
    detail_code = error_codes.SMS_SERVICE_UNAVAILABLE


class PhoneNotAllowed(APIException):
    """号码不在封闭测试白名单内(B-1 / K-1)。

    固定验证码 + 任意手机号意味着「知道号码即可接管账号」,因此封闭测试期
    只放行白名单内的号码。本项目不接入短信商(2026-11-03 决定),白名单是**长期准入机制**,
    所以它要按「谁算自己人」来管,而不是当临时开关。
    """

    status_code = 403
    default_detail = "当前为封闭测试,该手机号未在受邀名单内"
    detail_code = error_codes.PHONE_NOT_ALLOWED


class InvalidClientType(APIException):
    """端类型不是 ``app`` / ``web``(登录设备的「下线该端」用)。

    为什么是 400 而不是 404:路径里的 ``{client_type}`` 是**取值**不合法,不是资源不存在
    —— 端类型只有两种,写错就是客户端 bug,按参数校验失败返回,便于客户端定位。
    """

    status_code = 400
    default_detail = "客户端类型不合法,只能是 app 或 web"
    default_code = "invalid_client_type"
    detail_code = error_codes.INVALID_CLIENT_TYPE
