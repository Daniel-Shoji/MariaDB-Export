"""Shared types for MariaDB exports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import assert_never


class Dataset(StrEnum):
    """Recorder tables an export can read."""

    STATES = "states"
    EVENTS = "events"
    STATISTICS = "statistics"
    STATISTICS_SHORT_TERM = "statistics_short_term"
    RECORDER_RUNS = "recorder_runs"
    CUSTOM = "custom"

    def default_window(self) -> timedelta | None:
        """Return the range used when a call omits both start and end."""

        match self:
            case Dataset.STATES | Dataset.EVENTS:
                return timedelta(days=1)
            case Dataset.STATISTICS:
                return timedelta(days=31)
            case Dataset.STATISTICS_SHORT_TERM:
                return timedelta(days=2)
            case Dataset.RECORDER_RUNS:
                return timedelta(days=365)
            case Dataset.CUSTOM:
                return None
            case _ as unreachable:
                assert_never(unreachable)


class ExportFormat(StrEnum):
    """File format of an export."""

    CSV = "csv"
    JSON = "json"
    JSONL = "jsonl"

    @property
    def extension(self) -> str:
        """Return the file extension."""

        match self:
            case ExportFormat.CSV:
                return "csv"
            case ExportFormat.JSON:
                return "json"
            case ExportFormat.JSONL:
                return "jsonl"
            case _ as unreachable:
                assert_never(unreachable)


class RunStatus(StrEnum):
    """Status shown by the last-export sensor."""

    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


class ExportError(Exception):
    """A MariaDB export could not finish."""


class RequestError(ExportError):
    """The export request is not valid."""


class CannotConnect(ExportError):
    """The database server could not be reached."""


class InvalidAuth(ExportError):
    """The database rejected the account."""


class UnknownDatabase(ExportError):
    """The database name does not exist for this account."""


class NotMariaDBError(ExportError):
    """The recorder URL does not point at MariaDB or MySQL."""

    def __init__(self, scheme: str) -> None:
        """Store the scheme that was found."""

        self.scheme = scheme
        super().__init__(f"Database URL uses {scheme}")


class InvalidDatabaseUrl(ExportError):
    """A database URL could not be parsed."""


class UnsafePath(ExportError):
    """An export path leaves the Home Assistant config directory."""


class SchemaMismatch(ExportError):
    """The database is missing the recorder tables needed for this dataset."""


class InvalidConnection(ExportError):
    """A connection form field is missing or out of range."""

    def __init__(self, field: str, code: str) -> None:
        """Store the form field and the strings.json error code."""

        self.field = field
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ConnectionConfig:
    """How to open a MariaDB connection."""

    host: str
    port: int
    database: str
    username: str
    password: str
    unix_socket: str | None = None
    ssl: bool = False

    @property
    def display_host(self) -> str:
        """Return the host shown in the config flow."""

        if self.unix_socket:
            return self.unix_socket
        return f"{self.host}:{self.port}"

    def identity(self) -> str:
        """Return a stable id for this server and database."""

        if self.unix_socket:
            return f"socket:{self.unix_socket}:{self.database}".lower()
        return f"{self.host}:{self.port}:{self.database}".lower()


@dataclass(frozen=True)
class ExportRequest:
    """One export call after defaults have been applied."""

    dataset: Dataset
    export_format: ExportFormat
    start: datetime | None
    end: datetime | None
    entity_ids: tuple[str, ...]
    event_types: tuple[str, ...]
    statistic_ids: tuple[str, ...]
    query: str | None
    limit: int
    include_attributes: bool
    include_context: bool
    changed_only: bool
    after_time: datetime | None
    after_id: int | None
    filename: str | None


@dataclass(frozen=True)
class BuiltQuery:
    """SQL ready to run, plus the columns written to the file."""

    sql: str
    params: tuple[object, ...]
    columns: tuple[str, ...]
    id_field: str | None
    time_field: str | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ExportResult:
    """What an export wrote."""

    path: Path
    rows: int
    truncated: bool
    last_id: int | None
    last_time: str | None
    bytes_written: int
    dataset: str
    export_format: str
    warnings: tuple[str, ...]
