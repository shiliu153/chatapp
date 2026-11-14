"""上传图片的统一校验与重编码。

设计要点:
    1. **先读 header 再解码**:``Image.open`` 只读文件头,拿到 ``size`` 后先判断像素总数,
       超过上限直接拒绝,避免解压炸弹在 ``exif_transpose``/``load`` 时分配巨量内存;
    2. **只接受 jpg/png/webp**:GIF/BMP/TIFF/PDF 等格式一律拒绝,缩小解码攻击面;
    3. **统一重编码**:所有图片都经 ``exif_transpose`` 后重新保存,新图不带 EXIF/GPS,
       同时把超长边缩到上限;
    4. 三个上传入口(资料图、广场图、聊天图)共用本模块,行为保持一致。

关联文档:
    - 安全审计:M3(像素上限)、M4(EXIF 剥离)、L5(格式面)

文件信息:
    文件名称          config/images.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps

# Pillow 自己的告警阈值:超过 2 倍上限会在 open 时抛 DecompressionBombError
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_SIDE = 4096
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


class ImageError(ValueError):
    """图片不可用(格式不支持、像素过大、无法解码)。

    参数说明:
        无(继承 ``ValueError``,未自定义 ``__init__``)。

    返回参数:
        异常实例本身。

    使用示例:
        ``raise ImageError("请上传图片文件")``

    备注信息:
        三个子类都继承它,调用方只捕 ``ImageError`` 即可覆盖全部图片问题;
        ``users`` / ``im`` 两个上传入口直接返回 400,``feed`` 转 ``ValidationError``
        (同样落到 400),响应里的文案就是异常文本。
    """


class ImageTooLarge(ImageError):
    """图片像素总数或边长超过上限。

    参数说明:
        无(继承 ``ImageError``,未自定义 ``__init__``)。

    返回参数:
        异常实例本身。

    使用示例:
        ``raise ImageTooLarge("图片像素过大")``

    备注信息:
        两条触发路径:``Image.open`` 抛 ``DecompressionBombError``(Pillow 按
        ``MAX_IMAGE_PIXELS`` 的两倍判定解压炸弹)与像素总数超过 ``MAX_IMAGE_PIXELS``(2000 万)。
        长边超限不会被拒绝,只在 ``normalize`` 里等比缩到 ``MAX_IMAGE_SIDE``。
    """


class UnsupportedImage(ImageError):
    """图片格式不在白名单内。

    参数说明:
        无(继承 ``ImageError``,未自定义 ``__init__``)。

    返回参数:
        异常实例本身。

    使用示例:
        ``raise UnsupportedImage("只支持 jpg/png/webp 图片")``

    备注信息:
        ``open_checked`` 与 ``normalize`` 都会抛:前者看 ``image.format``,
        后者在重编码前再查一次,防止打开后格式信息丢失。
    """


@dataclass(frozen=True)
class NormalizedImage:
    """重编码后的图片。

    Attributes:
        data: 重编码后的字节(不含 EXIF/GPS)。
        extension: 落盘后缀,如 ``.jpg``。
        width: 重编码后的宽。
        height: 重编码后的高。
        image: 重编码后的 PIL 对象,供调用方生成缩略图。

    参数说明:
        data: 重编码后的字节,即要落盘的内容。
        extension: 落盘后缀,用作文件名结尾。
        width: 重编码后的宽,与 ``image.width`` 相同。
        height: 重编码后的高,与 ``image.height`` 相同。
        image: 重编码后的 PIL 对象,供调用方生成缩略图。

    返回参数:
        冻结的 ``NormalizedImage`` 实例;字段赋值后不可改。

    使用示例:
        ``NormalizedImage(data=data, extension=".jpg", width=800, height=600, image=clean)``

    备注信息:
        ``frozen=True``:实例创建后字段不可改,要换尺寸只能重新构造;
        字段声明顺序即构造参数顺序,按位置传参同样有效。
    """

    data: bytes
    extension: str
    width: int
    height: int
    image: Image.Image


def open_checked(raw: bytes) -> Image.Image:
    """打开图片并检查格式与像素上限(此时尚未解码像素)。

    参数说明:
        raw: 上传的原始字节。

    返回参数:
        已通过校验、尚未 ``load()`` 的 PIL 图片对象。

    使用示例:
        ``image = open_checked(request.FILES["photo"].read())``

    备注信息:
        ``Image.open`` 只读文件头,所以这里不会分配像素内存;拿到对象后仍需
        ``exif_transpose``/``load`` 才真正解码。
        抛 ``UnsupportedImage``(格式不在白名单)、``ImageTooLarge``(像素总数超限或
        被判为解压炸弹)、``ImageError``(文件不是可识别的图片或宽高非正)。
    """
    try:
        image = Image.open(io.BytesIO(raw))
    except Image.DecompressionBombError as error:
        raise ImageTooLarge("图片像素过大") from error
    except Exception as error:      # UnidentifiedImageError / OSError 等
        raise ImageError("请上传图片文件") from error

    if (image.format or "").upper() not in ALLOWED_FORMATS:
        raise UnsupportedImage("只支持 jpg/png/webp 图片")
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ImageError("图片尺寸不合法")
    if width * height > MAX_IMAGE_PIXELS:
        raise ImageTooLarge("图片像素过大,请先压缩")
    return image


def normalize(image: Image.Image, *, max_side: int = MAX_IMAGE_SIDE) -> NormalizedImage:
    """按 EXIF 方向摆正、缩到上限并重新编码(丢弃全部元数据)。

    参数说明:
        image: ``open_checked`` 返回的图片。
        max_side: 长边上限;超过则等比缩小。

    返回参数:
        重编码后的图片数据与尺寸。

    使用示例:
        ``normalized = normalize(image, max_side=2048)``

    备注信息:
        保存前把 ``info`` 清空,EXIF/GPS 不会带进新图;JPEG 质量 85 且开 ``optimize``,
        WebP 质量 85,PNG 走无损。模式不合适的先 ``convert("RGB")``(JPEG、WebP)或
        保留 ``RGBA``(WebP);格式不在白名单时抛 ``UnsupportedImage``。
        ``max_side`` 是仅关键字参数,调用时必须写参数名。
    """
    fmt = (image.format or "").upper()
    if fmt not in ALLOWED_FORMATS:
        raise UnsupportedImage("只支持 jpg/png/webp 图片")

    display = ImageOps.exif_transpose(image)
    if max(display.size) > max_side:
        display.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    if fmt == "JPEG":
        clean = display.convert("RGB") if display.mode not in ("RGB", "L") else display.copy()
        clean.info = {}
        clean.save(buffer, "JPEG", quality=85, optimize=True)
        extension = ".jpg"
    elif fmt == "PNG":
        clean = display.copy()
        clean.info = {}
        clean.save(buffer, "PNG", optimize=True)
        extension = ".png"
    else:   # WEBP
        clean = display.convert("RGB") if display.mode not in ("RGB", "RGBA") else display.copy()
        clean.info = {}
        clean.save(buffer, "WEBP", quality=85)
        extension = ".webp"

    data = buffer.getvalue()
    return NormalizedImage(data=data, extension=extension, width=clean.width,
                           height=clean.height, image=clean)
