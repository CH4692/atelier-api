"""Provision optional xdist databases only on the explicitly configured test server."""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError


@contextmanager
def worker_database(url: URL, worker_id: str) -> Iterator[URL]:
    """Keep serial behavior and isolate every parallel worker in a disposable DB."""
    if url.get_backend_name() != "postgresql" or not (url.database or "").endswith(
        "_test"
    ):
        raise ValueError("Parallel tests require an explicit PostgreSQL _test database")
    if worker_id == "master":
        yield url
        return
    if re.fullmatch(r"gw[0-9]{1,6}", worker_id) is None:
        raise ValueError("Invalid pytest worker identifier")
    name = f"{(url.database or '')[:-5][:24]}_{worker_id}_{uuid4().hex[:8]}_test"
    catalog = create_engine(url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    quoted = catalog.dialect.identifier_preparer.quote_identifier(name)
    created = False
    try:
        try:
            with catalog.connect() as connection:
                connection.exec_driver_sql(f"CREATE DATABASE {quoted}")
                created = True
                connection.exec_driver_sql(
                    f"ALTER DATABASE {quoted} SET timezone = 'UTC'"
                )
        except SQLAlchemyError:
            pytest.fail(
                "Cannot create isolated worker database. Use a disposable test server with CREATEDB permission, or run with -n 0.",
                pytrace=False,
            )
        yield url.set(database=name)
    finally:
        try:
            if created:
                with catalog.connect() as connection:
                    connection.exec_driver_sql(f"DROP DATABASE {quoted} WITH (FORCE)")
        finally:
            catalog.dispose()
