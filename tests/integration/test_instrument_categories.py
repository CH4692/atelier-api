"""Verify category filtering, measurement persistence and backward-compatible migration."""

from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from atelier_api.instruments.schemas import InstrumentType

pytestmark = pytest.mark.integration


def test_bows_and_string_instruments_filter_independently_of_ownership(postgres_client):
    instruments = []
    for kind in InstrumentType:
        payload = {"type": kind.value}
        if kind == InstrumentType.BOW:
            payload.update({"ownership": "workshop", "bow_weight_g": 60.5})
        else:
            payload["body_length_mm"] = 355
        response = postgres_client.post("/api/v1/instruments", json=payload)
        assert response.status_code == 201
        record = response.json()
        instruments.append(record)
        assert (
            postgres_client.get(f"/api/v1/instruments/{record['id']}").json() == record
        )
    for record in instruments:
        response = postgres_client.get(
            "/api/v1/instruments", params={"type": record["type"]}
        )
        assert response.status_code == 200 and response.json() == [record]
    assert (
        postgres_client.get(
            "/api/v1/instruments", params={"type": "bow", "ownership": "customer"}
        ).json()
        == []
    )
    assert postgres_client.get(
        "/api/v1/instruments", params={"type": "bow", "ownership": "workshop"}
    ).json() == [instruments[-1]]


def test_category_change_requires_explicit_clearing_and_preserves_ownership_history(
    postgres_client,
):
    created = postgres_client.post(
        "/api/v1/instruments", json={"type": "violin", "body_length_mm": 355}
    ).json()
    path = f"/api/v1/instruments/{created['id']}"
    history = postgres_client.get(f"{path}/ownership-history").json()
    assert postgres_client.patch(path, json={"type": "bow"}).status_code == 422
    assert postgres_client.get(path).json() == created
    response = postgres_client.patch(
        path, json={"type": "bow", "body_length_mm": None, "bow_weight_g": 60.5}
    )
    assert response.status_code == 200
    assert (
        response.json()["body_length_mm"] is None
        and response.json()["bow_weight_g"] == 60.5
    )
    assert postgres_client.get(f"{path}/ownership-history").json() == history
    assert postgres_client.patch(path, json={"type": "cello"}).status_code == 422
    assert (
        postgres_client.patch(
            path, json={"type": "cello", "bow_weight_g": None}
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "kind,body_length,bow_weight",
    [
        ("bow", 355, None),
        ("violin", None, 60),
        ("bow", None, 0),
        ("violin", -1, None),
        ("bow", None, float("inf")),
        ("violin", float("nan"), None),
        ("invalid", None, None),
    ],
)
def test_database_enforces_categories_and_measurements(
    db_connection, kind, body_length, bow_weight
):
    with pytest.raises(IntegrityError), db_connection.begin_nested():
        db_connection.execute(
            text(
                "INSERT INTO instrument (type, ownership, body_length_mm, bow_weight_g) VALUES (:kind, 'unassigned', :body, :weight)"
            ),
            {"kind": kind, "body": body_length, "weight": bow_weight},
        )


def test_migration_preserves_legacy_records_and_refuses_lossy_downgrade(db_connection):
    schema = f"legacy_categories_{uuid4().hex}"
    db_connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    db_connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
    db_connection.execute(
        text(
            "CREATE TABLE instrument (id integer PRIMARY KEY, type varchar(32) NOT NULL, CONSTRAINT ck_instrument_type CHECK (type IN ('violin','viola','cello','double_bass')))"
        )
    )
    db_connection.execute(
        text(
            "INSERT INTO instrument VALUES (1,'violin'), (2,'viola'), (3,'cello'), (4,'double_bass')"
        )
    )
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("c64f95a37d12")
    assert revision is not None
    with Operations.context(MigrationContext.configure(db_connection)):
        revision.module.upgrade()
    assert db_connection.execute(
        text("SELECT id,type,body_length_mm,bow_weight_g FROM instrument ORDER BY id")
    ).all() == [
        (1, "violin", None, None),
        (2, "viola", None, None),
        (3, "cello", None, None),
        (4, "double_bass", None, None),
    ]
    db_connection.execute(
        text("INSERT INTO instrument (id,type,bow_weight_g) VALUES (5,'bow',60.5)")
    )
    with (
        pytest.raises(DBAPIError),
        db_connection.begin_nested(),
        Operations.context(MigrationContext.configure(db_connection)),
    ):
        revision.module.downgrade()
    assert (
        db_connection.scalar(text("SELECT bow_weight_g FROM instrument WHERE id=5"))
        == 60.5
    )
    db_connection.execute(text("DELETE FROM instrument WHERE id=5"))
    with Operations.context(MigrationContext.configure(db_connection)):
        revision.module.downgrade()
    assert db_connection.execute(
        text("SELECT id,type FROM instrument ORDER BY id")
    ).all() == [(1, "violin"), (2, "viola"), (3, "cello"), (4, "double_bass")]
