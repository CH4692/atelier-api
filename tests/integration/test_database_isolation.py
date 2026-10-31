"""Verify real commit boundaries and the optional parallel worker database."""

import os

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlmodel import Session

from atelier_api.customers.models import Customer


def test_application_commit_does_not_escape_test_transaction(
    db_connection, postgres_engine
):
    with Session(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        session.add(Customer(first_name="Isolated", last_name="Commit"))
        session.commit()
    assert db_connection.scalar(text("SELECT count(*) FROM customer")) == 1
    with postgres_engine.connect() as independent:
        assert independent.scalar(text("SELECT count(*) FROM customer")) == 0
    assert db_connection.in_transaction()


def test_parallel_workers_use_a_separate_test_database(postgres_engine, worker_id):
    base = make_url(os.environ["TEST_DATABASE_URL"])
    with postgres_engine.connect() as connection:
        actual = connection.scalar(text("SELECT current_database()"))
    assert actual.endswith("_test")
    if worker_id == "master":
        assert actual == base.database
    else:
        assert actual != base.database
        assert f"_{worker_id}_" in actual
