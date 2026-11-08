import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_fresh_alembic_environment_registers_estimate_and_template_models():
    # Running in the pytest process would hide missing imports: API test
    # collection already registers these models through the application router.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """import io
import json
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from sqlmodel import SQLModel

config = Config('alembic.ini')
script = ScriptDirectory.from_config(config)
with EnvironmentContext(config, script, as_sql=True, output_buffer=io.StringIO(),
                        fn=lambda *_: iter(())):
    script.run_env()
print(json.dumps(sorted(SQLModel.metadata.tables)))
""",
        ],
        cwd=PROJECT_ROOT,
        env={**os.environ, "DATABASE_URL": "sqlite://"},
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert {"repair_estimate", "estimate_item", "repair_template"} <= set(
        json.loads(result.stdout)
    )


def run_migration(url, *args):
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", *args],
        cwd=PROJECT_ROOT,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )


def test_offline_postgresql_sql_uses_environment_without_connecting():
    result = run_migration(
        "postgresql+psycopg://atelier:private%40password%25@127.0.0.1:1/atelier",
        "--sql",
    )
    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE customer" in result.stdout
    assert "SERIAL" in result.stdout
    assert "ADD COLUMN is_archived BOOLEAN DEFAULT false NOT NULL" in result.stdout
    assert "ALTER COLUMN is_archived DROP DEFAULT" in result.stdout
    assert "private" not in result.stdout + result.stderr


def test_online_connection_failure_is_actionable_and_hides_credentials():
    result = run_migration(
        "postgresql+psycopg://atelier:private%40password%25@127.0.0.1:1/atelier?connect_timeout=1",
    )
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "Database connection failed. Check DATABASE_URL" in output
    assert "private" not in output
    assert "Traceback" not in output
