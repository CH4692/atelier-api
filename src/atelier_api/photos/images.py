"""Validate actual image data and re-encode pixels without private metadata."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from tempfile import SpooledTemporaryFile
from threading import BoundedSemaphore
from typing import IO

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.datastructures import UploadFile

from .models import MAX_PHOTO_BYTES, MAX_PIXELS

FORMATS = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}
# Bound concurrent decoder memory per application process, independently of uploads.
_decoders = BoundedSemaphore(2)


@dataclass
class PreparedImage:
    """Own a bounded temporary encoding until upload finishes or fails."""

    source: IO[bytes]
    filename: str
    content_type: str
    extension: str
    size: int

    def close(self) -> None:
        self.source.close()


def safe_filename(value: str | None) -> str:
    name = (value or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if (
        name in {"", ".", ".."}
        or len(name) > 255
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
    ):
        raise HTTPException(422, "Invalid photo filename")
    return name


@contextmanager
def prepare_image(upload: UploadFile) -> Iterator[PreparedImage]:
    """Verify content, cap pixels, apply orientation and discard all EXIF/ICC data.

    MIME and filename extensions are untrusted hints. The actual decoded format
    determines storage and response types. Animated images are rejected rather
    than silently losing documentation frames.
    """
    name = safe_filename(upload.filename)
    upload.file.seek(0, 2)
    if upload.file.tell() > MAX_PHOTO_BYTES:
        raise HTTPException(413, "Photograph exceeds 10 MB")
    upload.file.seek(0)
    with SpooledTemporaryFile(max_size=1_000_000, mode="w+b") as output:
        try:
            with _decoders:
                with Image.open(upload.file, formats=list(FORMATS)) as image:
                    image_format = image.format or ""
                    if image.width * image.height > MAX_PIXELS:
                        raise HTTPException(422, "Photograph exceeds 20 megapixels")
                    if getattr(image, "n_frames", 1) != 1:
                        raise HTTPException(
                            422, "Animated photographs are not supported"
                        )
                    image.verify()
                upload.file.seek(0)
                with Image.open(upload.file, formats=list(FORMATS)) as image:
                    image.load()
                    oriented = ImageOps.exif_transpose(image)
                    try:
                        mode = (
                            "RGBA"
                            if image_format != "JPEG"
                            and (
                                "A" in oriented.getbands()
                                or "transparency" in oriented.info
                            )
                            else "RGB"
                        )
                        with (
                            oriented.convert(mode) as pixels,
                            Image.new(mode, oriented.size) as clean,
                        ):
                            clean.paste(pixels)
                            clean.save(output, format=image_format)
                    finally:
                        oriented.close()
            size = output.tell()
            if size > MAX_PHOTO_BYTES:
                raise HTTPException(413, "Re-encoded photograph exceeds 10 MB")
            output.seek(0)
            content_type, extension = FORMATS[image_format]
            prepared = PreparedImage(output, name, content_type, extension, size)
        except HTTPException:
            raise
        except UnidentifiedImageError:
            raise HTTPException(415, "Use a valid JPEG, PNG or WebP image") from None
        except Image.DecompressionBombError, OSError, ValueError, SyntaxError:
            raise HTTPException(422, "Invalid photograph") from None
        yield prepared
