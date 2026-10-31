"""Isolate private object storage behind an injectable synchronous interface."""

from collections.abc import Iterator
from hashlib import sha256
from typing import IO, Annotated, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from botocore.response import StreamingBody
from fastapi import Depends, HTTPException

from atelier_api.auth.dependencies import SecuritySettings
from atelier_api.settings import Settings


class StorageError(Exception):
    """Report an infrastructure failure without revealing provider details."""


class ObjectMissing(StorageError):
    """Indicate missing or inaccessible object contents."""


class ObjectConflict(StorageError):
    """Refuse to overwrite an existing object."""


class StorageStream(Protocol):
    """Expose only bounded reads and deterministic connection cleanup."""

    def read(self, size: int = -1, /) -> bytes: ...
    def close(self) -> None: ...


class R2Stream:
    """Translate provider errors even when reads fail after response headers."""

    def __init__(self, body: StreamingBody) -> None:
        self.body = body

    def read(self, size: int = -1, /) -> bytes:
        try:
            return self.body.read(size)
        except BotoCoreError, OSError:
            raise StorageError("Photograph stream unavailable") from None

    def close(self) -> None:
        self.body.close()


class StorageService(Protocol):
    """Support bounded, private binary operations without public object URLs."""

    @property
    def namespace(self) -> str:
        """Identify the storage location independently of credential rotation."""
        ...

    def upload(
        self, key: str, source: IO[bytes], size: int, content_type: str
    ) -> None: ...
    def download(self, key: str) -> StorageStream: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...


class R2Storage:
    """Use explicit credentials; never fall back to ambient AWS credentials."""

    def __init__(self, config: Settings) -> None:
        if (
            not config.photo_storage_enabled
            or config.r2_access_key_id is None
            or config.r2_secret_access_key is None
            or config.r2_bucket_name is None
        ):
            raise StorageError("Photo storage is not configured")
        self.bucket = config.r2_bucket_name
        self.namespace = sha256(
            f"{config.r2_endpoint_url}/{self.bucket}".encode()
        ).hexdigest()
        self.client = boto3.client(
            "s3",
            endpoint_url=config.r2_endpoint_url,
            aws_access_key_id=config.r2_access_key_id.get_secret_value(),
            aws_secret_access_key=config.r2_secret_access_key.get_secret_value(),
            region_name="auto",
            config=Config(
                signature_version="s3v4",
                connect_timeout=5,
                read_timeout=15,
                retries={"max_attempts": 2, "mode": "standard"},
                s3={"addressing_style": "path"},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    def close(self) -> None:
        self.client.close()

    def upload(self, key: str, source: IO[bytes], size: int, content_type: str) -> None:
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=source,
                ContentLength=size,
                ContentType=content_type,
                IfNoneMatch="*",
                CacheControl="private, no-store",
            )
        except ClientError as error:
            if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 412:
                raise ObjectConflict from None
            raise StorageError from None
        except BotoCoreError, OSError:
            raise StorageError from None

    def download(self, key: str) -> StorageStream:
        try:
            return R2Stream(self.client.get_object(Bucket=self.bucket, Key=key)["Body"])
        except ClientError as error:
            if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") in {
                403,
                404,
            }:
                raise ObjectMissing from None
            raise StorageError from None
        except BotoCoreError, OSError:
            raise StorageError from None

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except BotoCoreError, ClientError, OSError:
            raise StorageError from None

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as error:
            if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                return False
            raise StorageError from None
        except BotoCoreError, OSError:
            raise StorageError from None


def get_storage(config: SecuritySettings) -> Iterator[StorageService]:
    """Construct storage only for operations that require object access."""
    if not config.photo_storage_enabled:
        raise HTTPException(503, "Photo storage is not configured")
    storage = R2Storage(config)
    try:
        yield storage
    finally:
        storage.close()


StorageDep = Annotated[StorageService, Depends(get_storage)]
