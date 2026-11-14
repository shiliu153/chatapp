"""账号与短信验证码相关的业务异常。

设计要点:
    每个异常通过 ``detail_code`` 携带业务码(定义在 ``config/error_codes.py``),
    由 ``config.exceptions.api_exception_handler`` 统一转成
    ``{code, message, request_id}`` 信封;没有 ``detail_code`` 的异常则退化为
    HTTP 状态码作业务码。

文件信息:
    文件名称          accounts/exceptions.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from rest_framework.exceptions import APIException, Throttled

from config import error_codes


class SingleDeviceSessionConflict(APIException):
    """账号已在其他设备登录(单设备登录策略)。

    参数说明:
        无(未自定义 ``__init__``,沿用 ``APIException(detail=None, code=None)``)。

    返回参数:
        异常实例本身;抛出后由 ``config.exceptions.api_exception_handler`` 转成错误信封。

    使用示例:
        ``raise SingleDeviceSessionConflict()``

    备注信息:
        HTTP 401 + 业务码 ``40101``(``detail_code``);由
        ``accounts.authentication.SessionJwtAuthentication`` 在令牌版本不一致时抛出,
        前端据此强退到登录页。
    """

    status_code = 401
    default_detail = "账号已在其他设备登录,请重新登录"
    default_code = "single_device"
    detail_code = error_codes.SESSION_CONFLICT


class SmsCodeExpired(APIException):
    """验证码已过期或不存在。

    参数说明:
        无(未自定义 ``__init__``,沿用 ``APIException(detail=None, code=None)``)。

    返回参数:
        异常实例本身;抛出后由 ``config.exceptions.api_exception_handler`` 转成错误信封。

    使用示例:
        ``raise SmsCodeExpired()``

    备注信息:
        HTTP 400 + 业务码 ``40001``(``detail_code``);Redis 里查不到该手机号的验证码
        (未发送、已过期或已被消费)时抛出。
    """

    status_code = 400
    default_detail = "验证码已过期,请重新获取"
    detail_code = error_codes.SMS_CODE_EXPIRED


class SmsCodeWrong(APIException):
    """验证码错误(尚未触发锁定)。

    参数说明:
        无(未自定义 ``__init__``,沿用 ``APIException(detail=None, code=None)``)。

    返回参数:
        异常实例本身;抛出后由 ``config.exceptions.api_exception_handler`` 转成错误信封。

    使用示例:
        ``raise SmsCodeWrong()``

    备注信息:
        HTTP 400 + 业务码 ``40002``(``detail_code``);错误次数未达阈值时用它,
        达到阈值改抛 ``SmsLocked``(429)。
    """

    status_code = 400
    default_detail = "验证码错误"
    detail_code = error_codes.SMS_CODE_WRONG


class SmsLocked(APIException):
    """连续错误次数超限,验证码校验被临时锁定。

    参数说明:
        wait: 还需等待的秒数;传入后 DRF 全局处理器会给响应加 ``Retry-After`` 头。

    返回参数:
        异常实例本身;抛出后由 ``config.exceptions.api_exception_handler`` 转成错误信封。

    使用示例:
        ``SmsLocked(wait=settings.SMS_LOCK_TTL)``

    备注信息:
        HTTP 429 + 业务码 ``42902``(``detail_code``);``wait`` 只用于 ``Retry-After`` 头,
        是否已锁定由 ``accounts.sms_codes.verify`` 的 Redis 锁定键决定,不读 ``wait``。
    """

    status_code = 429
    default_detail = "错误次数过多,请稍后再试"
    detail_code = error_codes.SMS_TOO_MANY_ATTEMPTS

    def __init__(self, wait=None):
        """记录剩余锁定秒数。

        参数说明:
            wait: 还需等待的秒数;DRF 的异常处理器见到 ``wait`` 属性会给响应
                加上 ``Retry-After`` 头。

        返回参数:
            无返回值(构造即初始化实例)。

        使用示例:
            ``SmsLocked(wait=settings.SMS_LOCK_TTL)``

        备注信息:
            实例化后立即调用 ``super().__init__()`` 走 DRF 的默认 detail/code 装配;
            ``wait`` 允许 ``None``,此时不加 ``Retry-After`` 头。
        """
        self.wait = wait      # DRF 全局处理器见到 wait 会给响应加 Retry-After
        super().__init__()


class SmsSendTooFrequent(Throttled):
    """同一手机号在重发间隔内再次请求验证码。

    参数说明:
        wait: 还需等待的秒数(继承自 DRF ``Throttled``);传入后响应带 ``Retry-After`` 头。

    返回参数:
        异常实例本身;抛出后由 ``config.exceptions.api_exception_handler`` 转成错误信封。

    使用示例:
        ``raise SmsSendTooFrequent(wait=settings.SMS_RESEND_INTERVAL)``

    备注信息:
        HTTP 429 + 业务码 ``42901``(``detail_code``);父类 ``Throttled`` 的状态码与
        ``{wait}`` 文案插值沿用 DRF 实现。
    """

    default_detail = "发送太频繁,请稍后再试"
    detail_code = error_codes.SMS_SEND_TOO_FREQUENT


class SmsServiceUnavailable(APIException):
    """短信任务入队失败,按 fail-closed 拒绝本次请求。

    参数说明:
        无(未自定义 ``__init__``,沿用 ``APIException(detail=None, code=None)``)。

    返回参数:
        异常实例本身;抛出后由 ``config.exceptions.api_exception_handler`` 转成错误信封。

    使用示例:
        ``raise SmsServiceUnavailable()``

    备注信息:
        HTTP 503 + 业务码 ``50301``(``detail_code``);Celery 入队失败时抛出,
        宁可拒绝也不假装已发送(响应路径禁止第三方网络调用)。抛出前调用方已用
        ``services.rollback_send`` 回滚占位与码,用户不会被重发间隔卡死。
    """

    status_code = 503
    default_detail = "短信服务暂时不可用,请稍后重试"
    detail_code = error_codes.SMS_SERVICE_UNAVAILABLE


class PhoneNotAllowed(APIException):
    """号码不在封闭测试白名单内(B-1 / K-1)。

    固定验证码 + 任意手机号意味着「知道号码即可接管账号」,因此封闭测试期
    只放行白名单内的号码。本项目不接入短信商(2026-11-03 决定),白名单是**长期准入机制**,
    所以它要按「谁算自己人」来管,而不是当临时开关。

    参数说明:
        无(未自定义 ``__init__``,沿用 ``APIException(detail=None, code=None)``)。

    返回参数:
        异常实例本身;抛出后由 ``config.exceptions.api_exception_handler`` 转成错误信封。

    使用示例:
        ``raise PhoneNotAllowed()``

    备注信息:
        HTTP 403 + 业务码 ``40301``(``detail_code``);白名单判定见
        ``accounts/services.py`` 与 ``accounts.PhoneAllowlist`` 表。
    """

    status_code = 403
    default_detail = "当前为封闭测试,该手机号未在受邀名单内"
    detail_code = error_codes.PHONE_NOT_ALLOWED


class InvalidClientType(APIException):
    """端类型不是 ``app`` / ``web``(登录设备的「下线该端」用)。

    为什么是 400 而不是 404:路径里的 ``{client_type}`` 是**取值**不合法,不是资源不存在
    —— 端类型只有两种,写错就是客户端 bug,按参数校验失败返回,便于客户端定位。

    参数说明:
        无(未自定义 ``__init__``,沿用 ``APIException(detail=None, code=None)``)。

    返回参数:
        异常实例本身;抛出后由 ``config.exceptions.api_exception_handler`` 转成错误信封。

    使用示例:
        ``raise InvalidClientType()``

    备注信息:
        HTTP 400 + 业务码 ``40004``(``detail_code``);仅用于「下线该端」路径里
        ``{client_type}`` 取值非 ``app`` / ``web`` 的情形。
    """

    status_code = 400
    default_detail = "客户端类型不合法,只能是 app 或 web"
    default_code = "invalid_client_type"
    detail_code = error_codes.INVALID_CLIENT_TYPE
