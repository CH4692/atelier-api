from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from atelier_api.instruments.models import Instrument
from tests.integration.auth_helpers import sign_in

pytestmark = pytest.mark.integration


def test_qr_target_is_stable_and_host_headers_are_ignored(auth_factory, db_connection):
    client = auth_factory(public_qr_base_url="https://records.example.test")
    sign_in(client)
    record = client.post(
        "/api/v1/instruments", json={"type": "violin", "notes": "Private information"}
    ).json()
    path = f"/api/v1/instruments/{record['id']}/qr-code.svg"
    response = client.get(
        path,
        headers={
            "Host": "evil.example",
            "Forwarded": "host=evil.example",
            "X-Forwarded-Host": "evil.example",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-location"].startswith(
        "https://records.example.test/i/"
    )
    response = client.get(
        path,
        headers={"Forwarded": "host=evil.example", "X-Forwarded-Host": "evil.example"},
    )
    assert response.status_code == 200
    target = response.headers["content-location"]
    assert target.startswith("https://records.example.test/i/")
    public_id = UUID(target.rsplit("/", 1)[1])
    assert public_id.version == 4
    assert "Private information" not in response.text
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert "attachment" in response.headers["content-disposition"]
    scan_path = f"/i/{public_id}"
    resolved = client.get(scan_path, follow_redirects=False)
    assert resolved.status_code == 307
    assert resolved.headers["location"] == f"/api/v1/instruments/{record['id']}"
    assert client.get(scan_path).json() == record
    client.patch(f"/api/v1/instruments/{record['id']}", json={"notes": "Changed"})
    assert client.get(path).headers["content-location"] == target
    assert (
        client.patch(
            f"/api/v1/instruments/{record['id']}", json={"public_id": str(uuid4())}
        ).status_code
        == 422
    )
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        stored = session.exec(select(Instrument)).one()
        assert stored.public_id == public_id
        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    "UPDATE instrument SET public_id = gen_random_uuid() WHERE id = :id"
                ),
                {"id": record["id"]},
            )
            session.commit()
        session.rollback()


@pytest.mark.parametrize(
    "role,expected", [(None, 401), ("customer", 403), ("employee", 404), ("admin", 404)]
)
@pytest.mark.parametrize(
    "path",
    [
        "/i/9f8d65ec-e35b-4f33-9d83-3840f0f0b888",
        "/api/v1/instruments/999999/qr-code.svg",
    ],
)
def test_qr_requires_workshop_access(auth_factory, role, expected, path):
    client = auth_factory(customer_portal_auth_enabled=True)
    if role:
        sign_in(client, role)
    assert client.get(path).status_code == expected


def test_missing_production_origin_prevents_printing(auth_factory):
    client = auth_factory()
    sign_in(client)
    record = client.post("/api/v1/instruments", json={"type": "bow"}).json()
    response = client.get(f"/api/v1/instruments/{record['id']}/qr-code.svg")
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/json"


def test_database_generates_distinct_ids_for_direct_inserts(db_connection):
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        ids = (
            session.execute(
                text(
                    "INSERT INTO instrument (type, ownership) VALUES ('violin', 'workshop'), "
                    "('cello', 'workshop') RETURNING public_id"
                )
            )
            .scalars()
            .all()
        )
        assert len(set(ids)) == 2
        assert all(value.version == 4 for value in ids)
        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    "INSERT INTO instrument (type, ownership, public_id) "
                    "VALUES ('bow', 'workshop', :public_id)"
                ),
                {"public_id": ids[0]},
            )
        session.rollback()
