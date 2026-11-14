"""使用报告接口的业务码与异常:统计周期取值非法。

业务码目录见 ``config/error_codes.py``;错误信封由 ``config.exceptions`` 统一生成。

文件信息:
    文件名称          stats/exceptions.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from rest_framework.exceptions import APIException

from config import error_codes


class InvalidPeriod(APIException):
    """统计周期不是 ``week`` / ``month`` / ``year``。

    为什么是 400 而不是 404:``period`` 是查询参数的**取值**不合法,不是资源不存在
    —— 取值只有三种,写错就是客户端 bug,按参数校验失败返回,便于客户端定位。
    业务码 ``40005`` 与批次 M / O 的 ``40004`` / ``40003`` 同批分配,互不复用。

    参数说明:
        无(未自定义 ``__init__``,沿用 ``APIException(detail=None, code=None)``)。

    返回参数:
        异常实例本身;抛出后由 ``config.exceptions.api_exception_handler`` 转成错误信封。

    使用示例:
        ``raise InvalidPeriod()``

    备注信息:
        HTTP 400 + 业务码 ``40005``(``detail_code``);由 ``stats.services.parse_period``
        在取值不在 ``PERIODS`` 之内时抛出,响应体 ``message`` 里带出三个合法取值,
        ``code`` / ``message`` / ``request_id`` 三字段由错误信封统一补齐。
    """

    status_code = 400
    default_detail = "统计周期只能是 week / month / year"
    default_code = "invalid_period"
    detail_code = error_codes.INVALID_PERIOD
