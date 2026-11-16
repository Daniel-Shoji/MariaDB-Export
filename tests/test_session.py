"""Tests for streaming an export through a fake MariaDB connection."""

from __future__ import annotations

from typing import Any

import pymysql
import pytest

from exporter.models import (
    CannotConnect,
    ConnectionConfig,
    Dataset,
    ExportFormat,
    InvalidAuth,
)
from exporter.schema import PROBE_TABLES
from exporter.session import MariaDBSession, classify_db_error
from support import modern_schema, request


class ScriptedCursor:
    """Cursor that answers the statements the exporter sends."""

    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.sql = ""
        self.params: Any = None
        self._index = 0
        self.description: list[tuple[str, ...]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        self.sql = sql
        self.params = params
        self.connection.queries.append((sql, params))
        self._index = 0
        if (
            self.connection.data_rows
            and "information_schema" not in sql
            and "VERSION()" not in sql
            and not sql.startswith("SET ")
        ):
            self.description = [(key,) for key in self.connection.data_rows[0]]

    def fetchone(self) -> dict[str, Any] | None:
        if "VERSION()" in self.sql:
            return {"version": self.connection.version}
        return None

    def fetchall(self) -> list[dict[str, Any]]:
        if "information_schema" in self.sql:
            return list(self.connection.schema_rows)
        return []

    def fetchmany(self, size: int) -> list[dict[str, Any]]:
        if "information_schema" in self.sql or "VERSION()" in self.sql:
            return []
        rows = self.connection.data_rows[self._index : self._index + size]
        self._index += size
        return rows

    def close(self) -> None:
        return None

    def __enter__(self) -> ScriptedCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class FakeConnection:
    """Connection double that records every statement."""

    def __init__(
        self, schema_rows: list[dict[str, Any]], data_rows: list[dict[str, Any]]
    ) -> None:
        self.schema_rows = schema_rows
        self.data_rows = data_rows
        self.version = "10.11.6-MariaDB"
        self.queries: list[tuple[str, Any]] = []
        self.closed = False

    def cursor(self, cursor: Any = None) -> ScriptedCursor:
        return ScriptedCursor(self)

    def close(self) -> None:
        self.closed = True


def _schema_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table, columns in modern_schema().columns.items():
        for name, info in columns.items():
            rows.append(
                {
                    "table_name": table,
                    "column_name": name,
                    "data_type": info.data_type,
                    "character_maximum_length": info.char_length,
                }
            )
    return rows


def test_export_streams_csv_and_stops_at_the_limit(tmp_path) -> None:
    """Rows are written until the limit, and the extra row marks the file truncated."""

    rows = [
        {
            "state_id": index,
            "entity_id": "sensor.kitchen",
            "state": str(index),
            "attributes": "{}",
            "last_updated_ts": 1767225600 + index,
            "last_changed_ts": None,
            "last_reported_ts": None,
            "origin_idx": 0,
        }
        for index in (1, 2, 3)
    ]
    connection = FakeConnection(_schema_rows(), rows)

    def connect(**kwargs: Any) -> FakeConnection:
        connection.kwargs = kwargs
        return connection

    result = MariaDBSession(_config(), connect=connect).export(
        request(limit=2, include_attributes=True),
        tmp_path,
        statement_timeout=30,
    )

    text = result.path.read_text(encoding="utf-8-sig")
    assert result.rows == 2
    assert result.truncated is True
    assert result.last_id == 2
    assert result.export_format == "csv"
    assert "sensor.kitchen" in text
    assert "3" not in text.splitlines()[-1]
    assert connection.closed is True
    assert any("max_statement_time" in sql for sql, _params in connection.queries)
    assert not list(tmp_path.glob(".*.partial"))
    probe = next(
        params for sql, params in connection.queries if "information_schema" in sql
    )
    assert probe == PROBE_TABLES


def test_ping_maps_access_denied_and_sends_the_socket(tmp_path) -> None:
    """Authentication failures stay distinct from a down server."""

    seen: dict[str, Any] = {}

    def connect(**kwargs: Any) -> FakeConnection:
        seen.update(kwargs)
        raise pymysql.err.OperationalError(1045, "Access denied")

    config = _config()
    config = ConnectionConfig(
        host=config.host,
        port=config.port,
        database=config.database,
        username=config.username,
        password=config.password,
        unix_socket="/run/mysqld/mysqld.sock",
        ssl=True,
    )
    with pytest.raises(InvalidAuth):
        MariaDBSession(config, connect=connect).ping()
    assert seen["unix_socket"] == "/run/mysqld/mysqld.sock"
    assert "host" not in seen
    assert seen["ssl"] == {"check_hostname": False}
    assert seen["charset"] == "utf8mb4"
    assert isinstance(
        classify_db_error(pymysql.err.OperationalError(2003, "down")),
        CannotConnect,
    )


def _config() -> ConnectionConfig:
    return ConnectionConfig(
        host="db.local",
        port=3306,
        database="homeassistant",
        username="ha_export",
        password="secret",
    )


def test_custom_export_writes_jsonl(tmp_path) -> None:
    """A custom SELECT uses the cursor columns and writes one object per line."""

    connection = FakeConnection(_schema_rows(), [{"statistic_id": "sensor.kitchen"}])

    def connect(**kwargs: Any) -> FakeConnection:
        return connection

    export = request(
        dataset=Dataset.CUSTOM,
        export_format=ExportFormat.JSONL,
        start=None,
        end=None,
        query="SELECT statistic_id FROM statistics_meta",
        limit=5,
    )
    result = MariaDBSession(_config(), connect=connect).export(
        export,
        tmp_path,
        statement_timeout=0,
    )

    assert result.rows == 1
    assert (
        result.path.read_text(encoding="utf-8").strip()
        == '{"statistic_id": "sensor.kitchen"}'
    )
    assert any("mariadb_export_query" in sql for sql, _params in connection.queries)
