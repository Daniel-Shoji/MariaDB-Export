"""Discover which recorder columns this database still has."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .models import SchemaMismatch

PROBE_TABLES: tuple[str, ...] = (
    "states",
    "states_meta",
    "state_attributes",
    "events",
    "event_data",
    "event_types",
    "statistics",
    "statistics_short_term",
    "statistics_meta",
    "recorder_runs",
    "schema_changes",
)


@dataclass(frozen=True)
class Column:
    """One column reported by information_schema."""

    name: str
    data_type: str
    char_length: int | None

    @property
    def usable(self) -> bool:
        """Return whether Home Assistant still stores values in this column.

        Current schemas keep old columns as CHAR(0). Those names still appear
        in information_schema, but the recorder no longer writes them.
        """

        if self.data_type in {"char", "varchar"} and (self.char_length or 0) == 0:
            return False
        return True


@dataclass(frozen=True)
class Schema:
    """Columns grouped by table."""

    columns: Mapping[str, Mapping[str, Column]]

    def has_table(self, table: str) -> bool:
        """Return whether the table exists."""

        return table in self.columns

    def has(self, table: str, column: str) -> bool:
        """Return whether the column exists and still holds values."""

        info = self.columns.get(table, {}).get(column)
        return info is not None and info.usable

    def require(self, table: str, dataset: str) -> None:
        """Raise when a dataset's table is missing."""

        if not self.has_table(table):
            raise SchemaMismatch(
                f"This database has no {table} table, so {dataset} cannot be exported. "
                "A custom export can still run a SELECT."
            )


def probe_sql() -> tuple[str, tuple[str, ...]]:
    """Return the information_schema query and its parameters."""

    placeholders = ", ".join(["%s"] * len(PROBE_TABLES))
    sql = (
        "SELECT table_name, column_name, data_type, character_maximum_length "
        "FROM information_schema.columns "
        "WHERE table_schema = DATABASE() "
        f"AND table_name IN ({placeholders})"
    )
    return sql, PROBE_TABLES


def schema_from_rows(rows: Iterable[Mapping[str, Any]]) -> Schema:
    """Build a schema snapshot from information_schema rows."""

    tables: dict[str, dict[str, Column]] = {}
    for row in rows:
        lowered = {str(key).lower(): value for key, value in row.items()}
        table = str(lowered.get("table_name", "")).lower()
        name = str(lowered.get("column_name", "")).lower()
        if not table or not name:
            continue
        data_type = str(lowered.get("data_type", "")).lower()
        length = _optional_int(lowered.get("character_maximum_length"))
        tables.setdefault(table, {})[name] = Column(name, data_type, length)
    return Schema(columns=tables)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)  # type: ignore[arg-type]
