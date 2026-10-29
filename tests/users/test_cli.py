from unittest.mock import MagicMock

import pytest

from atelier_api.users import cli


def test_bootstrap_help_does_not_offer_password_argument(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["atelier-users", "bootstrap", "--help"])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 0
    assert "--password" not in capsys.readouterr().out


def test_bootstrap_prompts_and_does_not_print_credentials(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(
        "sys.argv", ["atelier-users", "bootstrap", "--email", "admin@example.com"]
    )
    monkeypatch.setattr(cli, "getpass", lambda _: "cli-test-password-123")
    monkeypatch.setattr(cli, "Session", MagicMock())
    bootstrap = MagicMock()
    bootstrap.return_value.model_dump_json.return_value = '{"id":1,"role":"admin"}'
    monkeypatch.setattr(cli, "bootstrap_admin", bootstrap)
    cli.main()
    supplied = bootstrap.call_args.args[0]
    assert supplied.password.get_secret_value() == "cli-test-password-123"
    assert "cli-test-password-123" not in capsys.readouterr().out


def test_invalid_administrator_cannot_provision_accounts(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(
        "sys.argv",
        [
            "atelier-users",
            "create",
            "--admin-email",
            "admin@example.com",
            "--email",
            "employee@example.com",
        ],
    )
    monkeypatch.setattr(cli, "getpass", lambda _: "wrong-password")
    monkeypatch.setattr(cli, "Session", MagicMock())
    monkeypatch.setattr(cli, "authenticate_user", lambda *args: None)
    create = MagicMock()
    monkeypatch.setattr(cli, "create_user", create)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    create.assert_not_called()
    assert "wrong-password" not in capsys.readouterr().err
