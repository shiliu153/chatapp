"""用户资料应用的测试:年龄换算、资料完善度、资料/照片/偏好、在线状态与账号注销。

覆盖场景:
    - 年龄换算:生日当天恰好 18 岁、差一天算 17;年龄区间换算成生日区间、闰日退化;
    - 资料完善度:新资料默认未完善、``refresh_status`` 不覆盖封禁状态;
    - 标签池由数据迁移写入;
    - 我的资料:鉴权、懒创建、``user_id`` 是账号 id 而非资料主键、标签池;
    - 编辑资料:局部更新、昵称变化才同步 IM、未满 18 拒绝、违禁词、非法标签与性别;
    - 照片:开发期上传即过审、过审同步头像、非图片拒绝、6 张上限、删自己的照片与文件、
      不能删别人的、状态随照片增减在完善/未完善间流转;
    - 资料语音:3 秒 201 + 签名地址、31 秒 400(提示 30 秒)、覆盖上传只剩一条且旧文件已删、
      我的/他人资料都返回 ``voice``、没录过为 ``null``、DELETE 幂等且删文件、
      配额超限 413+41301 且不落盘、缺 ffmpeg 503+50302、不进「资料完善」判定、限流;
    - 偏好:默认值、更新、区间非法、未满 18 下限、目标性别为空表示不限;
    - admin 审核动作:驳回与通过时的状态重算、记录审核人与时间;
    - 他人资料卡:只返回公开字段、重封禁不可见、轻封禁可见、拉黑双向不可见、404;
    - 共同标签:只返回交集且按 id 升序、无交集/我没标签时为空数组、查询条数不随标签数增长;
    - 资料卡关注态:默认未关注且计数为 0、关注后 ``is_followed`` 为真、粉丝/关注数正确、
      查询条数不随关注数增长;
    - 抓取监控:同目标一小时只计一次、跨目标累加、超阈值告警、Redis 故障不影响响应;
    - 在线状态服务:写入后在线、窗口边界、未知用户、本地时区 ISO、Redis 故障降级;
    - 日活集合:按天与按小时去重、空日返回 None、45 天 TTL、按 Asia/Shanghai 切日、
      Redis 故障降级,以及「presence.touch 顺手记日活」的接线;
    - 在线状态接口:鉴权、返回在线与最后活跃、剔除拉黑/自己/未知/重封禁、去重保序、
      参数校验、限流、Redis 故障返回 null 而非 500;
    - 账号注销:鉴权、手机号不一致或缺失拒绝、重封禁禁止注销、删除全部关联数据与磁盘文件、
      清理在线状态与待踢标记、提交后按 im_user_id 入队删号、旧令牌失效、同号可重注册。

文件信息:
    文件名称          users/tests.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import base64
import io
import os
import shutil
import tempfile
import time
from datetime import date, datetime, timedelta, timezone as dt_timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.models import Q
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from PIL import Image
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from accounts import sms_codes
from config import storage
from discovery.models import Match, Swipe
from feed.models import Follow, Post, PostComment, PostImage
from im import tasks as im_tasks
from im.models import ChatImage, ChatImageStatus, ChatVoice, ChatVoiceStatus
from moderation.models import BanLog, Block, Report

from . import activity, presence, services
from .models import (Photo, PhotoStatus, Profile, ProfileStatus, ProfileVisit, ProfileVoice,
                     Tag, birthday_bounds, calculate_age)

User = get_user_model()


class AgeTests(SimpleTestCase):
    """周岁换算:生日当天恰好满岁,差一天仍算上一岁。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.AgeTests``

    备注信息:
        纯函数用例,继承 ``SimpleTestCase``,不碰数据库。
    """

    def test_calculate_age_boundary(self):
        """周岁边界:生日当天正好 18,差一天仍算 17。

        参数说明:
            无。
        """
        today = date(2026, 9, 10)
        self.assertEqual(calculate_age(date(2008, 9, 11), today), 17)   # 差一天
        self.assertEqual(calculate_age(date(2008, 9, 10), today), 18)   # 生日当天刚好 18


class BirthdayBoundsTests(SimpleTestCase):
    """年龄区间换算成生日区间,含闰日退化的边界。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.BirthdayBoundsTests``

    备注信息:
        同样不碰数据库;``today`` 由用例显式传入,断言不随运行日期漂移。
    """

    def test_bounds(self):
        """年龄区间换算生日区间:上界是刚好满最小年龄那天,下界是超出最大年龄的边界。

        参数说明:
            无。
        """
        upper, lower = birthday_bounds(18, 30, today=date(2026, 9, 10))
        self.assertEqual(upper, date(2008, 9, 10))   # 生在这天 = 刚好 18 岁
        self.assertEqual(lower, date(1995, 9, 10))   # 生在更早 = 31 岁,排除

    def test_leap_day(self):
        """闰日退化:从 2 月 29 日倒推一年,生日上界落到 2 月 28 日。

        参数说明:
            无。
        """
        upper, _ = birthday_bounds(1, 30, today=date(2024, 2, 29))
        self.assertEqual(upper, date(2023, 2, 28))


class ProfileModelTests(TestCase):
    """资料模型:默认未完善,重算状态时不会覆盖封禁状态。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.ProfileModelTests``

    备注信息:
        断言直接落在模型方法上,不经过接口层。
    """

    def setUp(self):
        """建一个不带资料的账号,供各用例复用。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``

        备注信息:
            每个用例前由测试框架自动调用,资料行由用例自己创建。
        """
        self.user = User.objects.create_user(phone="13800138000")

    def test_new_profile_is_incomplete(self):
        """新建资料默认未完善,缺昵称与照片。

        参数说明:
            无。
        """
        profile = Profile.objects.create(user=self.user)
        self.assertEqual(profile.status, ProfileStatus.INCOMPLETE)
        self.assertIn("nickname", profile.missing_fields())
        self.assertIn("photos", profile.missing_fields())

    def test_refresh_status_does_not_override_ban(self):
        """``refresh_status`` 不覆盖重封禁状态。

        参数说明:
            无。
        """
        profile = Profile.objects.create(user=self.user, status=ProfileStatus.BANNED_HEAVY)
        profile.refresh_status()
        self.assertEqual(profile.status, ProfileStatus.BANNED_HEAVY)


class SeedTagTests(TestCase):
    """标签池:由数据迁移写入,数量不少于 10 个。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.SeedTagTests``

    备注信息:
        标签由数据迁移写入,用例里不造数据。
    """

    def test_tags_seeded_by_migration(self):
        """标签池由数据迁移写入,数量不少于 10 个。

        参数说明:
            无。
        """
        self.assertGreaterEqual(Tag.objects.count(), 10)


class AuthMixin:
    """接口用例公共设施:给测试客户端装上指定用户的令牌。

    参数说明:
        无构造参数。

    返回参数:
        混入类本身不实例化,只提供能力。

    使用示例:
        ``class MeTests(AuthMixin, APITestCase)``

    备注信息:
        本身不含用例;与 ``APITestCase`` 一起混入后提供 ``self.login(user)``。
    """

    def login(self, user):
        """把指定用户的 access token 装到测试客户端。

        参数说明:
            user: 目标用户。

        返回参数:
            无返回值。

        使用示例:
            ``self.login(user)``

        备注信息:
            装的是 access token,后续请求都带该账号身份;再次调用会覆盖前一次登录的令牌。
        """
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")


class MeTests(AuthMixin, APITestCase):
    """我的资料:鉴权、懒创建、``user_id`` 语义与标签池。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.MeTests``

    备注信息:
        资料行由接口懒创建,用例里不要预先建 ``Profile``。
    """

    def setUp(self):
        """建一个不带资料的账号,供各用例复用。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``

        备注信息:
            资料行不在这里创建,用于验证接口的懒创建行为。
        """
        self.user = User.objects.create_user(phone="13800138000")

    def test_requires_auth(self):
        """未登录读我的资料返回 401 与错误码 401。

        参数说明:
            无。
        """
        resp = self.client.get("/api/v1/users/me")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["code"], 401)

    def test_me_creates_profile_lazily(self):
        """首次读我的资料会懒创建资料行,返回手机号与未完善状态。

        参数说明:
            无。
        """
        self.login(self.user)
        resp = self.client.get("/api/v1/users/me")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["phone"], "13800138000")
        self.assertEqual(data["status"], "incomplete")
        self.assertEqual(data["photos"], [])
        self.assertEqual(data["tags"], [])
        self.assertIn("nickname", data["missing_fields"])
        self.assertTrue(Profile.objects.filter(user=self.user).exists())

    def test_me_user_id_is_account_id_not_profile_pk(self):
        """``user_id`` 是账号 id,``id`` 才是资料主键,两者不能混用。

        参数说明:
            无。
        """
        # 我的页「ID」行要显示账号 ID(u7),不是 profile 主键(u7 的资料是第 6 条)
        other = User.objects.create_user(phone="13800138001")
        Profile.objects.get_or_create(user=other)   # 先占掉 profile 自增 1
        self.login(self.user)
        data = self.client.get("/api/v1/users/me").json()
        self.assertEqual(data["user_id"], self.user.id)
        self.assertNotEqual(data["id"], data["user_id"])   # id 仍是 profile 主键,便于区分

    def test_tags_pool(self):
        """标签池接口返回全部可选标签。

        参数说明:
            无。
        """
        self.login(self.user)
        resp = self.client.get("/api/v1/users/tags")
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(len(resp.json()), 10)


class ProfileUpdateTests(AuthMixin, APITestCase):
    """编辑资料:局部更新、昵称变化才同步 IM、未满 18 与各类非法输入。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.ProfileUpdateTests``

    备注信息:
        IM 同步挂在 ``transaction.on_commit`` 上,必须包在
        ``captureOnCommitCallbacks(execute=True)`` 里回调才会真跑。
    """

    def setUp(self):
        """建账号并登录,记下我的资料地址。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``

        备注信息:
            ``self.url`` 指向 ``PATCH /api/v1/users/me``,各用例复用。
        """
        self.user = User.objects.create_user(phone="13800138000")
        self.login(self.user)
        self.url = "/api/v1/users/me"

    def _full_profile(self, **overrides):
        """拼一份完整的资料提交体。

        参数说明:
            **overrides: 需要覆盖的字段。

        返回参数:
            可直接作为 PATCH body 的字典。

        使用示例:
            ``self._full_profile(city="北京")``

        备注信息:
            只拼提交体不落库,默认值已填满所有必填项,缺的字段由用例覆盖补上。
        """
        data = {
            "nickname": "小明",
            "gender": "male",
            "birthday": "2000-01-01",
            "city": "上海",
            "bio": "喜欢音乐",
        }
        data.update(overrides)
        return data

    def test_toggle_visits_hidden(self):
        """隐身开关可打开,响应与库内都生效。

        参数说明:
            无。
        """
        resp = self.client.patch(self.url, {"visits_hidden": True}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["visits_hidden"])
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.visits_hidden)

    def test_visits_hidden_defaults_false_in_me(self):
        """我的资料里隐身开关默认关闭。

        参数说明:
            无。
        """
        self.assertFalse(self.client.get(self.url).json()["visits_hidden"])

    @patch("im.tasks.sync_profile.delay")
    def test_update_fields(self, delay):
        """整体更新资料:昵称、年龄换算、标签回填都生效,缺照片仍算未完善。

        参数说明:
            无。
        """
        tag = Tag.objects.first()
        resp = self.client.patch(self.url, {**self._full_profile(), "tag_ids": [tag.id]}, format="json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["nickname"], "小明")
        self.assertEqual(data["age"], calculate_age(date(2000, 1, 1)))
        self.assertEqual([t["id"] for t in data["tags"]], [tag.id])
        self.assertEqual(data["status"], "incomplete")   # 还差照片

    @patch("im.tasks.sync_profile.delay")
    def test_partial_update_keeps_other_fields(self, delay):
        """局部更新只改传了的字段,其余字段保持原值。

        参数说明:
            无。
        """
        self.client.patch(self.url, {"nickname": "小明"}, format="json")
        resp = self.client.patch(self.url, {"city": "北京"}, format="json")
        self.assertEqual(resp.json()["nickname"], "小明")
        self.assertEqual(resp.json()["city"], "北京")

    @patch("im.tasks.sync_profile.delay")
    def test_patch_nickname_triggers_im_sync(self, delay):
        """昵称真的变了才在提交后入队 IM 同步,参数是账号 id 与 ``nick``。

        参数说明:
            无。
        """
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.patch(self.url, {"nickname": "新名字"}, format="json")
        self.assertEqual(resp.status_code, 200)
        delay.assert_called_once_with(self.user.id, "nick")

    @patch("im.tasks.sync_profile.delay")
    def test_patch_same_nickname_no_sync(self, delay):
        """昵称没变化不重复入队 IM 同步,连改两次只入队一次。

        参数说明:
            无。
        """
        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(self.url, {"nickname": "小明"}, format="json")
            self.client.patch(self.url, {"nickname": "小明"}, format="json")
        self.assertEqual(delay.call_count, 1)   # 只有第一次实际变化时同步

    @patch("im.tasks.sync_profile.delay")
    def test_patch_other_field_no_sync(self, delay):
        """只改非昵称字段不触发 IM 同步。

        参数说明:
            无。
        """
        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(self.url, {"city": "杭州"}, format="json")
        delay.assert_not_called()

    def test_underage_rejected_and_not_saved(self):
        """未满 18 的生日被拒 400,且不落库。

        参数说明:
            无。
        """
        too_young = f"{timezone.localdate().year - 17}-01-01"
        resp = self.client.patch(self.url, {"birthday": too_young}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIsNone(Profile.objects.get(user=self.user).birthday)

    def test_blocked_word_in_nickname_rejected(self):
        """昵称含违禁词返回 400 并带中文提示。

        参数说明:
            无。
        """
        resp = self.client.patch(self.url, {"nickname": "代开发票找我"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("message", resp.json())

    def test_unknown_tag_rejected(self):
        """不存在的标签 id 返回 400。

        参数说明:
            无。
        """
        resp = self.client.patch(self.url, {"tag_ids": [999999]}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_invalid_gender_rejected(self):
        """非法性别取值返回 400。

        参数说明:
            无。
        """
        resp = self.client.patch(self.url, {"gender": "alien"}, format="json")
        self.assertEqual(resp.status_code, 400)


PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class PhotoTests(AuthMixin, APITestCase):
    """照片:开发期上传即过审、过审同步头像、上限与格式、删除与状态流转。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.PhotoTests``

    备注信息:
        整类切临时 ``MEDIA_ROOT``,图片只写临时目录,不污染真实 media/。
    """

    def setUp(self):
        """准备临时 MEDIA_ROOT、账号与上传地址。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``

        备注信息:
            图片一律写临时目录并在用例结束递归删除,不污染真实 media/。
        """
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir)   # 测试图片必须写入临时目录,不能落到真实 media/
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(phone="13800138000")
        self.login(self.user)
        self.url = "/api/v1/users/me/photos"

    def upload(self, name="a.png", content=PNG_1PX, content_type="image/png"):
        """上传一张图片到相册。

        参数说明:
            name: 文件名。
            content: 文件字节内容。
            content_type: MIME 类型。

        返回参数:
            DRF 测试客户端的响应对象。

        使用示例:
            ``self.upload(name="b.png")``

        备注信息:
            走 multipart 上传;默认传 1x1 PNG,换文件名即可造出多张照片。
        """
        return self.client.post(self.url, {"file": SimpleUploadedFile(name, content, content_type=content_type)},
                                format="multipart")

    def fill_profile(self):
        """补全资料(会触发昵称同步任务,测试里挡掉)。

        参数说明:
            无。

        返回参数:
            PATCH 资料接口的响应对象。

        使用示例:
            ``self.fill_profile()``

        备注信息:
            补全资料会改昵称,故 ``im.tasks.sync_profile.delay`` 用 patch 挡掉,避免真入队。
        """
        # 补全资料会改昵称 → 触发 IM 同步任务,测试里一律挡掉
        with patch("im.tasks.sync_profile.delay"):
            return self.client.patch("/api/v1/users/me", {
                "nickname": "小明", "gender": "male", "birthday": "2000-01-01",
                "city": "上海", "bio": "喜欢音乐",
            }, format="json")

    def test_upload_auto_approved_in_dev(self):
        """开发期上传即过审,返回带绝对地址的照片。

        参数说明:
            无。
        """
        resp = self.upload()
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["status"], "approved")
        self.assertTrue(data["url"].startswith("http://testserver/media/"))

    @patch("im.tasks.sync_profile.delay")
    def test_upload_approved_photo_syncs_im_avatar(self, delay):
        """过审照片在提交后入队 IM 头像同步,参数是账号 id 与 ``avatar``。

        参数说明:
            无。
        """
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.upload()
        self.assertEqual(resp.status_code, 201)
        delay.assert_called_once_with(self.user.id, "avatar")

    def test_upload_rejects_non_image(self):
        """非图片文件返回 400。

        参数说明:
            无。
        """
        resp = self.upload(name="a.txt", content=b"not an image", content_type="text/plain")
        self.assertEqual(resp.status_code, 400)

    def test_upload_rejects_gif(self):
        """资料图同样只接受 jpg/png/webp(L5)。

        参数说明:
            无。
        """
        buffer = io.BytesIO()
        Image.new("RGB", (1, 1), "red").save(buffer, "GIF")
        resp = self.upload(name="a.gif", content=buffer.getvalue(), content_type="image/gif")
        self.assertEqual(resp.status_code, 400)

    def test_upload_strips_exif(self):
        """资料图重编码后不保留原始 EXIF(M4)。

        参数说明:
            无。
        """
        exif = Image.Exif()
        exif[0x010F] = "TestCamera"
        buffer = io.BytesIO()
        Image.new("RGB", (2, 2), "red").save(buffer, "JPEG", exif=exif)
        resp = self.upload(name="a.jpg", content=buffer.getvalue(), content_type="image/jpeg")
        self.assertEqual(resp.status_code, 201, resp.json())
        with Image.open(Photo.objects.get().file.path) as stored:
            self.assertNotIn(0x010F, stored.getexif())

    def test_upload_limit_six(self):
        """相册上限 6 张:前 6 张 201,第 7 张 400。

        参数说明:
            无。
        """
        for i in range(6):
            self.assertEqual(self.upload(name=f"{i}.png").status_code, 201)
        self.assertEqual(self.upload(name="7.png").status_code, 400)

    def test_upload_throttled(self):
        """照片上传按用户限流,超限 429(M7)。

        参数说明:
            无。
        """
        from .throttles import PhotoUploadThrottle

        cache.clear()
        with patch.object(PhotoUploadThrottle, "rate", "2/hour", create=True):
            self.assertEqual(self.upload().status_code, 201)
            self.assertEqual(self.upload().status_code, 201)
            self.assertEqual(self.upload().status_code, 429)

    def test_delete_own_photo_removes_file(self):
        """删自己的照片返回 204,照片行不再存在。

        参数说明:
            无。
        """
        photo_id = self.upload().json()["id"]
        resp = self.client.delete(f"{self.url}/{photo_id}")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Photo.objects.filter(id=photo_id).exists())

    def test_cannot_delete_others_photo(self):
        """删别人的照片返回 404,不泄露照片是否存在。

        参数说明:
            无。
        """
        other = User.objects.create_user(phone="13900139000")
        photo = Photo.objects.create(user=other, file="photos/x.png")
        resp = self.client.delete(f"{self.url}/{photo.id}")
        self.assertEqual(resp.status_code, 404)

    def test_status_becomes_complete_with_approved_photo(self):
        """资料填全且有过审照片后,状态从 incomplete 转 complete。

        参数说明:
            无。
        """
        self.fill_profile()
        self.assertEqual(self.client.get("/api/v1/users/me").json()["status"], "incomplete")
        self.upload()
        self.assertEqual(self.client.get("/api/v1/users/me").json()["status"], "complete")

    def test_status_returns_to_incomplete_after_photo_delete(self):
        """删掉唯一过审照片后,状态退回 incomplete。

        参数说明:
            无。
        """
        self.fill_profile()
        photo_id = self.upload().json()["id"]
        self.client.delete(f"{self.url}/{photo_id}")
        self.assertEqual(self.client.get("/api/v1/users/me").json()["status"], "incomplete")

    @override_settings(AUTO_APPROVE=False)
    def test_pending_photo_when_auto_approve_off(self):
        """``AUTO_APPROVE=False`` 时上传进待审,资料仍算未完善。

        参数说明:
            无。
        """
        self.fill_profile()
        self.assertEqual(self.upload().json()["status"], "pending")
        self.assertEqual(self.client.get("/api/v1/users/me").json()["status"], "incomplete")

    def test_upload_records_file_bytes(self):
        """上传后把重编码字节数记进 ``bytes``,供配额统计(M7)。

        参数说明:
            无。
        """
        self.assertEqual(self.upload().status_code, 201)
        photo = Photo.objects.get()
        self.assertEqual(photo.bytes, photo.file.size)

    def test_upload_rejected_when_quota_exceeded(self):
        """配额已满时上传 413/41301,且不建行、不落盘(M7)。

        参数说明:
            无。
        """
        self.assertEqual(self.upload().status_code, 201)
        used = Photo.objects.get().bytes
        with self.settings(USER_STORAGE_QUOTA_BYTES=used):
            resp = self.upload(name="b.png")
        self.assertEqual(resp.status_code, 413)
        self.assertEqual(resp.json()["code"], 41301)
        self.assertEqual(Photo.objects.count(), 1)

    def test_quota_zero_disables_limit(self):
        """``USER_STORAGE_QUOTA_BYTES=0`` 表示关闭配额(本地手测口径)。

        参数说明:
            无。
        """
        with self.settings(USER_STORAGE_QUOTA_BYTES=0):
            self.assertEqual(self.upload().status_code, 201)


class ProfileVoiceTests(AuthMixin, APITestCase):
    """资料语音自我介绍(批次 R):上传/覆盖/删除、30 秒上限、签名 URL、配额不落盘。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.ProfileVoiceTests``

    备注信息:
        实测时长与转码靠 ``im.voice`` 的 ``ffmpeg_available`` / ``_probe_ms`` / ``_transcode``
        三个打桩控制,用例不真解码音频,也不需要装 ffmpeg。
    """

    def setUp(self):
        """准备临时 MEDIA_ROOT、清缓存、登录并记下语音地址。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``

        备注信息:
            清缓存是为了抹掉上传限流计数,否则用例之间会互相触发 429。
        """
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir)
        override.enable()
        self.addCleanup(override.disable)
        cache.clear()
        self.user = User.objects.create_user(phone="13800138000")
        self.login(self.user)
        self.url = "/api/v1/users/me/voice"

    def upload(self, content=b"fake-m4a", name="a.m4a", content_type="audio/mp4"):
        """上传一段资料语音。

        参数说明:
            content: 文件字节。
            name: 文件名。
            content_type: MIME 类型。

        返回参数:
            DRF 测试客户端的响应对象。

        使用示例:
            ``self.upload(name="b.m4a")``

        备注信息:
            走 multipart 上传;内容默认是假字节,真实时长由 ``im.voice._probe_ms`` 打桩决定。
        """
        return self.client.post(
            self.url,
            {"file": SimpleUploadedFile(name, content, content_type=content_type)},
            format="multipart")

    def voice_files(self):
        """列出媒体目录里已落盘的语音文件。

        参数说明:
            无。

        返回参数:
            语音文件的 ``Path`` 列表(覆盖上传的断言用「只剩一个」)。

        使用示例:
            ``self.voice_files()``

        备注信息:
            只看 ``voices/`` 子目录下的 ``*.m4a``;目录还不存在时返回空列表。
        """
        root = Path(self.media_dir) / "voices"
        return sorted(root.rglob("*.m4a")) if root.exists() else []

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"transcoded"))
    @patch("im.voice._probe_ms", return_value=3000)
    def test_upload_three_seconds_returns_public_url(self, _probe, _transcode, _ffmpeg):
        """3 秒语音:201 + 公开绝对地址(无 query)+ 实测时长,文件与行都落库。

        参数说明:
            无。
        """
        resp = self.upload()
        self.assertEqual(resp.status_code, 201, resp.json())
        data = resp.json()
        self.assertTrue(data["url"].startswith("http://testserver/media/voices/"))
        self.assertNotIn("?", data["url"])
        self.assertEqual(data["duration_ms"], 3000)
        record = ProfileVoice.objects.get()
        self.assertEqual(record.profile.user_id, self.user.id)
        self.assertEqual(record.bytes, len(b"transcoded"))
        self.assertRegex(record.file.name, r"^voices/\d{4}/\d{2}/\d+-[0-9a-f]{32}\.m4a$")
        self.assertTrue(record.file.storage.exists(record.file.name))

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"transcoded"))
    @patch("im.voice._probe_ms", return_value=31000)
    def test_rejects_over_thirty_seconds(self, _probe, _transcode, _ffmpeg):
        """31 秒 → 400,提示里写明上限是 30 秒,且不落库不落盘。

        参数说明:
            无。
        """
        resp = self.upload()
        self.assertEqual(resp.status_code, 400)
        self.assertIn("30 秒", resp.json()["message"])
        self.assertEqual(ProfileVoice.objects.count(), 0)
        self.assertEqual(self.voice_files(), [])

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"transcoded"))
    @patch("im.voice._probe_ms", return_value=3000)
    def test_second_upload_replaces_and_deletes_old_file(self, _probe, _transcode, _ffmpeg):
        """重复上传 = 覆盖:库里仍只有一条,旧文件已从磁盘删除。

        参数说明:
            无。
        """
        self.assertEqual(self.upload().status_code, 201)
        first = ProfileVoice.objects.get().file.name
        self.assertEqual(self.upload(content=b"second").status_code, 201)
        self.assertEqual(ProfileVoice.objects.count(), 1)
        current = ProfileVoice.objects.get()
        self.assertNotEqual(current.file.name, first)
        self.assertFalse(default_storage.exists(first))
        self.assertEqual(len(self.voice_files()), 1)

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"transcoded"))
    @patch("im.voice._probe_ms", return_value=3000)
    def test_me_and_public_profile_expose_voice_url(self, _probe, _transcode, _ffmpeg):
        """``GET /users/me`` 与他人资料卡都返回 ``voice``,URL 是公开绝对地址。

        参数说明:
            无。
        """
        self.assertEqual(self.upload().status_code, 201)
        mine = self.client.get("/api/v1/users/me").json()["voice"]
        self.assertIsNotNone(mine)
        self.assertEqual(mine["duration_ms"], 3000)

        viewer = User.objects.create_user(phone="13900139000")
        self.login(viewer)
        public = self.client.get(f"/api/v1/users/{self.user.id}")
        self.assertEqual(public.status_code, 200, public.json())
        voice = public.json()["voice"]
        self.assertEqual(voice["duration_ms"], 3000)
        for url in (mine["url"], voice["url"]):
            # 与照片完全同口径:公开绝对地址、**不带任何 query**。语音落在
            # /media/voices/,nginx 是裸静态直出,签 e/s 也没有人校验,所以干脆不签。
            self.assertTrue(url.startswith("http://testserver/media/voices/"))
            self.assertNotIn("?", url)

    def test_voice_is_null_without_upload(self):
        """没录过语音时字段是 ``null``,而不是报错或空对象。

        参数说明:
            无。
        """
        self.assertIsNone(self.client.get("/api/v1/users/me").json()["voice"])

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"transcoded"))
    @patch("im.voice._probe_ms", return_value=3000)
    def test_delete_is_idempotent_and_removes_file(self, _probe, _transcode, _ffmpeg):
        """DELETE 两次都 204;之后 ``voice`` 为 ``null`` 且磁盘文件已删。

        参数说明:
            无。
        """
        self.assertEqual(self.upload().status_code, 201)
        name = ProfileVoice.objects.get().file.name
        self.assertEqual(self.client.delete(self.url).status_code, 204)
        self.assertEqual(self.client.delete(self.url).status_code, 204)
        self.assertEqual(ProfileVoice.objects.count(), 0)
        self.assertFalse(default_storage.exists(name))
        self.assertIsNone(self.client.get("/api/v1/users/me").json()["voice"])

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"transcoded"))
    @patch("im.voice._probe_ms", return_value=3000)
    def test_quota_exceeded_returns_413_and_writes_nothing(self, _probe, _transcode, _ffmpeg):
        """配额超限:413 + ``41301``,既不建行**也不落盘**(检查在 ``file.save()`` 之前)。

        参数说明:
            无。
        """
        with self.settings(USER_STORAGE_QUOTA_BYTES=1):
            resp = self.upload()
        self.assertEqual(resp.status_code, 413)
        self.assertEqual(resp.json()["code"], 41301)
        self.assertEqual(ProfileVoice.objects.count(), 0)
        self.assertEqual(self.voice_files(), [])

    @patch("im.voice.ffmpeg_available", return_value=False)
    def test_returns_503_without_ffmpeg(self, _ffmpeg):
        """服务器没装 ffmpeg/ffprobe:503 + ``50302``(不新增业务码)。

        参数说明:
            无。
        """
        resp = self.upload()
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["code"], 50302)

    def test_rejects_non_audio(self):
        """传图片冒充语音返回 400。

        参数说明:
            无。
        """
        resp = self.upload(name="a.png", content=b"png", content_type="image/png")
        self.assertEqual(resp.status_code, 400)

    def test_requires_auth(self):
        """未登录读资料与上传语音都返回 401。

        参数说明:
            无。
        """
        self.client.credentials()
        self.assertEqual(self.client.get("/api/v1/users/me").status_code, 401)
        self.assertEqual(self.upload().status_code, 401)

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"x"))
    @patch("im.voice._probe_ms", return_value=3000)
    def test_voice_does_not_affect_profile_status(self, _probe, _transcode, _ffmpeg):
        """回归:语音**不进**「资料完善」判定 —— 有语音不改变状态,没有也不会退化。

        参数说明:
            无。
        """
        profile = services.get_profile(self.user)
        before = profile.status
        self.assertEqual(self.upload().status_code, 201)
        profile.refresh_from_db()
        self.assertEqual(profile.status, before)
        self.assertIn("nickname", profile.missing_fields())
        self.assertNotIn("voice", profile.missing_fields())

    @patch("users.throttles.ProfileVoiceThrottle.get_rate", return_value="1/hour")
    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"x"))
    @patch("im.voice._probe_ms", return_value=3000)
    def test_upload_is_throttled(self, _rate, _probe, _transcode, _ffmpeg):
        """上传按账号限流(默认 10 次/小时)。

        参数说明:
            无。
        """
        cache.clear()
        self.assertEqual(self.upload().status_code, 201)
        self.assertEqual(self.upload().status_code, 429)


class StorageUsageTests(TestCase):
    """存储用量口径:五类媒体相加,已删除/已过期的不计,按账号隔离(M7)。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.StorageUsageTests``

    备注信息:
        只比库内 ``bytes`` 求和,不写磁盘。
    """

    def setUp(self):
        """建一个不带资料的账号。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``

        备注信息:
            用量口径只看库内 ``bytes`` 求和,用例不需要真的写磁盘。
        """
        self.user = User.objects.create_user(phone="13800138000")

    def _chat_image(self, size, status=ChatImageStatus.VISIBLE):
        """造一条聊天图元数据(不写磁盘,只落 ``bytes``)。

        参数说明:
            size: 字节数。
            status: 图片状态。

        返回参数:
            新建的 ``ChatImage``。

        使用示例:
            ``self._chat_image(30)``

        备注信息:
            默认 ``VISIBLE``;传 ``EXPIRED`` / ``DELETED`` 可验证「不计入用量」的口径。
        """
        return ChatImage.objects.create(
            owner=self.user, file="chat/a.jpg", thumb="chat/a_t.jpg",
            width=1, height=1, bytes=size, status=status)

    def test_usage_sums_all_media_types(self):
        """用量是五类媒体字节数之和:资料图、动态图、聊天图、聊天语音、资料语音。

        参数说明:
            无。
        """
        Photo.objects.create(user=self.user, file="photos/a.png", bytes=10)
        post = Post.objects.create(author=self.user, text="x")
        PostImage.objects.create(post=post, file="posts/a.png", bytes=20)
        self._chat_image(30)
        ChatVoice.objects.create(owner=self.user, file="chat/voices/a.m4a",
                                 duration_ms=1000, bytes=40)
        ProfileVoice.objects.create(profile=services.get_profile(self.user),
                                    file="voices/a.m4a", duration_ms=1000, bytes=50)
        self.assertEqual(storage.usage_bytes(self.user.id), 150)

    def test_expired_or_deleted_media_not_counted(self):
        """已过期与已删除的媒体不计入用量。

        参数说明:
            无。
        """
        self._chat_image(30, status=ChatImageStatus.EXPIRED)
        self._chat_image(40, status=ChatImageStatus.DELETED)
        ChatVoice.objects.create(owner=self.user, file="chat/voices/a.m4a",
                                 duration_ms=1000, bytes=50,
                                 status=ChatVoiceStatus.EXPIRED)
        self.assertEqual(storage.usage_bytes(self.user.id), 0)

    def test_usage_is_per_user(self):
        """用量按账号隔离:别人的占用不算到我头上。

        参数说明:
            无。
        """
        other = User.objects.create_user(phone="13900139000")
        Photo.objects.create(user=other, file="photos/b.png", bytes=99)
        self.assertEqual(storage.usage_bytes(self.user.id), 0)


class MediaCommandTests(TestCase):
    """媒体管理命令:字节回填、孤儿清理、磁盘报表告警(M7)。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.MediaCommandTests``

    备注信息:
        命令按 ``settings.MEDIA_ROOT`` 扫盘,故整类切到临时目录。
    """

    def setUp(self):
        """准备临时 MEDIA_ROOT 与账号。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``

        备注信息:
            管理命令按 ``settings.MEDIA_ROOT`` 扫盘,故整体切到临时目录并在用例结束删除。
        """
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(phone="13800138000")

    def _write(self, relative, content=b"abc"):
        """在临时 MEDIA_ROOT 下写一个文件。

        参数说明:
            relative: 相对 ``MEDIA_ROOT`` 的路径。
            content: 文件内容。

        返回参数:
            写入后的绝对路径。

        使用示例:
            ``self._write("photos/a.png", b"12345")``

        备注信息:
            父目录不存在时自动创建,便于一次造出多层目录。
        """
        path = Path(settings.MEDIA_ROOT) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_media_bytes_backfill_fills_sizes(self):
        """``media_bytes_backfill`` 按磁盘实际大小回填 ``bytes``。

        参数说明:
            无。
        """
        photo = Photo.objects.create(user=self.user, file="photos/a.png")
        self._write("photos/a.png", b"12345")
        call_command("media_bytes_backfill", stdout=StringIO())
        photo.refresh_from_db()
        self.assertEqual(photo.bytes, 5)

    def test_media_bytes_backfill_dry_run_does_not_write(self):
        """``--dry-run`` 只统计不写库,``bytes`` 仍是 0。

        参数说明:
            无。
        """
        Photo.objects.create(user=self.user, file="photos/a.png")
        self._write("photos/a.png", b"12345")
        call_command("media_bytes_backfill", "--dry-run", stdout=StringIO())
        self.assertEqual(Photo.objects.get().bytes, 0)

    def test_media_cleanup_deletes_only_orphans_with_apply(self):
        """``media_cleanup`` 默认只演练,``--apply`` 才删孤儿文件,库里有记录的保留。

        参数说明:
            无。
        """
        Photo.objects.create(user=self.user, file="photos/keep.png")
        kept = self._write("photos/keep.png")
        orphan = self._write("photos/orphan.png")
        old = time.time() - 48 * 3600
        os.utime(orphan, (old, old))

        call_command("media_cleanup", stdout=StringIO())
        self.assertTrue(orphan.exists())          # dry-run 不删

        call_command("media_cleanup", "--apply", stdout=StringIO())
        self.assertFalse(orphan.exists())
        self.assertTrue(kept.exists())

    def test_media_disk_report_fails_over_threshold(self):
        """目录占用超过 ``--fail-over`` 阈值时命令以非零状态退出。

        参数说明:
            无。
        """
        self._write("photos/big.bin", b"x" * (2 * 1024 * 1024))
        with self.assertRaises(SystemExit):
            call_command("media_disk_report", "--warn-mb", "1", "--fail-over",
                         stdout=StringIO(), stderr=StringIO())


class PreferenceTests(AuthMixin, APITestCase):
    """择偶偏好:默认值、更新、区间与年龄下限校验、目标性别为空表示不限。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.PreferenceTests``

    备注信息:
        偏好行随资料懒创建,从没设置过时接口返回默认值而不是 404。
    """

    def setUp(self):
        """建账号并登录,记下偏好地址。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``

        备注信息:
            ``self.url`` 指向 ``/api/v1/users/me/preference``,各用例复用。
        """
        self.user = User.objects.create_user(phone="13800138000")
        self.login(self.user)
        self.url = "/api/v1/users/me/preference"

    def test_defaults(self):
        """未设置过时返回默认偏好:不限性别、18 到 99 岁、城市空串。

        参数说明:
            无。
        """
        data = self.client.get(self.url).json()
        self.assertIsNone(data["target_gender"])
        self.assertEqual(data["age_min"], 18)
        self.assertEqual(data["age_max"], 99)
        self.assertEqual(data["city"], "")

    def test_update(self):
        """更新偏好后读回一致。

        参数说明:
            无。
        """
        resp = self.client.patch(self.url, {"target_gender": "female", "age_min": 22,
                                            "age_max": 30, "city": "上海"}, format="json")
        self.assertEqual(resp.status_code, 200)
        data = self.client.get(self.url).json()
        self.assertEqual(data["target_gender"], "female")
        self.assertEqual(data["age_min"], 22)
        self.assertEqual(data["age_max"], 30)
        self.assertEqual(data["city"], "上海")

    def test_invalid_range_rejected(self):
        """年龄下限大于上限返回 400。

        参数说明:
            无。
        """
        resp = self.client.patch(self.url, {"age_min": 40, "age_max": 30}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_underage_range_rejected(self):
        """年龄下限低于 18 返回 400。

        参数说明:
            无。
        """
        resp = self.client.patch(self.url, {"age_min": 17}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_target_gender_null_means_any(self):
        """``target_gender`` 传 null 表示不限性别,读回也是 null。

        参数说明:
            无。
        """
        self.client.patch(self.url, {"target_gender": "male"}, format="json")
        resp = self.client.patch(self.url, {"target_gender": None}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["target_gender"])


class PhotoAdminActionTests(TestCase):
    """审核台批量动作:改照片状态,并重算用户的「资料完善」状态。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.PhotoAdminActionTests``

    备注信息:
        走 admin 的批量动作接口,断言 302 重定向与库内最终状态。
    """

    def setUp(self):
        """建运营账号、被审用户与一张过审照片,并以运营身份登录 admin。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``

        备注信息:
            用 ``force_login`` 直接登录超管,不跑 admin 登录页与 TOTP。
        """
        self.staff = User.objects.create_superuser(phone="13700137000", password="pw")
        self.user = User.objects.create_user(phone="13900139000")
        self.profile = Profile.objects.create(
            user=self.user, nickname="小红", gender="female", birthday="2000-01-01",
            city="上海", bio="你好", status=ProfileStatus.COMPLETE)
        self.photo = Photo.objects.create(user=self.user, file="photos/x.png",
                                          status=PhotoStatus.APPROVED)
        self.client.force_login(self.staff)

    def _run_action(self, action, *photos):
        """通过 admin 的批量动作接口对指定照片执行审核。

        参数说明:
            action: admin action 名称(``approve_photos`` / ``reject_photos``)。
            *photos: 要处理的照片对象。

        返回参数:
            admin 接口的响应对象(动作为重定向,状态码 302)。

        使用示例:
            ``self._run_action("approve_photos", self.photo)``

        备注信息:
            admin 批量动作走 ``POST /admin/users/photo/``,靠 ``action`` 与 ``_selected_action`` 两个表单字段驱动。
        """
        return self.client.post("/admin/users/photo/", {
            "action": action,
            "_selected_action": [p.pk for p in photos],
        })

    def test_reject_action_marks_photo_and_profile_incomplete(self):
        """驳回动作把照片置 ``rejected``,并把资料状态重算回未完善。

        参数说明:
            无。
        """
        resp = self._run_action("reject_photos", self.photo)
        self.assertEqual(resp.status_code, 302)
        self.photo.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.photo.status, PhotoStatus.REJECTED)
        self.assertEqual(self.profile.status, ProfileStatus.INCOMPLETE)

    def test_approve_action_completes_profile_again(self):
        """通过动作把照片置 ``approved``,资料重新变回完善。

        参数说明:
            无。
        """
        Photo.objects.filter(pk=self.photo.pk).update(status=PhotoStatus.PENDING)
        Profile.objects.filter(pk=self.profile.pk).update(status=ProfileStatus.INCOMPLETE)
        self._run_action("approve_photos", self.photo)
        self.photo.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.photo.status, PhotoStatus.APPROVED)
        self.assertEqual(self.profile.status, ProfileStatus.COMPLETE)

    def test_action_records_reviewer_and_time(self):
        """审核动作为照片记录审核人与审核时间。

        参数说明:
            无。
        """
        self._run_action("approve_photos", self.photo)
        self.photo.refresh_from_db()
        self.assertEqual(self.photo.reviewed_by, self.staff)
        self.assertIsNotNone(self.photo.reviewed_at)


class PublicProfileTests(AuthMixin, APITestCase):
    """他人资料卡:只返回公开字段、封禁与拉黑下的可见性、404 与鉴权。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.PublicProfileTests``

    备注信息:
        对方名下有两张照片(一张过审、一张待审),用来验证只暴露过审那张。
    """

    def setUp(self):
        """建我、对方与他人资料卡(一张过审照片 + 一张待审)。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``

        备注信息:
            待审那张用于验证资料卡只返回过审照片。
        """
        self.me = User.objects.create_user(phone="13800138000")
        self.login(self.me)
        self.other = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.other, nickname="小红", gender="female",
                               birthday="1998-01-01", city="上海", bio="喜欢爬山",
                               status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=self.other, file="photos/a.png", status=PhotoStatus.APPROVED)
        Photo.objects.create(user=self.other, file="photos/b.png", status=PhotoStatus.PENDING)

    def _get(self):
        """请求他人资料卡。

        参数说明:
            无。

        返回参数:
            DRF 测试客户端的响应对象。

        使用示例:
            ``self._get()``

        备注信息:
            目标固定是 ``self.other``;要看别的账号时直接拼 URL 请求。
        """
        return self.client.get(f"/api/v1/users/{self.other.id}")

    def test_returns_public_fields_only(self):
        """他人资料卡只返回公开字段,手机号、生日、偏好与缺失项都不出现。

        参数说明:
            无。
        """
        data = self._get().json()
        self.assertEqual(data["user_id"], self.other.id)
        self.assertEqual(data["nickname"], "小红")
        self.assertEqual(data["age"], calculate_age(date(1998, 1, 1)))
        self.assertEqual(len(data["photos"]), 1)          # 只有过审那张
        for hidden in ("phone", "birthday", "preference", "missing_fields"):
            self.assertNotIn(hidden, data)

    def test_public_profile_hides_visits_hidden(self):
        """他人资料卡不暴露对方的隐身开关。

        参数说明:
            无。
        """
        Profile.objects.filter(user=self.other).update(visits_hidden=True)
        self.assertNotIn("visits_hidden", self._get().json())

    def test_heavy_banned_target_is_invisible(self):
        """重封禁的目标返回 404,等同于不存在。

        参数说明:
            无。
        """
        Profile.objects.filter(user=self.other).update(status=ProfileStatus.BANNED_HEAVY)
        self.assertEqual(self._get().status_code, 404)

    def test_light_banned_target_still_visible(self):
        """轻封禁的目标资料卡仍可见。

        参数说明:
            无。
        """
        Profile.objects.filter(user=self.other).update(status=ProfileStatus.BANNED_LIGHT)
        self.assertEqual(self._get().status_code, 200)

    def test_blocked_relationship_hides_both_ways(self):
        """拉黑双向都不可见:我拉黑对方、对方拉黑我,两种情形都 404。

        参数说明:
            无。
        """
        Block.objects.create(blocker=self.me, blocked=self.other)
        self.assertEqual(self._get().status_code, 404)
        Block.objects.all().delete()
        Block.objects.create(blocker=self.other, blocked=self.me)
        self.assertEqual(self._get().status_code, 404)

    def test_unknown_user_returns_404(self):
        """不存在的用户返回 404。

        参数说明:
            无。
        """
        self.assertEqual(self.client.get("/api/v1/users/999999").status_code, 404)

    def test_requires_auth(self):
        """未登录读他人资料卡返回 401。

        参数说明:
            无。
        """
        self.client.credentials()
        self.assertEqual(self._get().status_code, 401)


class SharedTagsTests(AuthMixin, APITestCase):
    """共同标签(``shared_tags``):交集口径、无交集兜底、查询条数不随标签数增长。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.SharedTagsTests``

    备注信息:
        查询条数守卫用 ``CaptureQueriesContext`` 对比「标签少」与「标签多」两种情形。
    """

    def setUp(self):
        """建我与对方(资料完善 + 过审照片),取前 4 个标签备用。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``

        备注信息:
            标签按 id 升序取,用例里靠下标挑不同组合。
        """
        self.me = User.objects.create_user(phone="13800138001")
        self.login(self.me)
        self.other = User.objects.create_user(phone="13900139001")
        Profile.objects.create(user=self.other, nickname="小红", gender="female",
                               birthday="1998-01-01", city="上海", bio="喜欢爬山",
                               status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=self.other, file="photos/a.png", status=PhotoStatus.APPROVED)
        self.tags = list(Tag.objects.order_by("id")[:4])

    def _set_tags(self, user, tags):
        """给指定用户设置标签。

        参数说明:
            user: 目标用户。
            tags: 标签对象序列。

        返回参数:
            无返回值。

        使用示例:
            ``self._set_tags(self.me, [self.tags[0]])``

        备注信息:
            整体覆盖资料上的标签集合,不是追加;资料不存在时由 ``services.get_profile`` 懒创建。
        """
        services.get_profile(user).tags.set(tags)

    def _shared_tags(self):
        """请求他人资料卡并取出 ``shared_tags``。

        参数说明:
            无。

        返回参数:
            ``shared_tags`` 列表。

        使用示例:
            ``self._shared_tags()``

        备注信息:
            顺带断言 200,失败时把响应前 200 字节放进断言消息,便于定位。
        """
        response = self.client.get(f"/api/v1/users/{self.other.id}")
        self.assertEqual(response.status_code, 200, response.content[:200])
        return response.json()["shared_tags"]

    def test_returns_intersection_only(self):
        """只返回交集,且按标签 id 升序。

        参数说明:
            无。
        """
        self._set_tags(self.me, [self.tags[0], self.tags[2]])
        self._set_tags(self.other, [self.tags[1], self.tags[2], self.tags[0]])
        self.assertEqual([tag["id"] for tag in self._shared_tags()],
                         [self.tags[0].id, self.tags[2].id])

    def test_empty_when_no_overlap(self):
        """没有交集时是空数组,不是 404 也不是 null。

        参数说明:
            无。
        """
        self._set_tags(self.me, [self.tags[0]])
        self._set_tags(self.other, [self.tags[1]])
        self.assertEqual(self._shared_tags(), [])

    def test_empty_when_viewer_has_no_tags(self):
        """我没选标签时同样返回空数组(避免把对方的全部标签当成共同点)。

        参数说明:
            无。
        """
        self._set_tags(self.other, [self.tags[0], self.tags[1]])
        self.assertEqual(self._shared_tags(), [])

    def test_query_count_does_not_grow_with_tag_count(self):
        """共同标签只多一次 M2M 查询,不随标签数量线性增长(N+1 守卫)。

        参数说明:
            无。
        """
        self._set_tags(self.me, self.tags[:1])
        self._set_tags(self.other, [self.tags[0]])
        with CaptureQueriesContext(connection) as one_shared:
            self._shared_tags()
        self._set_tags(self.me, self.tags)
        self._set_tags(self.other, self.tags)
        with CaptureQueriesContext(connection) as many_shared:
            self._shared_tags()
        self.assertEqual(len(one_shared.captured_queries), len(many_shared.captured_queries))


class FollowStateTests(AuthMixin, APITestCase):
    """资料卡关注态:``is_followed`` 口径、粉丝/关注数、查询条数恒定。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.FollowStateTests``

    备注信息:
        查询条数守卫先预热一次请求,避开首次请求的一次性懒创建。
    """

    def setUp(self):
        """建我、对方与一个粉丝账号,对方资料置为完善。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``

        备注信息:
            粉丝账号只建资料不登录,用来造「关注对方的人」。
        """
        self.me = User.objects.create_user(phone="13800138002")
        self.login(self.me)
        self.other = User.objects.create_user(phone="13900139002")
        Profile.objects.create(user=self.other, nickname="小红", gender="female",
                               birthday="1998-01-01", city="上海", bio="喜欢爬山",
                               status=ProfileStatus.COMPLETE)
        self.fan = User.objects.create_user(phone="13700137002")
        Profile.objects.create(user=self.fan, nickname="粉丝", status=ProfileStatus.COMPLETE)

    def _state(self):
        """请求他人资料卡并取出三个关注态字段。

        参数说明:
            无。

        返回参数:
            ``(is_followed, follower_count, following_count)`` 三元组。

        使用示例:
            ``self._state()``

        备注信息:
            顺带断言 200,失败时把响应前 200 字节放进断言消息,便于定位。
        """
        response = self.client.get(f"/api/v1/users/{self.other.id}")
        self.assertEqual(response.status_code, 200, response.content[:200])
        data = response.json()
        return data["is_followed"], data["follower_count"], data["following_count"]

    def test_default_state_is_not_followed(self):
        """没人关注、我也没有关注时:三个字段都是默认值(不是缺字段)。

        参数说明:
            无。
        """
        self.assertEqual(self._state(), (False, 0, 0))

    def test_is_followed_true_after_following(self):
        """我关注对方后,资料卡的 ``is_followed`` 变真。

        参数说明:
            无。
        """
        Follow.objects.create(follower=self.me, followee=self.other)
        self.assertTrue(self._state()[0])

    def test_counts_are_directional(self):
        """粉丝数只算「关注对方的人」,关注数只算「对方关注的人」。

        参数说明:
            无。
        """
        Follow.objects.create(follower=self.me, followee=self.other)
        Follow.objects.create(follower=self.fan, followee=self.other)
        Follow.objects.create(follower=self.other, followee=self.fan)
        is_followed, follower_count, following_count = self._state()
        self.assertTrue(is_followed)
        self.assertEqual(follower_count, 2)     # 我 + 粉丝
        self.assertEqual(following_count, 1)    # 对方只关注了粉丝

    def test_query_count_does_not_grow_with_follow_count(self):
        """关注态固定只多一条聚合 SQL,不随关注数增长(N+1 守卫)。

        参数说明:
            无。
        """
        self._state()   # 预热:首次请求会触发偏好/访客等一次性懒创建
        with CaptureQueriesContext(connection) as few:
            self._state()
        for index in range(5):
            fan = User.objects.create_user(phone=f"1360013{index:04d}")
            Follow.objects.create(follower=fan, followee=self.other)
        with CaptureQueriesContext(connection) as many:
            self._state()
        self.assertEqual(len(few.captured_queries), len(many.captured_queries))


class ProfileScrapeMonitorTests(TestCase):
    """M2 抓取监控:同目标一小时只计一次、跨目标累加、超阈值告警、Redis 故障不影响响应。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.ProfileScrapeMonitorTests``

    备注信息:
        计数桶按当前时间戳划分,断言走相对口径,不写死具体小时。
    """

    def setUp(self):
        """清缓存,并算好当前小时桶的下标。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``

        备注信息:
            桶下标 = 当前时间戳整除 ``PROFILE_VIEW_TTL_SECONDS``,与 ``record_profile_view`` 内部口径一致。
        """
        cache.clear()
        self.addCleanup(cache.clear)
        self.bucket = int(time.time()) // services.PROFILE_VIEW_TTL_SECONDS

    def _count(self, viewer_id):
        """读该浏览者当前小时的计数。

        参数说明:
            viewer_id: 浏览者账号 id。

        返回参数:
            计数;没记录时为 ``None``。

        使用示例:
            ``self._count(1)``

        备注信息:
            键格式与 ``services`` 内部一致:``profile_view_count:<浏览者 id>:<桶>``。
        """
        return cache.get(f"profile_view_count:{viewer_id}:{self.bucket}")

    def test_same_target_counted_once_per_hour(self):
        """同一目标一小时内重复看只计一次。

        参数说明:
            无。
        """
        services.record_profile_view(1, 2)
        services.record_profile_view(1, 2)
        self.assertEqual(self._count(1), 1)

    def test_distinct_targets_accumulate(self):
        """看不同目标会累加计数。

        参数说明:
            无。
        """
        for target in (2, 3, 4):
            services.record_profile_view(1, target)
        self.assertEqual(self._count(1), 3)

    @override_settings(PROFILE_SCRAPE_ALERT_PER_HOUR=2)
    def test_threshold_logs_warning_once(self):
        """超过阈值只告警一次,不随每次浏览刷屏。

        参数说明:
            无。
        """
        with self.assertLogs("users.services", "WARNING") as logs:
            for target in (2, 3, 4, 5):
                services.record_profile_view(1, target)
        self.assertEqual(len(logs.records), 1)
        self.assertIn("疑似资料抓取", logs.records[0].getMessage())

    def test_cache_failure_is_swallowed(self):
        """计数写缓存失败被吞掉,不向上抛异常。

        参数说明:
            无。
        """
        with patch("users.services.cache.add", side_effect=RuntimeError("redis down")):
            services.record_profile_view(1, 2)   # 不抛异常即通过


class ProfileScrapeApiTests(AuthMixin, APITestCase):
    """看他人资料会写计数;接口本身不受计数失败影响。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.ProfileScrapeApiTests``

    备注信息:
        计数失败用 ``patch`` 造异常,断言接口仍返回 200。
    """

    def setUp(self):
        """建我(已登录)与对方资料卡,并清缓存。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``

        备注信息:
            清缓存避免上一个用例留下的计数干扰断言。
        """
        cache.clear()
        self.addCleanup(cache.clear)
        self.me = User.objects.create_user(phone="13800138001")
        self.login(self.me)
        self.other = User.objects.create_user(phone="13900139001")
        Profile.objects.create(user=self.other, nickname="小蓝", status=ProfileStatus.COMPLETE)

    def test_viewing_profile_writes_counter(self):
        """看他人资料卡会在当前小时桶里写入一次计数。

        参数说明:
            无。
        """
        self.client.get(f"/api/v1/users/{self.other.id}")
        bucket = int(time.time()) // services.PROFILE_VIEW_TTL_SECONDS
        self.assertEqual(cache.get(f"profile_view_count:{self.me.id}:{bucket}"), 1)

    def test_counter_failure_does_not_break_response(self):
        """计数写失败不影响资料卡响应,仍返回 200。

        参数说明:
            无。
        """
        with patch("users.services.cache.add", side_effect=RuntimeError("redis down")):
            self.assertEqual(self.client.get(f"/api/v1/users/{self.other.id}").status_code, 200)


class PresenceServiceTests(TestCase):
    """在线状态服务:写入即在线、窗口边界、未知用户、时区与 Redis 故障降级。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.PresenceServiceTests``

    备注信息:
        在线态存在缓存里,用例前先 ``cache.clear()``;Redis 故障用 ``patch`` 造异常。
    """

    def setUp(self):
        """清缓存,避免别的用例留下的在线态干扰断言。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``

        备注信息:
            在线态就存在缓存里,不清会把上一个用例的 presence 键带进来。
        """
        cache.clear()

    def test_touch_then_online(self):
        """打过一次 touch 后该用户判定为在线,并带回最后活跃时间。

        参数说明:
            无。
        """
        presence.touch(9)
        data = presence.get_presence([9])
        self.assertTrue(data[9]["online"])
        self.assertIsNotNone(data[9]["last_active_at"])

    def test_online_window_boundary(self):
        """120 秒窗口边界:119 秒仍在线,121 秒离线但仍保留最后活跃时间。

        参数说明:
            无。
        """
        # 119 秒内 = 在线;121 秒 = 离线但仍有最后活跃时间
        cache.set("presence:9", int(time.time()) - 119)
        cache.set("presence:10", int(time.time()) - 121)
        data = presence.get_presence([9, 10])
        self.assertTrue(data[9]["online"])
        self.assertFalse(data[10]["online"])
        self.assertIsNotNone(data[10]["last_active_at"])

    def test_unknown_user_is_unknown(self):
        """没有记录的账号返回离线且最后活跃为 null,不抛异常。

        参数说明:
            无。
        """
        self.assertEqual(presence.get_presence([404])[404],
                         {"online": False, "last_active_at": None})

    def test_iso_uses_local_timezone(self):
        """最后活跃时间按本地时区渲染,带 ``+08:00`` 偏移。

        参数说明:
            无。
        """
        cache.set("presence:9", 1757745000)
        text = presence.get_presence([9])[9]["last_active_at"]
        self.assertRegex(text, r"\+08:00$")

    @patch("users.presence.cache.get_many", side_effect=Exception("boom"))
    def test_redis_down_query_degrades(self, _):
        """Redis 读失败时查询降级为离线,不向上抛异常。

        参数说明:
            无。
        """
        self.assertEqual(presence.get_presence([9])[9],
                         {"online": False, "last_active_at": None})

    @patch("users.presence.cache.set", side_effect=Exception("boom"))
    def test_redis_down_touch_is_silent(self, _):
        """Redis 写失败时 touch 静默失败,不影响调用方。

        参数说明:
            无。
        """
        presence.touch(9)   # 不抛异常


class ActivityTests(TestCase):
    """日活集合:按天与按小时去重、空日返回 None、TTL、时区归属与 Redis 故障降级。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.ActivityTests``

    备注信息:
        日期全部用类常量 ``DAY`` 固定,不依赖当前时间;相关 Redis 键在 setUp 与 cleanup 里清。
    """

    DAY = date(2026, 11, 2)

    def setUp(self):
        """清掉用例涉及的两天活跃集合,并在用例结束再清一次。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``

        备注信息:
            活跃集合落在 Redis,不清会被别的用例的 touch 污染。
        """
        self._drop_keys(self.DAY, self.DAY + timedelta(days=1))
        self.addCleanup(self._drop_keys, self.DAY, self.DAY + timedelta(days=1))

    def _drop_keys(self, *days):
        """删掉这些日子的活跃集合,避免用例之间互相污染。

        参数说明:
            *days: 本地自然日。

        返回参数:
            无返回值。

        使用示例:
            ``self._drop_keys(self.DAY)``

        备注信息:
            除日集合外,当天 24 个小时桶一并删除。
        """
        keys = []
        for day in days:
            keys.append(activity.day_key(day))
            keys.extend(activity.hour_key(day, hour) for hour in range(24))
        activity._client().delete(*keys)

    def _at(self, hour, minute=0, second=0, day=None):
        """造一个本地时区的时刻。

        参数说明:
            hour: 小时。
            minute: 分钟。
            second: 秒。
            day: 日期;``None`` 取 ``DAY``。

        返回参数:
            带时区的时刻。

        使用示例:
            ``self._at(10, 30)``

        备注信息:
            时区取 ``timezone.get_current_timezone()``,即 Asia/Shanghai,决定日切归属。
        """
        target = day or self.DAY
        return datetime(target.year, target.month, target.day, hour, minute, second,
                        tzinfo=timezone.get_current_timezone())

    def test_touch_records_day_and_hour(self):
        """一次 touch 同时进日集合与小时集合,且值是整数 id。

        参数说明:
            无。
        """
        activity.touch(9, at=self._at(10, 30))
        self.assertEqual(activity.daily_count(self.DAY), 1)
        self.assertEqual(activity.daily_users(self.DAY), {9})
        hours = activity.hourly_counts(self.DAY)
        self.assertEqual(len(hours), 24)
        self.assertEqual(hours[10], 1)
        self.assertEqual(sum(hours), 1)

    def test_same_user_same_day_counts_once(self):
        """同一人同一天 touch 两次仍算 1 人,小时桶也去重。

        参数说明:
            无。
        """
        activity.touch(9, at=self._at(10, 0))
        activity.touch(9, at=self._at(10, 45))
        self.assertEqual(activity.daily_count(self.DAY), 1)
        self.assertEqual(activity.hourly_counts(self.DAY)[10], 1)

    def test_different_hours_are_separate_buckets(self):
        """同一人换个小时又来,日集合仍是 1 人,小时桶各记 1。

        参数说明:
            无。
        """
        activity.touch(9, at=self._at(9, 5))
        activity.touch(9, at=self._at(21, 5))
        hours = activity.hourly_counts(self.DAY)
        self.assertEqual(activity.daily_count(self.DAY), 1)
        self.assertEqual((hours[9], hours[21]), (1, 1))

    def test_missing_day_is_none_not_zero(self):
        """没采到的日子返回 None(看板要显示「无数据」而不是 0)。

        参数说明:
            无。
        """
        self.assertIsNone(activity.daily_count(self.DAY))
        self.assertIsNone(activity.hourly_counts(self.DAY))
        self.assertEqual(activity.daily_users(self.DAY), set())

    def test_ttl_covers_45_days(self):
        """日集合与小时集合都带 45 天 TTL,不会无限涨。

        参数说明:
            无。
        """
        activity.touch(9, at=self._at(10, 0))
        client = activity._client()
        for key in (activity.day_key(self.DAY), activity.hour_key(self.DAY, 10)):
            ttl = client.ttl(key)
            self.assertGreater(ttl, 0)
            self.assertLessEqual(ttl, activity.ACTIVITY_TTL_SECONDS)

    def test_one_day_is_local_calendar_day(self):
        """日切按 Asia/Shanghai:本地 00:00:01 归次日,UTC 16:00 已是本地次日。

        参数说明:
            无。
        """
        activity.touch(9, at=self._at(23, 59, 59))
        activity.touch(10, at=self._at(0, 0, 1, day=self.DAY + timedelta(days=1)))
        # 2026-11-02 16:00 UTC == 2026-11-03 00:00 Asia/Shanghai
        activity.touch(11, at=datetime(2026, 11, 2, 16, 0, tzinfo=dt_timezone.utc))
        self.assertEqual(activity.daily_users(self.DAY), {9})
        self.assertEqual(activity.daily_users(self.DAY + timedelta(days=1)), {10, 11})

    @patch("users.activity.get_redis_connection", side_effect=RuntimeError("redis down"))
    def test_write_failure_is_silent(self, _):
        """Redis 挂了 touch 不抛异常 —— 它挂在认证热路径上,绝不能拖垮业务请求。

        参数说明:
            无。
        """
        activity.touch(9)

    @patch("users.activity.get_redis_connection", side_effect=RuntimeError("redis down"))
    def test_read_failure_degrades(self, _):
        """Redis 挂了读接口降级:计数 None、集合空,都不抛异常。

        参数说明:
            无。
        """
        self.assertIsNone(activity.daily_count(self.DAY))
        self.assertIsNone(activity.hourly_counts(self.DAY))
        self.assertEqual(activity.daily_users(self.DAY), set())

    def test_presence_touch_feeds_activity(self):
        """接线在 presence.touch 末尾:认证请求刷在线态时顺手记日活。

        参数说明:
            无。
        """
        today = timezone.localdate()
        self.addCleanup(self._drop_keys, today)
        presence.touch(9)
        self.assertIn(9, activity.daily_users(today))


class PresenceApiTests(AuthMixin, APITestCase):
    """在线状态接口:返回在线与最后活跃、剔除不可见对象、去重保序、限流与降级。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.PresenceApiTests``

    备注信息:
        可见性剔除靠拉黑与封禁数据驱动,不依赖缓存里的在线态。
    """

    def setUp(self):
        """建我、对方资料行并登录,同时清缓存。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``

        备注信息:
            ``self.url`` 指向 ``GET /api/v1/presence``;清缓存抹掉在线态与限流计数。
        """
        cache.clear()
        self.addCleanup(cache.clear)
        self.me = User.objects.create_user(phone="13800138000")
        self.other = User.objects.create_user(phone="13800138001")
        Profile.objects.get_or_create(user=self.other)
        self.login(self.me)
        self.url = "/api/v1/presence"

    def test_requires_auth(self):
        """未登录查在线状态返回 401。

        参数说明:
            无。
        """
        self.client.credentials()
        self.assertEqual(self.client.get(self.url, {"user_ids": "1"}).status_code, 401)

    def test_returns_online_and_last_active(self):
        """返回对方的在线标志与本地时区的最后活跃时间。

        参数说明:
            无。
        """
        presence.touch(self.other.id)
        data = self.client.get(self.url, {"user_ids": str(self.other.id)}).json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["user_id"], self.other.id)
        self.assertTrue(data["results"][0]["online"])
        self.assertRegex(data["results"][0]["last_active_at"], r"\+08:00$")

    def test_omits_blocked_both_directions(self):
        """拉黑双向的用户都不出现在结果里。

        参数说明:
            无。
        """
        third = User.objects.create_user(phone="13800138002")
        Block.objects.create(blocker=self.me, blocked=self.other)      # 我拉黑的
        Block.objects.create(blocker=third, blocked=self.me)           # 拉黑我的
        data = self.client.get(
            self.url, {"user_ids": f"{self.other.id},{third.id}"}).json()
        self.assertEqual(data["results"], [])

    def test_omits_self_unknown_and_heavy_banned(self):
        """自己、不存在的账号与重封禁目标都被剔除。

        参数说明:
            无。
        """
        Profile.objects.filter(user=self.other).update(status=ProfileStatus.BANNED_HEAVY)
        data = self.client.get(
            self.url,
            {"user_ids": f"{self.me.id},{self.other.id},999999"}).json()
        self.assertEqual(data["results"], [])

    def test_dedupes_and_keeps_request_order(self):
        """重复 id 去重,且结果顺序与请求顺序一致。

        参数说明:
            无。
        """
        data = self.client.get(
            self.url,
            {"user_ids": f"{self.other.id},{self.me.id},{self.other.id}"}).json()
        # 自己去重省略后,只剩 other,顺序稳定
        self.assertEqual([item["user_id"] for item in data["results"]], [self.other.id])

    def test_bad_params(self):
        """缺参、空串、非数字与超过 100 个 id 都返回 400。

        参数说明:
            无。
        """
        self.assertEqual(self.client.get(self.url).status_code, 400)
        self.assertEqual(self.client.get(self.url, {"user_ids": ""}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {"user_ids": "abc"}).status_code, 400)
        too_many = ",".join(str(i) for i in range(1, 102))
        self.assertEqual(self.client.get(self.url, {"user_ids": too_many}).status_code, 400)

    def test_throttled(self):
        """在线状态接口按账号限流,超限返回 429。

        参数说明:
            无。
        """
        from .throttles import PresenceThrottle

        with patch.object(PresenceThrottle, "rate", "2/hour", create=True):
            for _ in range(2):
                self.assertEqual(
                    self.client.get(self.url, {"user_ids": str(self.other.id)}).status_code, 200)
            self.assertEqual(
                self.client.get(self.url, {"user_ids": str(self.other.id)}).status_code, 429)

    @patch("users.presence.cache.get_many", side_effect=Exception("boom"))
    def test_redis_down_returns_null_instead_of_500(self, _):
        """Redis 挂掉时仍返回 200 且最后活跃为 null,不是 500。

        参数说明:
            无。
        """
        resp = self.client.get(self.url, {"user_ids": str(self.other.id)})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["results"][0]["last_active_at"], None)


class DeleteAccountTests(AuthMixin, APITestCase):
    """注销账号:立即硬删除 + 手机号二次确认 + 重封禁 403(防注销洗白)。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.DeleteAccountTests``

    备注信息:
        注销是真删,账号行删完 ``refresh_from_db`` 会抛异常,断言一律查目标 id 是否还存在;
        入队 IM 删号的断言必须用 ``captureOnCommitCallbacks(execute=True)``。
    """

    def setUp(self):
        """准备临时 MEDIA_ROOT、清缓存、建账号并登录。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``

        备注信息:
            本类末尾要真调一次 ``/auth/sms/verify``,故必须清掉别的用例留下的
            IP 限流计数与验证码,否则会被别处的计数连累而红。
        """
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir)   # 测试图片不写入真实 media/
        override.enable()
        self.addCleanup(override.disable)
        # 清掉别的用例留下的 IP 限流计数 / 验证码 / presence 残留
        # (本类末尾要真调一次 /auth/sms/verify,不清会被别处的限流计数连累)
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(phone="13800138000")
        self.login(self.user)
        self.url = "/api/v1/users/me"

    def _delete(self, phone="13800138000"):
        """调用账号注销接口。

        参数说明:
            phone: 二次确认用的手机号。

        返回参数:
            DRF 测试客户端的响应对象。

        使用示例:
            ``self._delete(phone="13900139000")``

        备注信息:
            注销是 ``DELETE /api/v1/users/me``,手机号走 JSON body 做二次确认。
        """
        return self.client.delete(self.url, {"phone": phone}, format="json")

    def test_requires_auth(self):
        """未登录注销返回 401。

        参数说明:
            无。
        """
        self.client.credentials()
        resp = self._delete()
        self.assertEqual(resp.status_code, 401)

    def test_phone_mismatch_rejected_and_data_kept(self):
        """手机号与当前账号不一致返回 400,数据原封不动。

        参数说明:
            无。
        """
        resp = self._delete(phone="13900139000")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], 400)
        self.assertEqual(resp.json()["message"], "手机号与当前账号不一致")
        self.assertTrue(User.objects.filter(id=self.user.id).exists())

    def test_phone_missing_rejected(self):
        """不传手机号返回 400,数据保留。

        参数说明:
            无。
        """
        resp = self.client.delete(self.url, {}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], 400)
        self.assertTrue(User.objects.filter(id=self.user.id).exists())

    def test_heavy_banned_cannot_delete(self):
        """重封禁账号禁止注销(防注销洗白),返回 403。

        参数说明:
            无。
        """
        Profile.objects.create(user=self.user, status=ProfileStatus.BANNED_HEAVY)
        resp = self._delete()
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(User.objects.filter(id=self.user.id).exists())

    def test_light_banned_can_delete(self):
        """轻封禁账号仍可注销,返回 204。

        参数说明:
            无。
        """
        Profile.objects.create(user=self.user, status=ProfileStatus.BANNED_LIGHT)
        self.assertEqual(self._delete().status_code, 204)

    def test_success_deletes_user_and_all_related_rows(self):
        """注销返回 204 空响应,账号与全部关联数据被硬删除。

        参数说明:
            无。
        备注信息:
            关联数据含资料、照片、滑卡、配对、动态与动态图、评论、拉黑、举报、封禁日志,
            别人对我发起的行(滑卡/拉黑/举报)也一并清。
        """
        user_id = self.user.id
        other = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.user, nickname="小明")
        Photo.objects.create(user=self.user, file="photos/a.png")
        Swipe.objects.create(swiper=self.user, target=other, action="like")
        Swipe.objects.create(swiper=other, target=self.user, action="like")
        Match.objects.create(**Match.pair_kwargs(self.user, other))
        post = Post.objects.create(author=self.user, text="动态")
        PostImage.objects.create(post=post, file="posts/a.png")
        PostComment.objects.create(post=post, author=other, text="评论")
        Block.objects.create(blocker=self.user, blocked=other)
        Report.objects.create(reporter=other, target=self.user, type="harassment")
        BanLog.objects.create(user=self.user, action="ban_light", reason="x")

        resp = self._delete()

        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp.content, b"")
        self.assertFalse(User.objects.filter(id=user_id).exists())
        self.assertFalse(Profile.objects.filter(user_id=user_id).exists())
        self.assertFalse(Photo.objects.filter(user_id=user_id).exists())
        self.assertFalse(Swipe.objects.filter(Q(swiper_id=user_id) | Q(target_id=user_id)).exists())
        self.assertFalse(Match.objects.filter(Q(user_a_id=user_id) | Q(user_b_id=user_id)).exists())
        self.assertFalse(Post.objects.filter(author_id=user_id).exists())
        self.assertFalse(PostImage.objects.filter(post__author_id=user_id).exists())
        self.assertFalse(PostComment.objects.filter(author_id=user_id).exists())
        self.assertFalse(Block.objects.filter(Q(blocker_id=user_id) | Q(blocked_id=user_id)).exists())
        self.assertFalse(Report.objects.filter(Q(reporter_id=user_id) | Q(target_id=user_id)).exists())
        self.assertFalse(BanLog.objects.filter(user_id=user_id).exists())

    def test_deletes_photo_and_post_image_files_on_disk(self):
        """注销同时删掉资料图与动态图的磁盘文件。

        参数说明:
            无。
        """
        photo = Photo.objects.create(user=self.user)
        photo.file.save("a.png", ContentFile(PNG_1PX), save=True)
        post = Post.objects.create(author=self.user, text="动态")
        image = PostImage.objects.create(post=post)
        image.file.save("b.png", ContentFile(PNG_1PX), save=True)
        photo_name, image_name = photo.file.name, image.file.name
        self.assertTrue(default_storage.exists(photo_name))
        self.assertTrue(default_storage.exists(image_name))

        with self.captureOnCommitCallbacks(execute=True):
            resp = self._delete()

        self.assertEqual(resp.status_code, 204)
        self.assertFalse(default_storage.exists(photo_name))
        self.assertFalse(default_storage.exists(image_name))

    def test_deletes_chat_image_files_on_disk(self):
        """注销同时删掉聊天图与其缩略图的磁盘文件。

        参数说明:
            无。
        """
        from im.models import ChatImage   # 延迟导入,与 services.py 的删号逻辑保持一致

        image = ChatImage(owner=self.user, width=1, height=1, bytes=len(PNG_1PX))
        image.file.save("chat/c.png", ContentFile(PNG_1PX), save=False)
        image.thumb.save("chat/c_thumb.png", ContentFile(PNG_1PX), save=False)
        image.save()
        names = [image.file.name, image.thumb.name]
        for name in names:
            self.assertTrue(default_storage.exists(name))

        with self.captureOnCommitCallbacks(execute=True):
            resp = self._delete()

        self.assertEqual(resp.status_code, 204)
        for name in names:
            self.assertFalse(default_storage.exists(name), name)

    def test_clears_presence_and_kick_pending_flag(self):
        """注销清掉在线状态与「待踢旧会话」标记。

        参数说明:
            无。
        """
        user_id = self.user.id
        presence.touch(user_id)
        cache.set(im_tasks.kick_pending_key(user_id, "app"), 1, 60)
        self.assertIsNotNone(presence.get_presence([user_id])[user_id]["last_active_at"])

        with self.captureOnCommitCallbacks(execute=True):
            self._delete()

        self.assertIsNone(presence.get_presence([user_id])[user_id]["last_active_at"])
        self.assertIsNone(cache.get(im_tasks.kick_pending_key(user_id, "app")))

    @patch("im.tasks.delete_account.delay")
    def test_enqueues_im_delete_with_im_user_id_after_commit(self, delay):
        """提交后按 ``u<账号 id>`` 入队 IM 删号任务。

        参数说明:
            无。
        备注信息:
            入队参数是字符串 ``u<id>``;账号行删完后 ``user.id`` 会是 None,必须在注销前先取值。
        """
        user_id = self.user.id          # ⚠️ 必须在注销前取,删完 user.id 会是 None
        with self.captureOnCommitCallbacks(execute=True):
            resp = self._delete()
        self.assertEqual(resp.status_code, 204)
        delay.assert_called_once_with(f"u{user_id}")

    @patch("im.tasks.delete_account.delay")
    def test_nothing_enqueued_when_phone_mismatch(self, delay):
        """手机号不符时不入队 IM 删号任务。

        参数说明:
            无。
        """
        with self.captureOnCommitCallbacks(execute=True):
            resp = self._delete(phone="13900139000")
        self.assertEqual(resp.status_code, 400)
        delay.assert_not_called()

    def test_other_users_data_untouched(self):
        """只删自己:别人的账号、资料与照片都不受影响。

        参数说明:
            无。
        """
        other = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=other, nickname="小红")
        Photo.objects.create(user=other, file="photos/b.png")
        self.assertEqual(self._delete().status_code, 204)
        self.assertTrue(User.objects.filter(id=other.id).exists())
        self.assertTrue(Profile.objects.filter(user=other).exists())
        self.assertTrue(Photo.objects.filter(user=other).exists())

    def test_old_token_rejected_after_delete(self):
        """注销后旧 access token 立刻失效,读我的资料返回 401。

        参数说明:
            无。
        """
        self.assertEqual(self._delete().status_code, 204)
        # 同一个 access token:用户行没了 → 鉴权失败
        self.assertEqual(self.client.get("/api/v1/users/me").status_code, 401)

    def test_same_phone_can_register_again_as_new_user(self):
        """注销后同一手机号可重新注册,拿到的是新的账号 id。

        参数说明:
            无。
        """
        old_id = self.user.id
        self.assertEqual(self._delete().status_code, 204)

        self.client.credentials()   # 旧令牌已失效,换匿名请求
        cache.delete("sms:send:13800138000")
        sms_codes.store("13800138000", settings.SMS_DEV_CODE)
        resp = self.client.post("/api/v1/auth/sms/verify",
                                {"phone": "13800138000", "code": settings.SMS_DEV_CODE},
                                format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["is_new_user"])
        self.assertNotEqual(resp.json()["user_id"], old_id)
class ProfileVisitModelTests(TestCase):
    """访客记录模型:默认值、唯一约束、按最近访问排序。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.ProfileVisitModelTests``

    备注信息:
        只测模型层,不经过接口;排序用例显式错开时间,避免同一时刻并列。
    """

    def setUp(self):
        """建两个账号备用。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``

        备注信息:
            两个账号互为访客与主人,用例里按需再建资料行。
        """
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def test_visits_hidden_defaults_to_false(self):
        """资料默认不隐身,``visits_hidden`` 为假。

        参数说明:
            无。
        """
        profile = Profile.objects.create(user=self.a, nickname="小明")
        self.assertFalse(profile.visits_hidden)

    def test_unique_viewer_owner_pair(self):
        """同一个 (访客, 主人) 只能有一行,重复插入撞唯一约束。

        参数说明:
            无。
        """
        ProfileVisit.objects.create(viewer=self.a, owner=self.b, last_at=timezone.now())
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProfileVisit.objects.create(viewer=self.a, owner=self.b, last_at=timezone.now())

    def test_ordered_by_last_at_desc(self):
        """访客列表按最近访问时间倒序,最新的一条排最前。

        参数说明:
            无。
        """
        # 显式错开时间:Windows 上 time.time() 分辨率约 15ms,连着两次 now() 可能相等,
        # 排序就会退化成「插入顺序」而偶发失败。
        now = timezone.now()
        ProfileVisit.objects.create(viewer=self.a, owner=self.b,
                                    last_at=now - timedelta(minutes=5))
        ProfileVisit.objects.create(viewer=self.b, owner=self.a, last_at=now)
        first = ProfileVisit.objects.first()
        self.assertEqual(first.viewer_id, self.b.id)

class ProfileVisitWriteTests(TestCase):
    """落库口径:30 分钟窗口、隐身、自看、展示门槛与上限、异常兜底。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.ProfileVisitWriteTests``

    备注信息:
        访客记录只对「资料完善 + 有过审照片 + 没隐身」的访问者落库,门槛由 ``_make_displayable`` 造。
    """

    def setUp(self):
        """建访客与主人,并把访客补成「可展示」状态。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``

        备注信息:
            访客记录只对「资料完善 + 有过审照片」的访问者落库,所以建完马上补全。
        """
        cache.clear()
        self.addCleanup(cache.clear)
        self.viewer = User.objects.create_user(phone="13800138000")
        self.owner = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.viewer, nickname="小明")
        Profile.objects.create(user=self.owner, nickname="小红")
        self._make_displayable(self.viewer, "小明")

    def _make_displayable(self, user, nickname="小明"):
        """把用户补成「资料完善 + 一张过审照片」——访客记录只对这类访问者落库(M-2)。

        参数说明:
            user: 目标账号。
            nickname: 昵称(资料完善必填项之一)。

        返回参数:
            无返回值。

        使用示例:
            ``self._make_displayable(user, "小红")``

        备注信息:
            补完字段后调一次 ``refresh_status``,状态才会跟着变成完善。
        """
        profile = user.profile
        profile.nickname = nickname
        profile.gender = "male"
        profile.birthday = date(1995, 1, 1)
        profile.city = "上海"
        profile.bio = "你好"
        profile.save()
        Photo.objects.create(user=user, file="photos/visit-test.jpg",
                             status=PhotoStatus.APPROVED)
        profile.refresh_status()

    def test_first_visit_creates_row(self):
        """第一次访问建一行,``first_at`` 与 ``last_at`` 只差毫秒级。

        参数说明:
            无。
        """
        services.record_profile_view(self.viewer.id, self.owner.id)
        visit = ProfileVisit.objects.get(viewer=self.viewer, owner=self.owner)
        # first_at 由 auto_now_add 在插入时取,last_at 是写入前算的 now,两者差毫秒级
        self.assertLess(abs((visit.last_at - visit.first_at).total_seconds()), 1)

    def test_second_visit_within_window_keeps_one_row(self):
        """30 分钟窗口内重复访问:库里仍只有一行,``last_at`` 不变。

        参数说明:
            无。
        """
        services.record_profile_view(self.viewer.id, self.owner.id)
        before = ProfileVisit.objects.get(viewer=self.viewer, owner=self.owner).last_at
        services.record_profile_view(self.viewer.id, self.owner.id)
        self.assertEqual(ProfileVisit.objects.count(), 1)
        after = ProfileVisit.objects.get(viewer=self.viewer, owner=self.owner).last_at
        self.assertEqual(before, after)

    def test_visit_after_window_updates_last_at(self):
        """窗口过期后再访问,同一行的 ``last_at`` 被推到更近。

        参数说明:
            无。
        """
        services.record_profile_view(self.viewer.id, self.owner.id)
        before = ProfileVisit.objects.get(viewer=self.viewer, owner=self.owner).last_at
        cache.delete(f"visit:{self.viewer.id}:{self.owner.id}")   # 模拟 30 分钟窗口过期
        services.record_profile_view(self.viewer.id, self.owner.id)
        self.assertEqual(ProfileVisit.objects.count(), 1)
        after = ProfileVisit.objects.get(viewer=self.viewer, owner=self.owner).last_at
        self.assertGreater(after, before)

    def test_incognito_viewer_is_not_recorded(self):
        """隐身的访问者不落库。

        参数说明:
            无。
        """
        profile = self.viewer.profile
        profile.visits_hidden = True
        profile.save(update_fields=["visits_hidden"])
        services.record_profile_view(self.viewer.id, self.owner.id)
        self.assertEqual(ProfileVisit.objects.count(), 0)

    def test_self_view_is_not_recorded(self):
        """看自己的资料不落库。

        参数说明:
            无。
        """
        services.record_profile_view(self.viewer.id, self.viewer.id)
        self.assertEqual(ProfileVisit.objects.count(), 0)

    def test_write_failure_is_swallowed(self):
        """写库失败被吞掉,不影响请求响应。

        参数说明:
            无。
        """
        with patch("users.services.ProfileVisit.objects.update_or_create",
                   side_effect=RuntimeError("db down")):
            services.record_profile_view(self.viewer.id, self.owner.id)   # 不抛即通过

    def test_missing_profile_is_not_recorded(self):
        """资料未创建 = 未完善,不在访客列表的展示口径内,不落库(M-2)。

        参数说明:
            无。
        """
        stranger = User.objects.create_user(phone="13900139002")   # 没有 Profile
        services.record_profile_view(stranger.id, self.owner.id)
        self.assertFalse(ProfileVisit.objects.filter(viewer=stranger).exists())

    def test_incomplete_viewer_is_not_recorded(self):
        """资料未完善的访问者不会出现在列表里,写库是纯放大(M-2)。

        参数说明:
            无。
        """
        half = User.objects.create_user(phone="13900139003")
        Profile.objects.create(user=half, nickname="只填了昵称")
        services.record_profile_view(half.id, self.owner.id)
        self.assertFalse(ProfileVisit.objects.filter(viewer=half).exists())

    def test_viewer_without_approved_photo_is_not_recorded(self):
        """照片待审/没有照片同样不落库,与 ``visits_received_queryset`` 同口径(M-2)。

        参数说明:
            无。
        """
        profile = self.viewer.profile
        Photo.objects.filter(user=self.viewer).update(status=PhotoStatus.PENDING)
        profile.refresh_status()
        services.record_profile_view(self.viewer.id, self.owner.id)
        self.assertFalse(ProfileVisit.objects.filter(viewer=self.viewer).exists())

    @override_settings(PROFILE_VISIT_MAX_PER_OWNER=2)
    def test_owner_keeps_only_recent_visits(self):
        """单个 owner 超过上限时淘汰最旧的行,表不会无限增长(M-2 第二道闸)。

        参数说明:
            无。
        """
        for index in range(3):
            viewer = User.objects.create_user(phone=f"1370013900{index}")
            Profile.objects.create(user=viewer, nickname=f"访客{index}")
            self._make_displayable(viewer, f"访客{index}")
            services.record_profile_view(viewer.id, self.owner.id)
        self.assertEqual(ProfileVisit.objects.filter(owner=self.owner).count(), 2)

class PurgeProfileVisitsCommandTests(TestCase):
    """保留期清理:dry-run 不删、--apply 只删过期行、自定义天数。

    参数说明:
        无构造参数。

    返回参数:
        测试类实例,由测试框架实例化。

    使用示例:
        ``python manage.py test users.tests.PurgeProfileVisitsCommandTests``

    备注信息:
        默认保留期 90 天,``--days`` 可覆盖;两条记录分别落在 91 天与 89 天前。
    """

    def setUp(self):
        """造一条 91 天前与一条 89 天前的访客记录。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self.setUp()``

        备注信息:
            默认保留期 90 天,故两条正好横跨期与未过期。
        """
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")
        self.old = ProfileVisit.objects.create(
            viewer=self.a, owner=self.b,
            last_at=timezone.now() - timedelta(days=91))
        self.fresh = ProfileVisit.objects.create(
            viewer=self.b, owner=self.a,
            last_at=timezone.now() - timedelta(days=89))

    def test_dry_run_keeps_rows(self):
        """默认 dry-run 一条都不删。

        参数说明:
            无。
        """
        call_command("purge_profile_visits", stdout=StringIO())
        self.assertEqual(ProfileVisit.objects.count(), 2)

    def test_apply_deletes_only_expired(self):
        """``--apply`` 只删超过保留期的行,未过期的不动。

        参数说明:
            无。
        """
        call_command("purge_profile_visits", "--apply", stdout=StringIO())
        self.assertFalse(ProfileVisit.objects.filter(id=self.old.id).exists())
        self.assertTrue(ProfileVisit.objects.filter(id=self.fresh.id).exists())

    def test_custom_days(self):
        """``--days`` 可自定义保留天数,传 1 天时两条都过期。

        参数说明:
            无。
        """
        call_command("purge_profile_visits", "--apply", "--days", "1", stdout=StringIO())
        self.assertEqual(ProfileVisit.objects.count(), 0)