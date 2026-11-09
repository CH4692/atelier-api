"""Validate synthetic demonstration assets without an object-storage service."""

from io import BytesIO

from PIL import Image

from atelier_api.demo.photos import illustration


def test_demo_illustrations_are_repeatable_real_images_with_distinct_views():
    assert illustration(0, 0) == illustration(0, 0)
    assert illustration(0, 0) != illustration(0, 1)
    with Image.open(BytesIO(illustration(0, 0))) as image:
        assert image.format == "PNG"
        assert image.size == (320, 480)
        assert not image.getexif()
