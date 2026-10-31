"""Provide deterministic photo data and private in-memory storage for tests."""

from io import BytesIO
from typing import IO

from PIL import Image

from atelier_api.photos.storage import ObjectConflict, ObjectMissing, StorageError


def image_bytes(format: str = "PNG", **options) -> bytes:
    output = BytesIO()
    with Image.new("RGB", (16, 12), "red") as image:
        image.save(output, format=format, **options)
    return output.getvalue()


class FakeStorage:
    """Simulate R2 failures without credentials or network calls."""

    def __init__(self) -> None:
        self.namespace = "fake-private-storage"
        self.objects: dict[str, bytes] = {}
        self.uploads: list[str] = []
        self.deletes: list[str] = []
        self.downloads: list[str] = []
        self.fail_upload_number: int | None = None
        self.fail_delete = False
        self.fail_download = False
        self.closed_streams: list[BytesIO] = []

    def upload(self, key: str, source: IO[bytes], size: int, content_type: str) -> None:
        if key in self.objects:
            raise ObjectConflict
        self.uploads.append(key)
        self.objects[key] = source.read()
        assert len(self.objects[key]) == size
        if len(self.uploads) == self.fail_upload_number:
            raise StorageError("Simulated private infrastructure failure")

    def download(self, key: str) -> BytesIO:
        self.downloads.append(key)
        if self.fail_download:
            raise StorageError("Simulated private infrastructure failure")
        if key not in self.objects:
            raise ObjectMissing
        stream = BytesIO(self.objects[key])
        self.closed_streams.append(stream)
        return stream

    def delete(self, key: str) -> None:
        self.deletes.append(key)
        if self.fail_delete:
            raise StorageError("Simulated private infrastructure failure")
        self.objects.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self.objects
