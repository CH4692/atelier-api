"""Bound multipart files during parsing, before writing oversized parts to disk."""

from collections.abc import AsyncGenerator

from fastapi import HTTPException, Request
from python_multipart.exceptions import MultipartParseError
from starlette.datastructures import FormData
from starlette.formparsers import MultiPartException, MultiPartParser

from .models import MAX_PHOTO_BYTES, MAX_PHOTOS, MAX_REQUEST_BYTES


class UploadLimitError(MultiPartException):
    """Abort parsing and close spooled resources when a byte limit is exceeded."""


class PhotoParser(MultiPartParser):
    """Extend Starlette because max_part_size limits text fields, not files.

    Use parser callbacks to reject files before writing excess bytes. Keep the
    small dependency-specific cleanup here and test error/disconnect paths.
    """

    def on_part_begin(self) -> None:
        super().on_part_begin()
        self.part_bytes = 0
        self.header_bytes = 0

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self.header_bytes += end - start
        if self.header_bytes > 8192:
            raise UploadLimitError("Photo part headers exceed 8 KB")
        super().on_header_field(data, start, end)

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self.header_bytes += end - start
        if self.header_bytes > 8192:
            raise UploadLimitError("Photo part headers exceed 8 KB")
        super().on_header_value(data, start, end)

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        self.part_bytes += end - start
        if self.part_bytes > MAX_PHOTO_BYTES:
            raise UploadLimitError("Photograph exceeds 10 MB")
        super().on_part_data(data, start, end)

    def on_end(self) -> None:
        self.complete = True

    async def parse(self) -> FormData:
        self.complete = False
        try:
            result = await super().parse()
            if not self.complete:
                raise MultiPartException("Incomplete multipart body")
            return result
        except BaseException:
            # Starlette only closes parts on MultiPartException; also handle
            # cancellation, disconnects and malformed parser input.
            for resource in self._files_to_close_on_error:
                resource.close()
            raise


async def parse_photos(request: Request) -> FormData:
    """Enforce total and per-file limits even without a Content-Length header."""
    try:
        length = int(request.headers.get("content-length", "0"))
    except ValueError:
        raise HTTPException(400, "Invalid request length") from None
    if length < 0 or length > MAX_REQUEST_BYTES:
        raise HTTPException(413, "Photo request exceeds 101 MB")

    async def bounded_stream() -> AsyncGenerator[bytes]:
        count = 0
        async for chunk in request.stream():
            count += len(chunk)
            if count > MAX_REQUEST_BYTES:
                raise UploadLimitError("Photo request exceeds 101 MB")
            for offset in range(0, len(chunk), 65536):
                yield chunk[offset : offset + 65536]
        yield b""

    parser = PhotoParser(
        request.headers, bounded_stream(), max_files=MAX_PHOTOS, max_fields=0
    )
    try:
        return await parser.parse()
    except UploadLimitError:
        raise HTTPException(413, "Photo upload limit exceeded") from None
    except MultiPartException as error:
        status = 413 if error.message.startswith("Too many files") else 422
        raise HTTPException(status, "Invalid multipart photographs") from None
    except MultipartParseError:
        raise HTTPException(422, "Invalid multipart photographs") from None
