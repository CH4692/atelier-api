import json
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from atelier_api.photos import purge_cli
from atelier_api.photos.purge import PurgeSummary
from atelier_api.settings import Settings


def config(**changes):
    return Settings(_env_file=None, database_url="sqlite://", **changes)


def test_retention_defaults_are_safe():
    settings = config()
    assert settings.photo_soft_delete_retention_days == 30
    assert not settings.photo_auto_purge_enabled
    assert (
        config(photo_soft_delete_retention_days=7).photo_soft_delete_retention_days == 7
    )


@pytest.mark.parametrize("value", [-1, 0, 36501, 1.5, "invalid", True])
def test_unsafe_retention_rejected(value):
    with pytest.raises(ValidationError):
        config(photo_soft_delete_retention_days=value)


def test_retention_environment(monkeypatch):
    monkeypatch.setenv("PHOTO_SOFT_DELETE_RETENTION_DAYS", "14")
    monkeypatch.setenv("PHOTO_AUTO_PURGE_ENABLED", "true")
    assert config().photo_soft_delete_retention_days == 14
    assert config().photo_auto_purge_enabled


def test_dry_run_never_constructs_storage_or_calls_purge(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["atelier-photos-purge", "--dry-run"])
    monkeypatch.setattr(purge_cli, "settings", config())
    session = MagicMock()
    monkeypatch.setattr(purge_cli, "Session", session)
    statistics = MagicMock(
        return_value=PurgeSummary(
            execution_id="test", eligible=3, eligible_bytes=126, protected=2
        )
    )
    monkeypatch.setattr(purge_cli, "retention_statistics", statistics)
    storage = MagicMock(side_effect=AssertionError("Dry-run cannot access R2"))
    monkeypatch.setattr(purge_cli, "R2Storage", storage)
    purge = MagicMock(side_effect=AssertionError("Dry-run cannot purge"))
    monkeypatch.setattr(purge_cli, "purge_photos", purge)
    purge_cli.main()
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"]
    assert output["eligible"] == 3
    assert output["eligible_bytes"] == 126
    assert output["protected"] == 2
    assert output["processed"] == 0
    storage.assert_not_called()
    purge.assert_not_called()


def test_disabled_cli_never_constructs_storage(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["atelier-photos-purge"])
    monkeypatch.setattr(purge_cli, "settings", config())
    storage = MagicMock(side_effect=AssertionError("Disabled command cannot access R2"))
    monkeypatch.setattr(purge_cli, "R2Storage", storage)
    with pytest.raises(SystemExit) as error:
        purge_cli.main()
    assert error.value.code == 1
    assert json.loads(capsys.readouterr().out)["result"] == "failed"
    storage.assert_not_called()


@pytest.mark.parametrize("value", ["0", "-1", "1001", "text"])
def test_invalid_cli_limit_rejected_before_any_work(monkeypatch, value):
    monkeypatch.setattr("sys.argv", ["atelier-photos-purge", "--limit", value])
    with pytest.raises(SystemExit) as error:
        purge_cli.main()
    assert error.value.code == 2


def test_cli_failure_summary_and_exit_code(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["atelier-photos-purge", "--limit", "7"])
    monkeypatch.setattr(purge_cli, "settings", config(photo_auto_purge_enabled=True))
    storage = MagicMock()
    monkeypatch.setattr(purge_cli, "R2Storage", MagicMock(return_value=storage))
    purge = MagicMock(
        return_value=PurgeSummary(
            execution_id="test",
            eligible=8,
            processed=7,
            purged=6,
            failed=1,
            result="failed",
        )
    )
    monkeypatch.setattr(purge_cli, "purge_photos", purge)
    with pytest.raises(SystemExit) as error:
        purge_cli.main()
    assert error.value.code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["failed"] == 1
    assert output["purged"] == 6
    assert purge.call_args.kwargs["limit"] == 7
    storage.close.assert_called_once()
