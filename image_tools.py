"""Bounded raster previews; original bytes stay in the authenticated library."""
from __future__ import annotations

import io
import warnings
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from workspace import WorkspaceError

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
IMAGE_FORMATS = ("PNG", "JPEG", "WEBP", "GIF", "BMP", "TIFF")
MAX_IMAGE_PIXELS = 25_000_000
MAX_PREVIEW_EDGE = 4096


def file_kind(record):
    """Also recognize images saved as attachments before image previews existed."""
    kind = record.get("type", "attachment")
    suffix = Path(record.get("originalName") or record.get("title", "")).suffix.lower()
    return "image" if kind == "attachment" and suffix in IMAGE_SUFFIXES else kind


def image_info(raw):
    if not isinstance(raw, bytes) or not raw or len(raw) > 8 * 1024 * 1024:
        raise WorkspaceError("الصورة فارغة أو تتجاوز 8 ميجابايت.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw), formats=IMAGE_FORMATS) as source:
                width, height = source.size
                if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
                    raise WorkspaceError("أبعاد الصورة تتجاوز حد المعاينة وهو 25 مليون بكسل.")
                metadata = {"width": width, "height": height, "format": source.format}
                source.verify()
                return metadata
    except WorkspaceError:
        raise
    except Exception:
        raise WorkspaceError("تعذّر قراءة الصورة؛ تأكد من أنها صورة سليمة بصيغة PNG أو JPG أو WEBP أو GIF أو BMP أو TIFF.") from None


@dataclass(frozen=True)
class ImagePreview:
    data: bytes
    width: int
    height: int
    format: str


def prepare_image(raw):
    info = image_info(raw)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw), formats=IMAGE_FORMATS) as source:
                # One frame keeps GIF/TIFF work bounded. EXIF orientation is
                # applied to the preview, including older uploaded attachments.
                image = ImageOps.exif_transpose(source)
                try:
                    image.thumbnail((MAX_PREVIEW_EDGE, MAX_PREVIEW_EDGE), Image.Resampling.LANCZOS)
                    mode = "RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB"
                    converted = image.convert(mode)
                    try:
                        output = io.BytesIO()
                        if info["format"] == "JPEG":
                            converted.save(output, "JPEG", quality=92, exif=b"", icc_profile=None)
                        else:
                            converted.save(output, "PNG", compress_level=3, exif=b"", icc_profile=None)
                        return ImagePreview(output.getvalue(), image.width, image.height, info["format"])
                    finally:
                        converted.close()
                finally:
                    image.close()
    except Exception:
        raise WorkspaceError("تعذّر تجهيز معاينة الصورة. يمكنك تنزيل الأصل لفتحه.") from None
