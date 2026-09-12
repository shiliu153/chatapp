from rest_framework.exceptions import APIException, Throttled

from config import error_codes


class SingleDeviceSessionConflict(APIException):
    """账号已在其他设备登录(单设备登录策略)。"""

    status_code = 401
    default_detail = "账号已在其他设备登录,请重新登录"
    default_code = "single_device"
    detail_code = error_codes.SESSION_CONFLICT


class SmsCodeExpired(APIException):
    status_code = 400
    default_detail = "验证码已过期,请重新获取"
    detail_code = error_codes.SMS_CODE_EXPIRED


class SmsCodeWrong(APIException):
    status_code = 400
    default_detail = "验证码错误"
    detail_code = error_codes.SMS_CODE_WRONG


class SmsLocked(APIException):
    status_code = 429
    default_detail = "错误次数过多,请稍后再试"
    detail_code = error_codes.SMS_TOO_MANY_ATTEMPTS


class SmsSendTooFrequent(Throttled):
    default_detail = "发送太频繁,请稍后再试"
    detail_code = error_codes.SMS_SEND_TOO_FREQUENT


class SmsServiceUnavailable(APIException):
    status_code = 503
    default_detail = "短信服务暂时不可用,请稍后重试"
    detail_code = error_codes.SMS_SERVICE_UNAVAILABLE
