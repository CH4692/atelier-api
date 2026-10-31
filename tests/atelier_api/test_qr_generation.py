from unittest.mock import patch
from uuid import uuid4
from xml.etree import ElementTree

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from atelier_api.instruments.qr import instrument_url, qr_svg
from atelier_api.settings import Settings


def config(**changes):
    return Settings(_env_file=None, database_url="sqlite://", **changes)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "https://",
        "https://user:pw@example.test",
        "https://example.test/",
        "https://example.test/path",
        "https://example.test?q=x",
        "https://example.test#x",
        "https://example.test:bad",
        "https://example.test\\evil",
        "https://example.test\n",
    ],
)
def test_invalid_qr_origin(value):
    with pytest.raises(ValidationError):
        config(public_qr_base_url=value)


def test_https_required_only_in_production():
    assert config(public_qr_base_url="http://localhost:8000").public_qr_base_url
    with pytest.raises(ValidationError, match="must use HTTPS"):
        config(
            environment="production",
            frontend_origins=["https://example.test"],
            public_qr_base_url="http://example.test",
        )


def test_missing_origin_disables_qr_generation():
    with pytest.raises(HTTPException) as error:
        instrument_url(config(), uuid4())
    assert error.value.status_code == 503


def test_svg_encodes_only_canonical_url():
    public_id = uuid4()
    url = instrument_url(
        config(public_qr_base_url="https://records.example.test"), public_id
    )
    assert url == f"https://records.example.test/i/{public_id}"
    with patch(
        "atelier_api.instruments.qr.qrcode.QRCode", autospec=True
    ) as constructor:
        qr_svg(url)
        constructor.return_value.add_data.assert_called_once_with(url)
        assert constructor.call_args.kwargs["border"] == 4
    root = ElementTree.fromstring(qr_svg(url))
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.find("{http://www.w3.org/2000/svg}path") is not None


def test_request_host_cannot_change_printed_target(client, mock_session, monkeypatch):
    from atelier_api.instruments.models import Instrument
    from atelier_api.main import app

    instrument = Instrument(id=42, type="violin")
    mock_session.get.return_value = instrument
    monkeypatch.setattr(
        app.state, "settings", config(public_qr_base_url="https://records.example.test")
    )
    response = client.get(
        "/api/v1/instruments/42/qr-code.svg",
        headers={
            "Host": "attacker.example",
            "Forwarded": "host=attacker.example;proto=http",
            "X-Forwarded-Host": "attacker.example",
        },
    )
    assert response.status_code == 200
    assert (
        response.headers["content-location"]
        == f"https://records.example.test/i/{instrument.public_id}"
    )


def test_new_instruments_receive_distinct_random_ids():
    from atelier_api.instruments.models import Instrument

    first = Instrument(type="violin").public_id
    second = Instrument(type="violin").public_id
    assert first.version == second.version == 4
    assert first != second
