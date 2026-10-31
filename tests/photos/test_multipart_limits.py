import asyncio

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.formparsers import MultiPartException
from starlette.requests import Request

from atelier_api.photos.limits import PhotoParser, UploadLimitError, parse_photos


async def stream_bytes(data):
    for offset in range(0, len(data), 5):
        yield data[offset : offset + 5]


def multipart(data=b"data", end=True):
    return (
        b'--test\r\nContent-Disposition: form-data; name="files"; filename="photo.png"\r\n\r\n'
        + data
        + (b"\r\n--test--\r\n" if end else b"")
    )


def test_per_file_limit_aborts_parser_and_closes_spools(monkeypatch):
    monkeypatch.setattr("atelier_api.photos.limits.MAX_PHOTO_BYTES", 3)
    parser = PhotoParser(
        Headers({"content-type": "multipart/form-data; boundary=test"}),
        stream_bytes(multipart()),
    )
    with pytest.raises(UploadLimitError):
        asyncio.run(parser.parse())
    assert parser._files_to_close_on_error
    assert all(resource.closed for resource in parser._files_to_close_on_error)


def test_truncated_body_closes_spools():
    parser = PhotoParser(
        Headers({"content-type": "multipart/form-data; boundary=test"}),
        stream_bytes(multipart(end=False)),
    )
    with pytest.raises(MultiPartException):
        asyncio.run(parser.parse())
    assert all(resource.closed for resource in parser._files_to_close_on_error)


def test_disconnect_closes_spools():
    async def disconnected():
        yield multipart(end=False)
        raise ConnectionError("Disconnected")

    parser = PhotoParser(
        Headers({"content-type": "multipart/form-data; boundary=test"}), disconnected()
    )
    with pytest.raises(ConnectionError):
        asyncio.run(parser.parse())
    assert all(resource.closed for resource in parser._files_to_close_on_error)


def test_missing_content_length_cannot_bypass_total_limit(monkeypatch):
    monkeypatch.setattr("atelier_api.photos.limits.MAX_REQUEST_BYTES", 30)

    async def receive():
        return {"type": "http.request", "body": multipart(), "more_body": False}

    request = Request(
        {
            "type": "http",
            "headers": [(b"content-type", b"multipart/form-data; boundary=test")],
        },
        receive=receive,
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(parse_photos(request))
    assert error.value.status_code == 413


def test_openapi_advertises_multiple_bounded_files():
    from atelier_api.main import app

    schema = app.openapi()
    operation = schema["paths"]["/api/v1/instruments/{instrument_id}/photos"]["post"]
    files = operation["requestBody"]["content"]["multipart/form-data"]["schema"][
        "properties"
    ]["files"]
    assert files["maxItems"] == 10
    assert files["items"]["format"] == "binary"
    assert operation["security"]
