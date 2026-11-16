"""Fixtures shared by export tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from exporter.models import Dataset, ExportFormat, ExportRequest
from exporter.schema import Column, Schema


def column(
    name: str, data_type: str = "bigint", char_length: int | None = None
) -> Column:
    """Build one information_schema column."""

    return Column(name, data_type, char_length)


def make_schema(tables: dict[str, list[Column]]) -> Schema:
    """Build a schema from usable and legacy columns."""

    return Schema(
        columns={
            table: {item.name: item for item in columns}
            for table, columns in tables.items()
        }
    )


def request(**overrides: Any) -> ExportRequest:
    """Build an export request with a one-day window."""

    base = ExportRequest(
        dataset=Dataset.STATES,
        export_format=ExportFormat.CSV,
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 2, tzinfo=UTC),
        entity_ids=(),
        event_types=(),
        statistic_ids=(),
        query=None,
        limit=10,
        include_attributes=True,
        include_context=False,
        changed_only=False,
        after_time=None,
        after_id=None,
        filename=None,
    )
    return replace(base, **overrides)


def modern_schema() -> Schema:
    """Schema version 53 style recorder tables."""

    return make_schema(
        {
            "states": [
                column("state_id"),
                column("entity_id", "char", 0),
                column("state", "varchar", 255),
                column("attributes", "char", 0),
                column("last_updated_ts", "double"),
                column("last_changed_ts", "double"),
                column("last_reported_ts", "double"),
                column("last_updated", "char", 0),
                column("last_changed", "char", 0),
                column("metadata_id"),
                column("attributes_id"),
                column("origin_idx", "smallint"),
                column("context_id_bin", "binary", 16),
                column("context_user_id_bin", "binary", 16),
                column("context_parent_id_bin", "binary", 16),
            ],
            "states_meta": [
                column("metadata_id"),
                column("entity_id", "varchar", 255),
            ],
            "state_attributes": [
                column("attributes_id"),
                column("hash"),
                column("shared_attrs", "longtext"),
            ],
            "events": [
                column("event_id"),
                column("event_type", "char", 0),
                column("event_data", "char", 0),
                column("time_fired_ts", "double"),
                column("time_fired", "char", 0),
                column("event_type_id"),
                column("data_id"),
                column("origin_idx", "smallint"),
                column("context_id_bin", "binary", 16),
                column("context_user_id_bin", "binary", 16),
                column("context_parent_id_bin", "binary", 16),
            ],
            "event_types": [
                column("event_type_id"),
                column("event_type", "varchar", 64),
            ],
            "event_data": [
                column("data_id"),
                column("shared_data", "longtext"),
            ],
            "statistics": _statistic_columns(),
            "statistics_short_term": _statistic_columns(),
            "statistics_meta": [
                column("id"),
                column("statistic_id", "varchar", 255),
                column("source", "varchar", 32),
                column("unit_of_measurement", "varchar", 255),
                column("unit_class", "varchar", 255),
                column("has_mean", "tinyint"),
                column("has_sum", "tinyint"),
                column("name", "varchar", 255),
                column("mean_type", "smallint"),
            ],
            "recorder_runs": [
                column("run_id"),
                column("start", "datetime"),
                column("end", "datetime"),
                column("closed_incorrect", "tinyint"),
                column("created", "datetime"),
            ],
        }
    )


def legacy_schema() -> Schema:
    """A pre-normalization recorder schema."""

    return make_schema(
        {
            "states": [
                column("state_id"),
                column("entity_id", "varchar", 255),
                column("state", "varchar", 255),
                column("attributes", "longtext"),
                column("last_updated", "datetime"),
                column("last_changed", "datetime"),
            ],
            "events": [
                column("event_id"),
                column("event_type", "varchar", 64),
                column("event_data", "longtext"),
                column("time_fired", "datetime"),
            ],
            "statistics": [
                column("id"),
                column("statistic_id", "varchar", 255),
                column("start", "datetime"),
                column("mean", "double"),
                column("min", "double"),
                column("max", "double"),
                column("state", "double"),
                column("sum", "double"),
            ],
            "recorder_runs": [
                column("run_id"),
                column("start", "datetime"),
                column("end", "datetime"),
                column("closed_incorrect", "tinyint"),
                column("created", "datetime"),
            ],
        }
    )


def _statistic_columns() -> list[Column]:
    return [
        column("id"),
        column("metadata_id"),
        column("start_ts", "double"),
        column("created_ts", "double"),
        column("mean", "double"),
        column("mean_weight", "double"),
        column("min", "double"),
        column("max", "double"),
        column("last_reset_ts", "double"),
        column("state", "double"),
        column("sum", "double"),
    ]
