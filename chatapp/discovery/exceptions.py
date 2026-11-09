"""滑卡增强(批次 O)的业务异常。

两个异常各带一个专属业务码(定义在 ``config/error_codes.py``),由
``config.exceptions.api_exception_handler`` 统一转成 ``{code, message, request_id}`` 信封:

    - :class:`SwipeUndoUnavailable`:撤销失败,``400`` + ``40003``;
    - :class:`SwipeLikeQuotaExceeded`:当日喜欢额度用完,``429`` + ``42904``,带 ``Retry-After``。

为什么撤销失败不复用重封禁/参数校验那套:客户端需要把「没有可撤销的那一次」
（按钮本该置灰）与「参数错了」区分开,否则只能靠中文文案做分支。
"""

from rest_framework.exceptions import APIException, Throttled

from config import error_codes


class SwipeUndoUnavailable(APIException):
    """没有可撤销的滑卡(超过 30 秒 / 已产生配对 / 本来就没有记录)。"""

    status_code = 400
    default_detail = "没有可撤销的滑卡"
    default_code = "swipe_undo_unavailable"
    detail_code = error_codes.SWIPE_UNDO_UNAVAILABLE


class SwipeLikeQuotaExceeded(Throttled):
    """当日喜欢次数已用完(``429`` + ``42904``)。

    Attributes:
        wait: 距下一个自然日(``Asia/Shanghai``)的秒数;DRF 的异常处理器见到它会给响应
            加 ``Retry-After`` 头,与 ``42901`` / ``42902`` 的处理方式一致。
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

        Args:
            wait: 距额度重置(次日 00:00)的秒数,用于 ``Retry-After``。
        """
        detail = (f"今天的喜欢次数已用完,预计 {int(wait)} 秒后恢复"
                  if wait else self.default_detail)
        super().__init__(detail=detail)
        self.wait = wait
