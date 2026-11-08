"""Verify reusable defaults, atomic snapshots and independent repair costs."""

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError
from sqlmodel import Session

from atelier_api.repair_orders import service as repair_service
from atelier_api.repair_templates import router as template_router
from atelier_api.repair_templates.models import RepairTemplate
from tests.integration.auth_helpers import sign_in

pytestmark = pytest.mark.integration
BASE = "/api/v1/repair-templates"
TEMPLATE = {
    "name": " Bridge fitting ",
    "description": " Fit a bridge ",
    "default_unit_price": "45.50",
}


@pytest.fixture
def template_setup(auth_factory):
    client = auth_factory()
    assert sign_in(client).status_code == 200
    customer = client.post(
        "/api/v1/customers", json={"first_name": "Template", "last_name": "Customer"}
    )
    assert customer.status_code == 201
    instrument = client.post("/api/v1/instruments", json={"type": "violin"})
    assert instrument.status_code == 201
    payload = {
        "customer_id": customer.json()["id"],
        "instrument_id": instrument.json()["id"],
    }
    return client, payload


def create_template(client, **changes):
    response = client.post(BASE, json={**TEMPLATE, **changes})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.e2e
def test_template_snapshot_remains_independent_after_template_and_repair_edits(
    template_setup, db_connection, accounts
):
    client, payload = template_setup
    template = create_template(client)
    assert template == {
        "id": template["id"],
        "name": "Bridge fitting",
        "description": "Fit a bridge",
        "default_unit_price": "45.50",
    }
    created = client.post(
        "/api/v1/repairs", json={**payload, "template_id": template["id"]}
    )
    assert created.status_code == 201, created.text
    order = created.json()
    path = f"/api/v1/repairs/{order['id']}"
    assert order["work_description"] == "Fit a bridge"
    costs = client.get(path + "/items").json()
    assert costs["total"] == "45.50"
    item = costs["items"][0]
    assert item["description"] == "Fit a bridge"
    assert item["quantity"] == "1.000"
    assert item["kind"] == "service"
    updated = client.patch(
        f"{BASE}/{template['id']}",
        json={"description": "New default", "default_unit_price": "60.00"},
    )
    assert updated.status_code == 200
    assert client.get(path).json()["work_description"] == "Fit a bridge"
    assert client.get(path + "/items").json() == costs
    future = client.post(
        "/api/v1/repairs", json={**payload, "template_id": template["id"]}
    )
    assert future.status_code == 201
    assert future.json()["work_description"] == "New default"
    assert (
        client.get(f"/api/v1/repairs/{future.json()['id']}/items").json()["total"]
        == "60.00"
    )
    assert (
        client.patch(path, json={"work_description": "Individual work"}).status_code
        == 200
    )
    assert (
        client.patch(
            f"{path}/items/{item['id']}",
            json={"unit_price": "50.00", "description": "Individual service"},
        ).status_code
        == 200
    )
    assert client.get(path + "/items").json()["total"] == "50.00"
    assert client.get(BASE).json()[0]["default_unit_price"] == "60.00"
    assert client.get(BASE).json()[0]["description"] == "New default"
    events = (
        db_connection.execute(
            text(
                "SELECT action, actor_id, details FROM audit_event WHERE resource_type = 'repair_template' ORDER BY id"
            )
        )
        .mappings()
        .all()
    )
    assert [event["action"] for event in events] == [
        "repair_template.created",
        "repair_template.updated",
    ]
    assert all(event["actor_id"] == accounts["employee"] for event in events)
    assert all(event["details"] == {} for event in events)
    details = db_connection.scalar(
        text(
            "SELECT details FROM audit_event WHERE action = 'repair_order.created' AND resource_id = :id"
        ),
        {"id": order["id"]},
    )
    assert details == {"template_id": template["id"]}


@pytest.mark.parametrize(
    "defaults,overrides,description,total",
    [
        (
            {},
            {"work_description": "Custom", "template_unit_price": "12.35"},
            "Custom",
            "12.35",
        ),
        ({}, {"template_unit_price": "0"}, "Fit a bridge", "0.00"),
        ({}, {"template_unit_price": None}, "Fit a bridge", None),
        ({"default_unit_price": None}, {}, "Fit a bridge", None),
        (
            {"default_unit_price": None},
            {"template_unit_price": "9.99"},
            "Fit a bridge",
            "9.99",
        ),
    ],
)
def test_template_overrides_and_absent_prices(
    template_setup, defaults, overrides, description, total
):
    client, payload = template_setup
    template = create_template(client, **defaults)
    response = client.post(
        "/api/v1/repair-orders",
        json={**payload, "template_id": template["id"], **overrides},
    )
    assert response.status_code == 201, response.text
    assert response.json()["work_description"] == description
    costs = client.get(f"/api/v1/repairs/{response.json()['id']}/items").json()
    if total is None:
        assert costs["items"] == []
        assert costs["total"] == "0.00"
    else:
        assert len(costs["items"]) == 1
        assert costs["total"] == total
    assert client.get(BASE).json()[0]["default_unit_price"] == defaults.get(
        "default_unit_price", "45.50"
    )


def test_template_listing_pagination_and_no_op_updates(template_setup, db_connection):
    client, _ = template_setup
    templates = [
        create_template(client, name=f"Template {index}") for index in range(3)
    ]
    page = client.get(BASE, params={"offset": 1, "limit": 1})
    assert page.status_code == 200
    assert page.json() == [templates[1]]
    assert page.headers["X-Total-Count"] == "3"
    assert page.headers["Cache-Control"] == "private, no-store"
    assert client.get(BASE, params={"offset": 3}).json() == []
    for query in [{"offset": -1}, {"limit": 0}, {"limit": 201}]:
        assert client.get(BASE, params=query).status_code == 422
    assert client.patch(f"{BASE}/{templates[0]['id']}", json={}).json() == templates[0]
    assert (
        db_connection.scalar(
            text(
                "SELECT count(*) FROM audit_event WHERE action = 'repair_template.updated'"
            )
        )
        == 0
    )
    cleared = client.patch(
        f"{BASE}/{templates[0]['id']}", json={"default_unit_price": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["default_unit_price"] is None
    assert cleared.json()["description"] == templates[0]["description"]


def test_unknown_template_does_not_create_repair_or_items(
    template_setup, db_connection
):
    client, payload = template_setup
    assert client.patch(BASE + "/999999", json={"name": "Unknown"}).status_code == 404
    response = client.post("/api/v1/repairs", json={**payload, "template_id": 999999})
    assert response.status_code == 404
    assert db_connection.scalar(text("SELECT count(*) FROM repair_order")) == 0
    assert db_connection.scalar(text("SELECT count(*) FROM repair_item")) == 0


@pytest.mark.parametrize(
    "module,action",
    [
        (template_router, "repair_template.created"),
        (template_router, "repair_template.updated"),
        (repair_service, "repair_item.created"),
    ],
)
def test_template_and_snapshot_audit_failures_are_atomic(
    template_setup, db_connection, monkeypatch, module, action
):
    client, payload = template_setup
    template = create_template(client)
    original = module.record_event

    def fail_after_audit(session, event, *args, **kwargs):
        original(session, event, *args, **kwargs)
        if event.value == action:
            raise RuntimeError("Injected audit failure")

    monkeypatch.setattr(module, "record_event", fail_after_audit)
    with pytest.raises(RuntimeError, match="Injected audit failure"):
        if action == "repair_template.updated":
            client.patch(
                f"{BASE}/{template['id']}", json={"default_unit_price": "99.00"}
            )
        elif module is template_router:
            client.post(BASE, json=TEMPLATE)
        else:
            client.post(
                "/api/v1/repairs", json={**payload, "template_id": template["id"]}
            )
    assert db_connection.scalar(text("SELECT count(*) FROM repair_template")) == 1
    assert client.get(BASE).json()[0]["default_unit_price"] == "45.50"
    assert db_connection.scalar(text("SELECT count(*) FROM repair_order")) == 0
    assert db_connection.scalar(text("SELECT count(*) FROM repair_item")) == 0
    assert (
        db_connection.scalar(
            text(
                "SELECT count(*) FROM audit_event WHERE action = 'repair_template.created'"
            )
        )
        == 1
    )
    assert (
        db_connection.scalar(
            text(
                "SELECT count(*) FROM audit_event WHERE action = 'repair_order.created'"
            )
        )
        == 0
    )


@pytest.mark.parametrize(
    "role,expected", [(None, 401), ("customer", 403), ("employee", 200), ("admin", 200)]
)
def test_templates_require_workshop_access(auth_factory, role, expected):
    client = auth_factory(customer_portal_auth_enabled=True)
    if role:
        assert sign_in(client, role).status_code == 200
    assert client.get(BASE).status_code == expected
    assert client.post(BASE, json=TEMPLATE).status_code == (
        201 if expected == 200 else expected
    )
    assert client.patch(BASE + "/999999", json={"name": "New"}).status_code == (
        404 if expected == 200 else expected
    )


def test_template_mutations_require_csrf(template_setup):
    client, _ = template_setup
    template = create_template(client)
    client.headers.pop("X-CSRF-Protection", None)
    assert client.post(BASE, json=TEMPLATE).status_code == 403
    assert (
        client.patch(f"{BASE}/{template['id']}", json={"name": "New"}).status_code
        == 403
    )


@pytest.mark.parametrize(
    "assignment",
    [
        "name = ' '",
        "description = ' '",
        "default_unit_price = -0.01",
        "default_unit_price = 10000000000",
    ],
)
def test_postgresql_template_constraints(template_setup, db_connection, assignment):
    client, _ = template_setup
    template = create_template(client)
    with pytest.raises((IntegrityError, DataError)), db_connection.begin_nested():
        db_connection.execute(
            text(f"UPDATE repair_template SET {assignment} WHERE id = :id"),
            {"id": template["id"]},
        )
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        stored = session.get(RepairTemplate, template["id"])
        assert stored.default_unit_price == Decimal("45.50")


def test_template_migration_refuses_destructive_downgrade(
    template_setup, db_connection
):
    from pathlib import Path

    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect
    from sqlalchemy.exc import DBAPIError

    client, _ = template_setup
    create_template(client)
    columns = {
        column["name"]: column
        for column in inspect(db_connection).get_columns("repair_template")
    }
    assert columns["default_unit_price"]["nullable"] is True
    price_type = columns["default_unit_price"]["type"]
    assert (price_type.precision, price_type.scale) == (12, 2)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_revision("c94e82a10637")
    assert revision is not None
    with (
        pytest.raises(DBAPIError, match="Refusing to delete repair templates"),
        db_connection.begin_nested(),
        Operations.context(MigrationContext.configure(db_connection)),
    ):
        revision.module.downgrade()
