"""滑卡增强(批次 O)的业务异常。

两个异常各带一个专属业务码(定义在 ``config/error_codes.py``),由
``config.exceptions.api_exception_handler`` 统一转成 ``{code, message, request_id}`` 信封:

    - :class:`SwipeUndoUnavailable`:撤销失败,``400`` + ``40003``;
    - :class:`SwipeLikeQuotaExceeded`:当日喜欢额度用完,``429`` + ``42904``,带 ``Retry-After``。

为什么撤销失败不复用重封禁/参数校验那套:客户端需要把「没有可撤销的那一次」
（按钮本该置灰）与「参数错了」区分开,否则只能靠中文文案做分支。

文件信息:
    文件名称          discovery/exceptions.py
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


class SwipeUndoUnavailable(APIException):
    """没有可撤销的滑卡(超过 30 秒 / 已产生配对 / 本来就没有记录)。

    参数说明:
        detail: 覆盖默认中文文案,默认取 ``default_detail``。
        code: 覆盖默认错误码,默认取 ``default_code``。

    返回参数:
        无返回值;作为异常抛出,由 ``config.exceptions.api_exception_handler`` 转成错误信封。

    使用示例:
        ``raise SwipeUndoUnavailable()``

    备注信息:
        ``400`` + ``40003``;``detail_code`` 取自 ``config/error_codes.py``,
        与 ``default_code`` 分工是「业务码」对「DRF 内部标识」。
    """

    status_code = 400
    default_detail = "没有可撤销的滑卡"
    default_code = "swipe_undo_unavailable"
    detail_code = error_codes.SWIPE_UNDO_UNAVAILABLE


class SwipeLikeQuotaExceeded(Throttled):
    """当日喜欢次数已用完(``429`` + ``42904``)。

    Attributes:
        wait: 距下一个自然日(``Asia/Shanghai``)的秒数;DRF 的异常处理器见到它会给响应
            加 ``Retry-After`` 头,与 ``42901`` / ``42902`` 的处理方式一致。

    参数说明:
        wait: 距额度重置的秒数,默认 ``None``(此时不带 ``Retry-After``)。

    返回参数:
        无返回值;作为异常抛出,由 ``config.exceptions.api_exception_handler`` 转成错误信封。

    使用示例:
        ``raise SwipeLikeQuotaExceeded(wait=ttl)``

    备注信息:
        ``status_code`` 继承自 ``Throttled``,恒为 ``429``;业务码 ``42904`` 定义在
        ``config/error_codes.py``。
    """

    default_detail = "今天的喜欢次数已用完,明天再来吧"
    detail_code = error_codes.SWIPE_LIKE_QUOTA_EXCEEDED

    def __init__(self, wait=None):
        """记录恢复所需的秒数。

        ``self.wait`` 必须在 ``super().__init__()`` **之后**赋值:DRF 的
        ``Throttled.__init__`` 会用自己的 ``wait`` 参数(默认 ``None``)覆写这个属性,
        写在前面会被清掉,响应就丢了 ``Retry-After``。同理不走 ``wait=`` 形参 ——
        那会让 DRF 在中文文案后面追加一句英文 ``Expected available in N seconds.``,
        而这里等的是「到明天 0 点」,读起来更像故障而不是配额。

        参数说明:
            wait: 距额度重置(次日 00:00)的秒数,用于 ``Retry-After``。

        返回参数:
            无返回值。

        使用示例:
            ``raise SwipeLikeQuotaExceeded(wait=3600)``

        备注信息:
            不传 ``wait`` 时退回 ``default_detail``,响应里没有 ``Retry-After``。
        """
        detail = (f"今天的喜欢次数已用完,预计 {int(wait)} 秒后恢复"
                  if wait else self.default_detail)
        super().__init__(detail=detail)
        self.wait = wait
