"""Exercise safe CLI defaults without contacting configured developer services."""

import json
from unittest.mock import MagicMock

import pytest

from atelier_api.demo import cli


def test_dry_run_has_expected_counts_and_never_connects(monkeypatch, capsys):
    engine = MagicMock()
    storage = MagicMock()
    monkeypatch.setattr(cli, "create_engine", engine)
    monkeypatch.setattr(cli, "R2Storage", storage)
    cli.main(["--dry-run", "--as-of", "2026-11-09", "--with-photos"])
    result = json.loads(capsys.readouterr().out)
    assert result["dry_run"] is True
    assert result["counts"]["photos"] == 50
    assert result["counts"]["users"] == 6
    assert result["counts"]["invoices"] == 0
    engine.assert_not_called()
    storage.assert_not_called()


def test_cli_does_not_fall_back_to_database_url(monkeypatch, capsys):
    monkeypatch.delenv("ARTELIER_DEMO_DATABASE_URL", raising=False)
    engine = MagicMock()
    monkeypatch.setattr(cli, "create_engine", engine)
    with pytest.raises(SystemExit) as error:
        cli.main(["--confirm-demo-data"])
    assert error.value.code == 1
    assert "ARTELIER_DEMO_DATABASE_URL" in capsys.readouterr().err
    engine.assert_not_called()


def test_confirmation_is_required_before_connecting(monkeypatch, capsys):
    monkeypatch.setenv(
        "ARTELIER_DEMO_DATABASE_URL", "postgresql+psycopg://localhost/atelier_demo"
    )
    engine = MagicMock()
    monkeypatch.setattr(cli, "create_engine", engine)
    with pytest.raises(SystemExit):
        cli.main([])
    assert "confirm-demo-data" in capsys.readouterr().err
    engine.assert_not_called()
