"""上传类接口的幂等键(``Idempotency-Key``):同一个 key 的重试不重复落盘、不重复建行。

设计要点:
    1. **只有带了 ``Idempotency-Key`` 才生效**:不传时视图拿到的是空会话(一次 Redis
       调用都不发),行为与加这一层之前逐字一致 —— 老客户端不受影响是硬约束;
    2. **状态放 Redis,不建库表**:``upload_idem:<scope>:<账号 id>:<key>`` 存
       ``{"id": <行主键>, "status": "ready"|"pending"}``,TTL 24 小时,因此不需要迁移;
       需求里写作 ``上传幂等:<scope>:<user_id>:<key>``,这里改 ASCII 冒号分隔:仓库既有
       缓存键一律 ASCII(``im:imported:42``、``sms:allowlist:snapshot``),中文键在
       ``redis-cli`` 与监控面板里不可读,语义一一对应、不丢信息;
    3. **结果键 + 在途锁两把键**:``upload_idem_lock:<scope>:<账号 id>:<key>`` 只在
       「正在处理」的这段时间存在。抢不到锁且还没有结果 = 同 key 并发,报
       ``409 + 40901``(:class:`UploadInFlight`);
    4. **失败必须释放**:视图没有 :meth:`Session.remember` 就退出上下文(400 / 413 /
       503 / 抛异常),:meth:`Session.close` 会把在途锁与结果键一起删掉,否则用户改好
       文件重传会被自己挡住;
    5. **重放不落盘、不建行**:命中结果键时视图按存下的 id 回查那一行并**重新签名**
       (媒体地址是限时签名,存下来的签名会过期),响应结构与首次一字不差。

注意事项:
    这里所有 Redis 操作都是 fail-open:Redis 抖动时记一次
    ``cache_errors_total{name="upload_idem"}`` 后按「这次没有幂等」继续,不让上传因为
    缓存故障变成 500。代价只是那段时间的重试可能多落一份 —— 正是加这层之前的行为,
    不会更差。

    在途锁的 TTL(``LOCK_TTL``)兜住「进程被杀」的情形:锁到点自动释放,不会把用户
    永久挡在外面;反转的代价是请求真的跑了超过 2 分钟时,第二次请求可能重复处理一次。

    本模块刻意**不是通用中间件**:目前只服务三个媒体上传入口(见 ``IMAGE`` /
    ``CHAT_VOICE`` / ``PROFILE_VOICE``),判定与重放逻辑留给各视图(幂等只是「重复请求
    返回同一个结果」,不改响应字段,也不替视图决定行还在不在)。

关联文档:
    - 接口契约:docs/api/conventions.md §幂等键、docs/api/im.md §6.2 / §6.4、
      docs/api/users.md §2.11
"""

import logging
import re
from contextlib import contextmanager

from django.core.cache import cache
from drf_spectacular.utils import OpenApiParameter
from rest_framework.exceptions import APIException

from . import error_codes, metrics

logger = logging.getLogger(__name__)

#: 请求头名称(原样大小写;Django 的 ``request.headers`` 不区分大小写)。
HEADER = "Idempotency-Key"
#: key 长度上限,也是正则里的上限 —— 客户端一般传 UUID(36 字符)。
MAX_KEY_LENGTH = 128
#: 字符白名单:字母、数字与 ``. _ : -``。UUID / 短哈希 / ``订单号-序号`` 都落在里面,
#: 空白、路径分隔符以外的特殊字符一律拒收(它们会让日志与 Redis 键难读)。
KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,%d}$" % MAX_KEY_LENGTH)

#: 结果映射的 TTL:24 小时。够覆盖「客户端退避重试 + 服务端响应丢失」的全部现实窗口,
#: 也不至于让 Redis 里永久堆积一次性键。
TTL = 24 * 3600
#: 在途锁的 TTL(秒):正常请求秒级完成,这个值只用来兜「进程被杀」,不是业务时长。
LOCK_TTL = 120

#: 已完成(行已落库、响应体可重放)。
READY = "ready"
#: 已受理但还在转码(异步语音路径)。
PENDING = "pending"

#: 作用域名:同一个 key 在不同入口互不干扰(图片与语音各存一份)。
IMAGE = "im_image"
CHAT_VOICE = "im_voice"
PROFILE_VOICE = "profile_voice"

RESULT_KEY = "upload_idem:{}:{}:{}"
LOCK_KEY = "upload_idem_lock:{}:{}:{}"


class UploadInFlight(APIException):
    """同一个 ``Idempotency-Key`` 的上一次上传还在处理中(409 / ``40901``)。

    Attributes:
        status_code: HTTP 409 —— 「请求与资源当前状态冲突」,不是限流也不是服务不可用,
            客户端据此退避后**用同一个 key** 重试即可(那时通常能拿到重放结果)。
        detail_code: 业务码 ``40901``,让客户端不必靠中文文案区分「转码忙」与「同一请求在跑」。
    """

    status_code = 409
    default_detail = "同一次上传正在处理中,请稍后重试"
    default_code = "upload_in_flight"
    detail_code = error_codes.UPLOAD_IN_FLIGHT


class InvalidIdempotencyKey(APIException):
    """``Idempotency-Key`` 不合规(400):维护不了「同一个 key」的对应关系。

    超长或含白名单外字符时**直接拒绝**而不是忽略:忽略会让客户端以为幂等生效,
    重试时才发现多落了一份文件,比当场报错难查得多。

    Attributes:
        status_code: HTTP 400(没有专属业务码,``code`` 退化为 400)。
    """

    status_code = 400
    default_detail = f"Idempotency-Key 不合法:只允许 1-{MAX_KEY_LENGTH} 个字母、数字与 . _ : -"
    default_code = "invalid_idempotency_key"


def value_of(request) -> str | None:
    """读取并校验请求头 ``Idempotency-Key``。

    参数说明:
        request: DRF 请求对象(有 ``headers``)。

    返回参数:
        校验通过的 key;没传(或缺省为空串)时返回 ``None``,表示「本次不要幂等」。

    使用示例:
        ``value = idempotency.value_of(request)``(见本模块 ``guard``)

    备注信息:
        先 ``strip()`` 再校验:HTTP 头允许尾部空白,不能因为客户端多打一个空格就报错,
        但校验通过的值必须**原样**用来拼键 —— 大小写与连字符都是客户端语义的一部分。
        不合规抛 :class:`InvalidIdempotencyKey`(400),由全局异常处理器补 ``request_id``。
    """
    raw = (request.headers.get(HEADER) or "").strip()
    if not raw:
        return None
    if not KEY_PATTERN.match(raw):
        raise InvalidIdempotencyKey()
    return raw


def _hit_cached_error(operation: str) -> None:
    """记一次缓存故障:指标 + 一条 warning(Redis 抖动时的唯一痕迹)。

    参数说明:
        operation: 出错的 Redis 操作名(``read`` / ``claim`` / ``write`` / ``delete``),
            直接进日志字段,便于区分「读结果失败」与「抢锁失败」。

    返回参数:
        无返回值。

    使用示例:
        ``_hit_cached_error("read")``(见本模块 ``Session._read``)

    备注信息:
        只记指标与日志,**不抛异常**:缓存故障不该让上传失败,调用方按 fail-open 继续。
    """
    metrics.CACHE_ERRORS.labels(name="upload_idem").inc()
    logger.warning("upload_idem_cache_failed", extra={"operation": operation})


class Session:
    """一次上传请求的幂等会话(由 :func:`guard` 产出,视图在 ``with`` 里用它)。

    Attributes:
        scope: 作用域名(:data:`IMAGE` / :data:`CHAT_VOICE` / :data:`PROFILE_VOICE`)。
        user_id: 账号 id;键里带上它,别的账号拿同一个 key 也撞不到一起。
        value: 校验过的 key;``None`` 表示本次请求没带(会话是空操作)。
        saved: 命中已完成结果时是 ``{"id": 行主键, "status": ready|pending}``,否则 ``None``。
    """

    def __init__(self, scope: str, user_id: int, value: str | None):
        """建一个会话对象;此时还没有任何 Redis 交互(读结果 / 抢锁在 ``_begin`` 里)。

        参数说明:
            scope: 作用域名。
            user_id: 当前账号 id。
            value: 校验过的 key 或 ``None``。

        返回参数:
            无返回值(构造函数)。

        使用示例:
            ``Session(IMAGE, request.user.id, value_of(request))``(见本模块 ``guard``)

        备注信息:
            ``_owned`` 与 ``_committed`` 是两个独立事实:前者是「本次请求拿着在途锁」,
            后者是「本次请求成功写下了结果」。``close()`` 只在这个请求**拥有**映射时
            才删结果键 —— 否则重放路径会把别人写好的结果删掉。
        """
        self.scope = scope
        self.user_id = user_id
        self.value = value
        self.saved = None
        self._claimed = False
        self._owned = False
        self._committed = False
        self._degraded = False

    @property
    def enabled(self) -> bool:
        """本次请求是否真的在管幂等(带了 key 且 Redis 没出错)。

        返回参数:
            ``True`` 表示读写缓存都健康;``False`` 时本会话的所有写操作都是空操作。

        使用示例:
            ``if not idem.enabled: return``(见本模块 ``Session.remember``)

        备注信息:
        只读属性;Redis 出错后 :attr:`_degraded` 一旦置真就不再复位 —— 一次失败后继续
        读写只会反复超时,不如整条请求退回「没有幂等」。
        """
        return self.value is not None and not self._degraded

    def remember(self, pk: int, status: str) -> None:
        """把「key → 行主键 + 状态」写进 Redis(TTL 24 小时)。

        参数说明:
            pk: 刚落库那一行的主键。
            status: :data:`READY`(行已可用)或 :data:`PENDING`(异步语音还在转码)。

        返回参数:
            无返回值。

        使用示例:
            ``idem.remember(chat_image.id, idempotency.READY)``(见 ``im/views.py::upload_image``)

        备注信息:
            必须在**行已经提交**(``save()`` 之后)才调用:重放路径会按这个 id 回查那一行,
            写下早于提交的 id 会让并发重放读到 404。
            写失败只降级不抛异常(fail-open),``_committed`` 保持 ``False``,
            于是 ``close()`` 走「失败释放」分支 —— 宁可少一次幂等,也不留一个没有结果的锁。
        """
        if not self.enabled:
            return
        try:
            cache.set(self._result_key(), {"id": int(pk), "status": status}, TTL)
        except Exception:  # noqa: BLE001  Redis 抖动不该让上传失败
            _hit_cached_error("write")
            self._degraded = True
            return
        self._committed = True

    def discard(self) -> None:
        """丢掉已失效的结果映射(行被删 / 过期回收 / 转码失败),按首次请求重新处理。

        返回参数:
            无返回值;抢不到在途锁时抛 :class:`UploadInFlight`。

        使用示例:
            ``idem.discard()``(见 ``im/views.py::upload_image`` 的重放分支)

        备注信息:
            「结果键还在、行没了」是必须处理的一种常态:运营删图、30 天回收、资料语音被
            覆盖成 ``failed``,都会留下一个指向空处的映射。此时若照旧重放,用户会拿到
            一个永远 404 的 id;若报错,用户被自己挡住。正确做法是删映射并重新处理 ——
            所以这里同时**抢在途锁**,保证重新处理这件事本身也不会并发两次。
        """
        if self.value is None:
            return
        self._delete(self._result_key())
        self.saved = None
        self._claim()

    def close(self) -> None:
        """退出上下文:释放在途锁;本次请求没写成结果时连结果键一起删(失败释放)。

        返回参数:
            无返回值。

        使用示例:
            ``session.close()``(见本模块 ``guard`` 的 ``finally``)

        备注信息:
            顺序是「先有结果,后放锁」:``remember()`` 在视图里早已执行,``close()`` 只放锁。
            反过来的话,窗口里挤进来的第二个请求会看不到结果、也抢得到锁,于是重复处理一次。
            结果键**只在本请求拥有它时才删**(``_owned``):纯粹的重放请求没抢锁也没写过
            结果,它若也走失败释放,会把别人写好、刚到手的映射删掉,下一次重试就白跑一次。
            所有删除都吞异常:退出路径上的 Redis 故障不该把已经成功的上传变成 500,
            残留键有 TTL 兜底。
        """
        if self.value is None:
            return
        if self._owned and not self._committed:
            self._delete(self._result_key())
        if self._claimed:
            self._delete(self._lock_key())

    def _result_key(self) -> str:
        """拼结果键(``upload_idem:<scope>:<账号 id>:<key>``)。

        返回参数:
            结果键字符串。

        使用示例:
            ``session._result_key()``(见本模块 ``Session.remember``)

        备注信息:
            账号 id 与 key 都在键里:同一 key 被两个账号用不会互相串结果。
        """
        return RESULT_KEY.format(self.scope, self.user_id, self.value)

    def _lock_key(self) -> str:
        """拼在途锁键(``upload_idem_lock:<scope>:<账号 id>:<key>``)。

        返回参数:
            在途锁键字符串。

        使用示例:
            ``session._lock_key()``(见本模块 ``Session._claim``)

        备注信息:
            与结果键分开,是因为两者的生命周期完全不同:结果留 24 小时,锁只活一次请求。
        """
        return LOCK_KEY.format(self.scope, self.user_id, self.value)

    def _read(self) -> dict | None:
        """读结果映射;没命中、内容形不合规或 Redis 故障都返回 ``None``。

        返回参数:
            ``{"id": int, "status": str}`` 或 ``None``。

        使用示例:
            ``self.saved = self._read()``(见本模块 ``Session._begin``)

        备注信息:
            内容做个形状校验再认:缓存可能被别的东西写脏(开发时共用一个 Redis),
            认不出来就当没命中 —— 宁可多处理一次,也不要拿一个假 id 去回查。
        """
        try:
            stored = cache.get(self._result_key())
        except Exception:  # noqa: BLE001
            _hit_cached_error("read")
            self._degraded = True
            return None
        if not isinstance(stored, dict):
            return None
        pk, status = stored.get("id"), stored.get("status")
        if not isinstance(pk, int) or status not in (READY, PENDING):
            return None
        return {"id": pk, "status": status}

    def _claim(self) -> None:
        """抢在途锁;抢到后本次请求独占这个 key,抢不到抛 ``UploadInFlight``。

        返回参数:
            无返回值;抢不到抛 :class:`UploadInFlight`,Redis 故障则降级为「没有幂等」。

        使用示例:
            ``self._claim()``(见本模块 ``Session._begin`` / ``Session.discard``)

        备注信息:
            ``cache.add`` 是原子的 ``SETNX``,只有第一个请求能建成,这就是「只处理一次」
            的机械依据(与 ``config.cache_utils.get_or_load`` 的击穿保护同一手法)。
            Redis 报错时**不**当成「别人占着」:那会让所有上传在缓存抖动期间变成 409。
        """
        try:
            acquired = cache.add(self._lock_key(), 1, LOCK_TTL)
        except Exception:  # noqa: BLE001
            _hit_cached_error("claim")
            self._degraded = True
            return
        if not acquired:
            raise UploadInFlight()
        self._claimed = True
        self._owned = True

    def _delete(self, key: str) -> None:
        """删一个键,失败只记指标(退出路径上不允许抛异常)。

        参数说明:
            key: 待删除的缓存键。

        返回参数:
            无返回值。

        使用示例:
            ``self._delete(self._lock_key())``(见本模块 ``Session.close``)

        备注信息:
            不判返回值:键本来就不存在时 ``delete`` 返回假,属于正常路径。
        """
        try:
            cache.delete(key)
        except Exception:  # noqa: BLE001
            _hit_cached_error("delete")

    def _begin(self) -> None:
        """进入请求:命中结果就只读重放,否则抢在途锁;并发冲突抛 ``UploadInFlight``。

        返回参数:
            无返回值。

        使用示例:
            ``session._begin()``(见本模块 ``guard``)

        备注信息:
            抢锁失败后再读一次结果:对方可能刚好写完结果、只差放锁,这一读能把「本来
            应该重放」的请求救回来,避免把成功的上传误报成 409。
        """
        if self.value is None:
            return
        self.saved = self._read()
        if self.saved is not None:
            return
        try:
            self._claim()
        except UploadInFlight:
            self.saved = self._read()
            if self.saved is not None:
                return
            raise


def schema_parameter():
    """给 ``@extend_schema(parameters=[...])`` 用的请求头声明(三个上传入口共用一份文案)。

    返回参数:
        ``OpenApiParameter``:``Idempotency-Key``(header,可选)。

    使用示例:
        ``@extend_schema(parameters=[idempotency.schema_parameter()], ...)``
        (见 ``im/views.py::upload_image``)

    备注信息:
        三个入口各调一次工厂函数而不是共享一个模块级实例:drf-spectacular 生成 schema 时
        会就地补全参数对象,共享实例容易互相污染(与 ``config/schema_helpers.py`` 同一口径)。
        这次声明会落进 ``docs/api/openapi.yml``,因此分册的「请求参数」表必须同改
        (``config/test_schema_contract.py`` 双向比对)。
    """
    return OpenApiParameter(
        HEADER, str, OpenApiParameter.HEADER, required=False,
        description=("可选幂等键:1-128 个字母、数字与 . _ : -,客户端每次上传生成一个,"
                     "重试时复用同一个。服务端 24 小时内对同一个 key 只处理一次,"
                     "重试直接返回首次的结果(命中已完成的映射时不会重复落盘、不会多建行)。"))


@contextmanager
def guard(request, scope: str):
    """上传视图的幂等上下文:``with idempotency.guard(request, idempotency.IMAGE) as idem:``。

    参数说明:
        request: DRF 请求对象(取 ``headers`` 与 ``user``)。
        scope: 作用域名(:data:`IMAGE` / :data:`CHAT_VOICE` / :data:`PROFILE_VOICE`)。

    返回参数:
        生成器上下文:产出 :class:`Session`。没带 key 时产出空会话(``saved`` 为 ``None``、
        所有方法都是空操作),视图代码不需要为「有没有 key」分支。

    使用示例:
        ``with idempotency.guard(request, idempotency.IMAGE) as idem:``
        (见 ``im/views.py::upload_image``)

    备注信息:
        并发同 key 时在 ``with`` 入口就抛 :class:`UploadInFlight`(409 + ``40901``),
        视图里不用写冲突分支;``with`` 体里抛出的任何异常(含 400/413/503 的
        ``Response`` 之外的异常)都会走 ``finally`` 释放键,满足「失败要能重试」。
    """
    session = Session(scope, request.user.id, value_of(request))
    session._begin()
    try:
        yield session
    finally:
        session.close()
