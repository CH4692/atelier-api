from io import BytesIO

import pytest
from fastapi import HTTPException
from PIL import Image
from starlette.datastructures import UploadFile

from atelier_api.photos.images import prepare_image, safe_filename
from atelier_api.photos.models import MAX_PHOTO_BYTES
from tests.photos.helpers import image_bytes


@pytest.mark.parametrize(
    "format,mime,extension",
    [
        ("JPEG", "image/jpeg", "jpg"),
        ("PNG", "image/png", "png"),
        ("WEBP", "image/webp", "webp"),
    ],
)
def test_actual_pixels_determine_format_and_temporary_data_is_closed(
    format, mime, extension
):
    with BytesIO(image_bytes(format)) as source:
        upload = UploadFile(source, filename="../../untrusted.exe")
        with prepare_image(upload) as prepared:
            assert prepared.filename == "untrusted.exe"
            assert prepared.content_type == mime
            assert prepared.extension == extension
            with Image.open(prepared.source) as decoded:
                assert decoded.size == (16, 12)
        assert prepared.source.closed


@pytest.mark.parametrize("filename", [None, "", "..", "x\n.png", "a" * 256])
def test_invalid_filename(filename):
    with pytest.raises(HTTPException) as error:
        safe_filename(filename)
    assert error.value.status_code == 422


def test_exif_gps_and_comments_are_removed_and_orientation_is_applied():
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "Private photographer"
    exif[34853] = {1: "N", 2: (48.0, 0.0, 0.0)}
    original = image_bytes("JPEG", exif=exif, comment=b"Private comment")
    with (
        BytesIO(original) as source,
        prepare_image(UploadFile(source, filename="condition.jpg")) as prepared,
    ):
        content = prepared.source.read()
        assert b"Private" not in content
        with Image.open(BytesIO(content)) as image:
            assert not image.getexif()
            assert not image.info.get("comment")
            assert image.size == (12, 16)


@pytest.mark.parametrize(
    "data,expected",
    [
        (b"<svg>bad</svg>", 415),
        (image_bytes("GIF"), 415),
        (image_bytes("JPEG")[:-20], 422),
        (b"x" * (MAX_PHOTO_BYTES + 1), 413),
    ],
)
def test_invalid_or_oversized_data(data, expected):
    with (
        BytesIO(data) as source,
        pytest.raises(HTTPException) as error,
        prepare_image(UploadFile(source, filename="photo.jpg")),
    ):
        pytest.fail("Invalid image accepted")
    assert error.value.status_code == expected


def test_pixel_limit_is_checked_before_decoding(monkeypatch):
    monkeypatch.setattr("atelier_api.photos.images.MAX_PIXELS", 100)
    with (
        BytesIO(image_bytes()) as source,
        pytest.raises(HTTPException, match="20 megapixels"),
        prepare_image(UploadFile(source, filename="photo.png")),
    ):
        pytest.fail("Oversized dimensions accepted")


def test_decompression_bomb_rejected(monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)
    with (
        BytesIO(image_bytes()) as source,
        pytest.raises(HTTPException) as error,
        prepare_image(UploadFile(source, filename="photo.png")),
    ):
        pytest.fail("Decompression bomb accepted")
    assert error.value.status_code == 422


def test_animated_image_rejected():
    with (
        BytesIO() as source,
        Image.new("RGB", (2, 2), "red") as first,
        Image.new("RGB", (2, 2), "blue") as second,
    ):
        first.save(source, format="PNG", save_all=True, append_images=[second])
        source.seek(0)
        with (
            pytest.raises(HTTPException, match="Animated"),
            prepare_image(UploadFile(source, filename="photo.png")),
        ):
            pytest.fail("Animation accepted")
