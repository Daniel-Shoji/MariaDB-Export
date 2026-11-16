"""Open MariaDB and stream an export to disk."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import pymysql
import pymysql.cursors

from .models import (
    BuiltQuery,
    CannotConnect,
    ConnectionConfig,
    ExportError,
    ExportRequest,
    ExportResult,
    InvalidAuth,
    UnknownDatabase,
)
from .normalize import normalize_row
from .paths import build_filename
from .queries import build_query
from .schema import probe_sql, schema_from_rows
from .writers import open_writer

_LOGGER = logging.getLogger(__name__)
_BATCH = 1000


class DBCursor(Protocol):
    """The cursor methods this package uses."""

    description: Any

    def execute(self, sql: str, params: Any = None) -> Any:
        """Run a statement."""

    def fetchone(self) -> dict[str, Any] | None:
        """Return the next row."""

    def fetchall(self) -> list[dict[str, Any]]:
        """Return every remaining row."""

    def fetchmany(self, size: int) -> list[dict[str, Any]]:
        """Return the next batch."""

    def close(self) -> None:
        """Close the cursor."""

    def __enter__(self) -> DBCursor:
        """Enter a cursor context."""

    def __exit__(self, *args: object) -> None:
        """Exit a cursor context."""


class DBConnection(Protocol):
    """The connection methods this package uses."""

    def cursor(self, cursor: Any = None) -> DBCursor:
        """Open a cursor."""

    def close(self) -> None:
        """Close the connection."""


class Connector(Protocol):
    """A pymysql.connect-compatible factory, overridable in tests."""

    def __call__(self, **kwargs: Any) -> DBConnection:
        """Open a connection."""


def ping_database(config: ConnectionConfig) -> str:
    """Open a short connection and return the server version."""

    return MariaDBSession(config).ping()


def classify_db_error(error: Exception) -> ExportError:
    """Map a driver error onto a connection error."""

    if isinstance(error, ExportError):
        return error
    code = error.args[0] if error.args and isinstance(error.args[0], int) else None
    if code == 1045:
        return InvalidAuth("MariaDB rejected the username or password.")
    if code == 1049:
        return UnknownDatabase(
            "That database does not exist or the user cannot see it."
        )
    if code in {2002, 2003, 2005, 2006, 2013}:
        return CannotConnect("Could not connect to MariaDB.")
    if isinstance(
        error,
        (
            pymysql.err.OperationalError,
            pymysql.err.ProgrammingError,
            pymysql.err.DataError,
        ),
    ):
        detail = (
            error.args[1]
            if len(error.args) > 1
            else "The database rejected the export."
        )
        return ExportError(str(detail))
    if isinstance(error, (pymysql.err.InterfaceError, OSError, TimeoutError)):
        return CannotConnect("Could not connect to MariaDB.")
    return ExportError("The export failed.")


class MariaDBSession:
    """One read-only session factory for a configured database."""

    def __init__(
        self, config: ConnectionConfig, connect: Connector | None = None
    ) -> None:
        """Store the connection settings."""

        self.config = config
        self._connect = connect or _default_connect

    def ping(self) -> str:
        """Return the server version, or raise a connection error."""

        connection = self._open(read_timeout=10)
        try:
            return _version(connection)
        except Exception as err:
            raise classify_db_error(err) from err
        finally:
            connection.close()

    def export(
        self,
        request: ExportRequest,
        directory: Path,
        *,
        statement_timeout: int,
        now: datetime | None = None,
    ) -> ExportResult:
        """Stream the export into ``directory`` and return what was written."""

        clock = now or datetime.now(UTC)
        directory.mkdir(parents=True, exist_ok=True)
        filename = build_filename(request, clock)
        target = (directory / filename).resolve()
        if directory.resolve() not in target.parents:
            raise ExportError("The export file must stay inside the export folder.")
        partial = directory / f".{filename}.partial"
        if partial.exists():
            partial.unlink()
        connection = self._open(read_timeout=None)
        try:
            try:
                version = _version(connection)
                _apply_timeout(connection, version, statement_timeout)
                schema = _load_schema(connection)
                built = build_query(schema, request)
                with connection.cursor(pymysql.cursors.SSDictCursor) as cursor:
                    cursor.execute(built.sql, built.params)
                    rows, truncated, last_id, last_time = _stream(
                        partial, cursor, request, built
                    )
            except ExportError:
                partial.unlink(missing_ok=True)
                raise
            except pymysql.err.Error as err:
                partial.unlink(missing_ok=True)
                raise classify_db_error(err) from err
            except OSError as err:
                partial.unlink(missing_ok=True)
                raise ExportError("The export file could not be written.") from err
            try:
                if target.exists():
                    target.unlink()
                partial.replace(target)
            except OSError as err:
                partial.unlink(missing_ok=True)
                raise ExportError("The export file could not be written.") from err
            return ExportResult(
                path=target,
                rows=rows,
                truncated=truncated,
                last_id=last_id,
                last_time=last_time,
                bytes_written=target.stat().st_size,
                dataset=request.dataset.value,
                export_format=request.export_format.value,
                warnings=built.warnings,
            )
        finally:
            connection.close()

    def _open(self, *, read_timeout: float | None) -> DBConnection:
        try:
            return self._connect(
                **_connect_kwargs(self.config, read_timeout=read_timeout)
            )
        except Exception as err:
            raise classify_db_error(err) from err


def _default_connect(**kwargs: Any) -> DBConnection:
    return pymysql.connect(**kwargs)


def _connect_kwargs(
    config: ConnectionConfig, *, read_timeout: float | None
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "user": config.username,
        "password": config.password,
        "database": config.database,
        "charset": "utf8mb4",
        "connect_timeout": 10,
        "autocommit": True,
    }
    if read_timeout is not None:
        kwargs["read_timeout"] = read_timeout
    if config.unix_socket:
        kwargs["unix_socket"] = config.unix_socket
    else:
        kwargs["host"] = config.host
        kwargs["port"] = config.port
    if config.ssl:
        kwargs["ssl"] = {"check_hostname": False}
    return kwargs


def _version(connection: DBConnection) -> str:
    with connection.cursor(pymysql.cursors.DictCursor) as cursor:
        cursor.execute("SELECT VERSION() AS version")
        row = cursor.fetchone() or {}
    return str(row.get("version", ""))


def _apply_timeout(connection: DBConnection, version: str, seconds: int) -> None:
    if seconds <= 0:
        return
    if "mariadb" in version.lower():
        statement = "SET SESSION max_statement_time = %s"
        parameter: object = seconds
    else:
        statement = "SET SESSION max_execution_time = %s"
        parameter = seconds * 1000
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(statement, (parameter,))
    except Exception:
        _LOGGER.debug("Could not set the database statement timeout", exc_info=True)


def _load_schema(connection: DBConnection) -> Any:
    sql, params = probe_sql()
    with connection.cursor(pymysql.cursors.DictCursor) as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    return schema_from_rows(rows)


def _stream(
    path: Path,
    cursor: DBCursor,
    request: ExportRequest,
    built: BuiltQuery,
) -> tuple[int, bool, int | None, str | None]:
    columns = built.columns
    if not columns and cursor.description:
        columns = tuple(str(item[0]) for item in cursor.description)
    encoding = "utf-8-sig" if request.export_format.value == "csv" else "utf-8"
    written = 0
    truncated = False
    last_id: int | None = None
    last_time: str | None = None
    with path.open("w", encoding=encoding, newline="") as handle:
        writer = open_writer(handle, request.export_format, columns)
        while written <= request.limit:
            batch = cursor.fetchmany(min(_BATCH, request.limit - written + 1))
            if not batch:
                break
            for raw in batch:
                if written == request.limit:
                    truncated = True
                    break
                row = normalize_row(request.dataset, _row_mapping(raw), columns)
                last_id = _row_id(row, built.id_field, last_id)
                last_time = _row_time(row, built.time_field, last_time)
                writer.write(row)
                written += 1
            if truncated:
                break
        writer.finish()
    return written, truncated, last_id, last_time


def _row_mapping(raw: Any) -> Mapping[str, Any]:
    if isinstance(raw, Mapping):
        return {str(key): value for key, value in raw.items()}
    raise ExportError("The database returned a row without column names.")


def _row_id(
    row: Mapping[str, Any], field: str | None, previous: int | None
) -> int | None:
    if field is None:
        return previous
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        return previous
    return value


def _row_time(
    row: Mapping[str, Any], field: str | None, previous: str | None
) -> str | None:
    if field is None:
        return previous
    value = row.get(field)
    if isinstance(value, str):
        return value
    return previous
