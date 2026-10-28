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
    """图片不可用(格式不支持、像素过大、无法解码)。"""


class ImageTooLarge(ImageError):
    """图片像素总数或边长超过上限。"""


class UnsupportedImage(ImageError):
    """图片格式不在白名单内。"""


@dataclass(frozen=True)
class NormalizedImage:
    """重编码后的图片。

    Attributes:
        data: 重编码后的字节(不含 EXIF/GPS)。
        extension: 落盘后缀,如 ``.jpg``。
        width: 重编码后的宽。
        height: 重编码后的高。
        image: 重编码后的 PIL 对象,供调用方生成缩略图。
    """

    data: bytes
    extension: str
    width: int
    height: int
    image: Image.Image


def open_checked(raw: bytes) -> Image.Image:
    """打开图片并检查格式与像素上限(此时尚未解码像素)。

    Args:
        raw: 上传的原始字节。

    Returns:
        已通过校验、尚未 ``load()`` 的 PIL 图片对象。

    Raises:
        UnsupportedImage: 格式不在 jpg/png/webp 白名单内。
        ImageTooLarge: 像素总数超过 ``MAX_IMAGE_PIXELS``。
        ImageError: 文件不是可识别的图片。
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

    Args:
        image: ``open_checked`` 返回的图片。
        max_side: 长边上限;超过则等比缩小。

    Returns:
        重编码后的图片数据与尺寸。

    Raises:
        UnsupportedImage: 打开后格式丢失或不在白名单内。
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
