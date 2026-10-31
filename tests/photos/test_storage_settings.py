import pytest
from pydantic import ValidationError

from atelier_api.settings import Settings

OPTIONS = {
    "r2_endpoint_url": "https://account.eu.r2.cloudflarestorage.com",
    "r2_access_key_id": "test-access-id",
    "r2_secret_access_key": "test-secret-value",
    "r2_bucket_name": "atelier-api-dev",
}


def config(**changes):
    return Settings(_env_file=None, database_url="sqlite://", **changes)


def test_storage_is_optional_and_credentials_are_redacted():
    assert not config().photo_storage_enabled
    configured = config(**OPTIONS)
    assert configured.photo_storage_enabled
    assert "test-access-id" not in repr(configured)
    assert "test-secret-value" not in repr(configured)
    assert "test-secret-value" not in configured.model_dump_json()


@pytest.mark.parametrize("missing", list(OPTIONS))
def test_partial_configuration_fails(missing):
    values = {key: value for key, value in OPTIONS.items() if key != missing}
    with pytest.raises(ValidationError, match="All four"):
        config(**values)


@pytest.mark.parametrize(
    "field,value",
    [
        ("r2_endpoint_url", "http://example.test"),
        ("r2_endpoint_url", "https://user:secret@example.test"),
        ("r2_endpoint_url", "https://example.test/bucket"),
        ("r2_endpoint_url", "https://example.test:bad"),
        ("r2_endpoint_url", "https://example.test\\evil"),
        ("r2_access_key_id", " "),
        ("r2_secret_access_key", ""),
        ("r2_bucket_name", "../other"),
    ],
)
def test_invalid_storage_configuration(field, value):
    with pytest.raises(ValidationError):
        config(**{**OPTIONS, field: value})
