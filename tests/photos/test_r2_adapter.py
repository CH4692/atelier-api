from io import BytesIO

import pytest
from botocore.exceptions import EndpointConnectionError, ReadTimeoutError
from botocore.response import StreamingBody
from botocore.stub import Stubber

from atelier_api.photos.storage import (
    ObjectConflict,
    ObjectMissing,
    R2Storage,
    R2Stream,
    StorageError,
)
from atelier_api.settings import Settings


@pytest.fixture
def r2():
    config = Settings(
        _env_file=None,
        database_url="sqlite://",
        r2_endpoint_url="https://storage.example.test",
        r2_bucket_name="atelier-api-dev",
        r2_access_key_id="fake-access",
        r2_secret_access_key="fake-secret",
    )
    storage = R2Storage(config)
    try:
        yield storage
    finally:
        storage.close()


def test_adapter_uses_private_conditional_writes_and_streaming_reads(r2):
    with BytesIO(b"data") as source, Stubber(r2.client) as stubber:
        stubber.add_response(
            "put_object",
            {},
            {
                "Bucket": "atelier-api-dev",
                "Key": "key",
                "Body": source,
                "ContentLength": 4,
                "ContentType": "image/png",
                "IfNoneMatch": "*",
                "CacheControl": "private, no-store",
            },
        )
        r2.upload("key", source, 4, "image/png")
        stubber.add_response(
            "head_object", {}, {"Bucket": "atelier-api-dev", "Key": "key"}
        )
        assert r2.exists("key")
        stubber.add_response(
            "get_object",
            {"Body": StreamingBody(BytesIO(b"data"), 4)},
            {"Bucket": "atelier-api-dev", "Key": "key"},
        )
        stream = r2.download("key")
        assert stream.read(2) == b"da"
        assert stream.read(2) == b"ta"
        stream.close()
        stubber.add_response(
            "delete_object", {}, {"Bucket": "atelier-api-dev", "Key": "key"}
        )
        r2.delete("key")
        stubber.assert_no_pending_responses()
    assert r2.client.meta.config.region_name == "auto"
    assert r2.client.meta.config.signature_version == "s3v4"
    assert r2.client.meta.config.request_checksum_calculation == "when_required"


@pytest.mark.parametrize(
    "operation,code,status,expected",
    [
        ("put_object", "PreconditionFailed", 412, ObjectConflict),
        ("put_object", "InternalError", 500, StorageError),
        ("get_object", "NoSuchKey", 404, ObjectMissing),
        ("get_object", "AccessDenied", 403, ObjectMissing),
        ("get_object", "InternalError", 500, StorageError),
        ("delete_object", "AccessDenied", 403, StorageError),
        ("head_object", "AccessDenied", 403, StorageError),
    ],
)
def test_adapter_errors_are_sanitized(r2, operation, code, status, expected):
    with Stubber(r2.client) as stubber, BytesIO(b"x") as source:
        stubber.add_client_error(
            operation,
            service_error_code=code,
            service_message="Sensitive provider details",
            http_status_code=status,
        )
        with pytest.raises(expected) as error:
            if operation == "put_object":
                r2.upload("key", source, 1, "image/png")
            elif operation == "get_object":
                r2.download("key")
            elif operation == "delete_object":
                r2.delete("key")
            else:
                r2.exists("key")
        assert "Sensitive" not in str(error.value)


def test_exists_missing_returns_false_and_delete_is_idempotent(r2):
    with Stubber(r2.client) as stubber:
        stubber.add_client_error(
            "head_object", service_error_code="NotFound", http_status_code=404
        )
        assert not r2.exists("missing")
        stubber.add_response("delete_object", {})
        r2.delete("missing")


def test_connection_failure_is_sanitized(r2, monkeypatch):
    def fail(**kwargs):
        raise EndpointConnectionError(endpoint_url="https://private.example.test")

    monkeypatch.setattr(r2.client, "get_object", fail)
    with pytest.raises(StorageError) as error:
        r2.download("key")
    assert "private" not in str(error.value)


def test_stream_failure_is_sanitized(monkeypatch):
    with BytesIO(b"test") as source:
        body = StreamingBody(source, 4)

        def fail(*args):
            raise ReadTimeoutError(endpoint_url="https://private.example.test")

        monkeypatch.setattr(body, "read", fail)
        stream = R2Stream(body)
        with pytest.raises(StorageError) as error:
            stream.read(4)
        assert "private" not in str(error.value)
        stream.close()
