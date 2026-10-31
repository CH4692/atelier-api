"""Check validation, missing resources, upload bounds and safe history projections."""

from datetime import UTC, datetime
from hashlib import sha256

import pytest

from atelier_api.instruments.models import Instrument
from atelier_api.main import app
from atelier_api.repair_orders.models import (
    MAX_DOCUMENT_BYTES,
    RepairDocument,
    RepairOrder,
)
from atelier_api.repair_orders.schemas import RepairOrderCreate
from atelier_api.repair_orders.service import repair_details


@pytest.fixture
def order():
    return RepairOrder(
        id=7,
        instrument_id=1,
        work_description="Replaced bridge",
        performed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_missing_history_instrument_returns_404(client, mock_session):
    mock_session.get.return_value = None
    assert client.get("/api/v1/instruments/999/history").status_code == 404
    mock_session.exec.assert_not_called()


def test_empty_history_returns_instrument_details(client, mock_session):
    mock_session.get.return_value = Instrument(id=1, type="violin")
    mock_session.exec.return_value.one.return_value = 0
    mock_session.exec.return_value.all.return_value = []
    response = client.get("/api/v1/instruments/1/history")
    assert response.status_code == 200
    assert response.json()["instrument"]["id"] == 1
    assert response.json()["repair_orders"] == []
    assert response.headers["X-Total-Count"] == "0"
    mock_session.execute.assert_not_called()


def test_history_queries_metadata_without_document_content(mock_session, order):
    mock_session.execute.return_value.mappings.return_value.all.return_value = []
    result = repair_details(mock_session, [order])
    assert result[0].work_description == order.work_description
    assert result[0].documents == []
    query = str(mock_session.execute.call_args.args[0])
    assert "repair_document.content" not in query
    assert "repair_document.repair_order_id IN" in query
    mock_session.execute.assert_called_once()


@pytest.mark.parametrize(
    "payload",
    [
        {"work_description": " ", "performed_at": "2026-01-01T00:00:00Z"},
        {"work_description": "x" * 10001, "performed_at": "2026-01-01T00:00:00Z"},
        {"work_description": "Work", "performed_at": "2026-01-01T00:00:00"},
        {"work_description": "Work"},
        {
            "work_description": "Work",
            "performed_at": "2026-01-01T00:00:00Z",
            "instrument_id": 99,
        },
    ],
)
def test_invalid_repair_payload_returns_422(client, mock_session, payload):
    assert (
        client.post("/api/v1/instruments/1/repair-orders", json=payload).status_code
        == 422
    )
    mock_session.add.assert_not_called()


def test_repair_dates_are_normalized_to_utc():
    data = RepairOrderCreate(
        work_description="  Replaced bridge  ", performed_at="2026-01-01T12:00:00+02:00"
    )
    assert data.work_description == "Replaced bridge"
    assert data.performed_at == datetime(2026, 1, 1, 10, tzinfo=UTC)
    assert data.performed_at.tzinfo == UTC


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"offset": "1.5"}]
)
def test_history_rejects_invalid_pagination(client, mock_session, params):
    assert client.get("/api/v1/instruments/1/history", params=params).status_code == 422
    mock_session.get.assert_not_called()


def test_missing_document_and_order_return_404(client, mock_session):
    mock_session.get.return_value = None
    assert client.get("/api/v1/repair-documents/999/content").status_code == 404
    assert client.get("/api/v1/repair-orders/999").status_code == 404
    assert (
        client.post(
            "/api/v1/repair-orders/999/documents?filename=test.pdf", content=b"data"
        ).status_code
        == 404
    )


def test_upload_rejects_multipart_instead_of_storing_its_envelope(
    client, mock_session, order
):
    mock_session.get.return_value = order
    assert (
        client.post(
            "/api/v1/repair-orders/7/documents?filename=test.pdf",
            files={"file": ("test.pdf", b"data")},
        ).status_code
        == 415
    )
    mock_session.add.assert_not_called()


@pytest.mark.parametrize(
    "data,expected", [(b"", 422), (b"x" * (MAX_DOCUMENT_BYTES + 1), 413)]
)
def test_upload_size_bounds_do_not_write(client, mock_session, order, data, expected):
    mock_session.get.return_value = order
    response = client.post(
        "/api/v1/repair-orders/7/documents?filename=test.pdf", content=data
    )
    assert response.status_code == expected
    mock_session.add.assert_not_called()
    mock_session.commit.assert_not_called()


@pytest.mark.parametrize("filename", [" ", "..", "bad\nname", "x" * 256])
def test_upload_rejects_invalid_filename(client, mock_session, order, filename):
    mock_session.get.return_value = order
    assert (
        client.post(
            "/api/v1/repair-orders/7/documents",
            params={"filename": filename},
            content=b"data",
        ).status_code
        == 422
    )
    mock_session.add.assert_not_called()


def test_document_download_is_an_attachment_without_caching(client, mock_session):
    data = b"<script>untrusted content</script>"
    mock_session.get.return_value = RepairDocument(
        id=9,
        repair_order_id=7,
        filename="Reparatur ü.html",
        size_bytes=len(data),
        sha256=sha256(data).hexdigest(),
        content=data,
    )
    response = client.get("/api/v1/repair-documents/9/content")
    assert response.content == data
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "no-store" in response.headers["cache-control"]


def test_history_and_document_upload_are_documented():
    schema = app.openapi()
    history = schema["paths"]["/api/v1/instruments/{instrument_id}/history"]["get"]
    assert (
        history["responses"]["200"]["headers"]["X-Total-Count"]["schema"]["type"]
        == "integer"
    )
    upload = schema["paths"]["/api/v1/repair-orders/{order_id}/documents"]["post"]
    assert upload["requestBody"]["required"] is True
    assert "application/octet-stream" in upload["requestBody"]["content"]
