"""Build parameterized SELECT statements for recorder tables."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import assert_never

from .models import BuiltQuery, Dataset, ExportRequest, RequestError, SchemaMismatch
from .schema import Schema
from .sql_guard import prepare_custom

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_STATISTICS_TABLES = {
    Dataset.STATISTICS: "statistics",
    Dataset.STATISTICS_SHORT_TERM: "statistics_short_term",
}


class _Sql:
    """Fragments of one SELECT."""

    def __init__(self) -> None:
        self.select: list[str] = []
        self.joins: list[str] = []
        self.where: list[str] = []
        self.params: list[object] = []

    def add(self, clause: str, *params: object) -> None:
        self.where.append(clause)
        self.params.extend(params)

    def statement(self, table: str, order: str) -> str:
        sql = f"SELECT {', '.join(self.select)} FROM {quote_ident(table)} AS s"
        if self.joins:
            sql = f"{sql} {' '.join(self.joins)}"
        if self.where:
            sql = f"{sql} WHERE {' AND '.join(self.where)}"
        return f"{sql} {order} LIMIT %s"


def quote_ident(name: str) -> str:
    """Quote a table or column name that belongs to this integration."""

    if not _IDENT.fullmatch(name):
        raise SchemaMismatch(f"Unexpected identifier {name}")
    return f"`{name}`"


def build_query(schema: Schema, request: ExportRequest) -> BuiltQuery:
    """Build the SELECT for a dataset."""

    match request.dataset:
        case Dataset.STATES:
            return _states(schema, request)
        case Dataset.EVENTS:
            return _events(schema, request)
        case Dataset.STATISTICS | Dataset.STATISTICS_SHORT_TERM:
            return _statistics(schema, request)
        case Dataset.RECORDER_RUNS:
            return _runs(schema, request)
        case Dataset.CUSTOM:
            if request.query is None:
                raise RequestError("Enter a SELECT query.")
            sql, params = prepare_custom(request.query, request.limit)
            return BuiltQuery(sql, params, (), None, None, ())
        case _ as unreachable:
            assert_never(unreachable)


def _states(schema: Schema, request: ExportRequest) -> BuiltQuery:
    schema.require("states", "states")
    warnings: list[str] = []
    sql = _Sql()
    modern = schema.has("states", "metadata_id") and schema.has_table("states_meta")
    if modern:
        sql.joins.append("INNER JOIN states_meta AS m ON m.metadata_id = s.metadata_id")
        entity = "m.entity_id"
    elif schema.has("states", "entity_id"):
        entity = "s.entity_id"
    else:
        raise SchemaMismatch(
            "The states table has no usable entity id column, "
            "so states cannot be exported."
        )
    sql.select.extend(
        [
            "s.state_id AS state_id",
            f"{entity} AS entity_id",
            "s.state AS state",
        ]
    )
    columns = ["state_id", "entity_id", "state"]
    if request.include_attributes:
        attribute_sql = _attribute_expr(schema)
        if attribute_sql is None:
            warnings.append("State attributes are not stored in this database.")
        else:
            sql.joins.extend(attribute_sql[1])
            sql.select.append(attribute_sql[0])
            columns.append("attributes")
    _append_state_times(schema, sql, columns)
    if request.include_context and schema.has("states", "context_id_bin"):
        _append_context(sql, columns)
    elif request.include_context:
        warnings.append("Context ids are not stored in this database.")
    if schema.has("states", "origin_idx"):
        sql.select.append("s.origin_idx AS origin_idx")
        columns.append("origin")
    time_sql, as_epoch = _state_time_column(schema)
    if request.entity_ids:
        marks = _placeholders(len(request.entity_ids))
        if modern:
            sql.add(
                "s.metadata_id IN ("
                f"SELECT metadata_id FROM states_meta WHERE entity_id IN ({marks})"
                ")",
                *request.entity_ids,
            )
        else:
            sql.add(f"s.entity_id IN ({marks})", *request.entity_ids)
    if request.changed_only:
        sql.add(_changed_only_clause(schema))
    _append_range(sql, time_sql, request, as_epoch=as_epoch)
    id_sql = "s.state_id"
    _append_keyset(sql, time_sql, id_sql, request, as_epoch=as_epoch)
    order = f"ORDER BY {time_sql} ASC, {id_sql} ASC"
    sql.params.append(request.limit + 1)
    return BuiltQuery(
        sql.statement("states", order),
        tuple(sql.params),
        tuple(columns),
        "state_id",
        "last_updated",
        tuple(warnings),
    )


def _events(schema: Schema, request: ExportRequest) -> BuiltQuery:
    schema.require("events", "events")
    warnings: list[str] = []
    sql = _Sql()
    modern = schema.has("events", "event_type_id") and schema.has_table("event_types")
    if modern:
        sql.joins.append(
            "INNER JOIN event_types AS t ON t.event_type_id = s.event_type_id"
        )
        event_type = "t.event_type"
    elif schema.has("events", "event_type"):
        event_type = "s.event_type"
    else:
        raise SchemaMismatch(
            "The events table has no usable event type column, "
            "so events cannot be exported."
        )
    sql.select.extend(
        [
            "s.event_id AS event_id",
            f"{event_type} AS event_type",
        ]
    )
    columns = ["event_id", "event_type"]
    if request.include_attributes:
        if schema.has_table("event_data") and schema.has("event_data", "shared_data"):
            sql.joins.append("LEFT JOIN event_data AS d ON d.data_id = s.data_id")
            if schema.has("events", "event_data"):
                sql.select.append("COALESCE(d.shared_data, s.event_data) AS event_data")
            else:
                sql.select.append("d.shared_data AS event_data")
            columns.append("event_data")
        elif schema.has("events", "event_data"):
            sql.select.append("s.event_data AS event_data")
            columns.append("event_data")
        else:
            warnings.append("Event data is not stored in this database.")
    time_sql, as_epoch = _event_time_column(schema, sql, columns)
    if request.include_context and schema.has("events", "context_id_bin"):
        _append_context(sql, columns)
    elif request.include_context:
        warnings.append("Context ids are not stored in this database.")
    if schema.has("events", "origin_idx"):
        sql.select.append("s.origin_idx AS origin_idx")
        columns.append("origin")
    if request.event_types:
        marks = _placeholders(len(request.event_types))
        if modern:
            sql.add(
                "s.event_type_id IN ("
                f"SELECT event_type_id FROM event_types WHERE event_type IN ({marks})"
                ")",
                *request.event_types,
            )
        else:
            sql.add(f"s.event_type IN ({marks})", *request.event_types)
    _append_range(sql, time_sql, request, as_epoch=as_epoch)
    id_sql = "s.event_id"
    _append_keyset(sql, time_sql, id_sql, request, as_epoch=as_epoch)
    order = f"ORDER BY {time_sql} ASC, {id_sql} ASC"
    sql.params.append(request.limit + 1)
    return BuiltQuery(
        sql.statement("events", order),
        tuple(sql.params),
        tuple(columns),
        "event_id",
        "time_fired",
        tuple(warnings),
    )


def _statistics(schema: Schema, request: ExportRequest) -> BuiltQuery:
    table = _STATISTICS_TABLES.get(request.dataset)
    if table is None:
        raise RequestError("Choose a statistics dataset.")
    schema.require(table, request.dataset.value)
    sql = _Sql()
    modern = schema.has(table, "metadata_id") and schema.has_table("statistics_meta")
    columns = ["id"]
    sql.select.append("s.id AS id")
    if modern:
        sql.joins.append("INNER JOIN statistics_meta AS m ON m.id = s.metadata_id")
        sql.select.append("m.statistic_id AS statistic_id")
        columns.append("statistic_id")
        for column in (
            "source",
            "unit_of_measurement",
            "unit_class",
            "name",
            "has_mean",
            "has_sum",
            "mean_type",
        ):
            if schema.has("statistics_meta", column):
                sql.select.append(f"m.{quote_ident(column)} AS {quote_ident(column)}")
                columns.append(column)
                if column == "mean_type":
                    columns.append("mean_type_value")
    elif schema.has(table, "statistic_id"):
        sql.select.append("s.statistic_id AS statistic_id")
        columns.append("statistic_id")
    else:
        raise SchemaMismatch(
            f"The {table} table has no statistic id, so it cannot be exported."
        )
    if schema.has(table, "start_ts"):
        sql.select.append("s.start_ts AS start_ts")
        time_sql = "s.start_ts"
        as_epoch = True
    elif schema.has(table, "start"):
        sql.select.append("s.start AS start_at")
        time_sql = "s.start"
        as_epoch = False
    else:
        raise SchemaMismatch(f"The {table} table has no start time.")
    columns.extend(["start", "start_ts"])
    if schema.has(table, "created_ts"):
        sql.select.append("s.created_ts AS created_ts")
        columns.extend(["created", "created_ts"])
    elif schema.has(table, "created"):
        sql.select.append("s.created AS created_at")
        columns.extend(["created", "created_ts"])
    for column in ("mean", "mean_weight", "min", "max", "state", "sum"):
        if schema.has(table, column):
            sql.select.append(f"s.{quote_ident(column)} AS {quote_ident(column)}")
            columns.append(column)
    if schema.has(table, "last_reset_ts"):
        sql.select.append("s.last_reset_ts AS last_reset_ts")
        columns.extend(["last_reset", "last_reset_ts"])
    elif schema.has(table, "last_reset"):
        sql.select.append("s.last_reset AS last_reset_at")
        columns.extend(["last_reset", "last_reset_ts"])
    if request.statistic_ids:
        marks = _placeholders(len(request.statistic_ids))
        if modern:
            sql.add(
                "s.metadata_id IN ("
                f"SELECT id FROM statistics_meta WHERE statistic_id IN ({marks})"
                ")",
                *request.statistic_ids,
            )
        else:
            sql.add(f"s.statistic_id IN ({marks})", *request.statistic_ids)
    _append_range(sql, time_sql, request, as_epoch=as_epoch)
    _append_keyset(sql, time_sql, "s.id", request, as_epoch=as_epoch)
    order = f"ORDER BY {time_sql} ASC, s.id ASC"
    sql.params.append(request.limit + 1)
    return BuiltQuery(
        sql.statement(table, order),
        tuple(sql.params),
        tuple(columns),
        "id",
        "start",
        (),
    )


def _runs(schema: Schema, request: ExportRequest) -> BuiltQuery:
    schema.require("recorder_runs", "recorder_runs")
    if not schema.has("recorder_runs", "start"):
        raise SchemaMismatch("The recorder_runs table has no start time.")
    sql = _Sql()
    sql.select.extend(
        [
            "s.run_id AS run_id",
            "s.start AS start",
        ]
    )
    columns = ["run_id", "start", "start_ts"]
    for column, output in (
        ("end", ("end", "end_ts")),
        ("closed_incorrect", ("closed_incorrect",)),
        ("created", ("created", "created_ts")),
    ):
        if schema.has("recorder_runs", column):
            sql.select.append(f"s.{quote_ident(column)} AS {quote_ident(column)}")
            columns.extend(output)
    _append_range(sql, "s.start", request, as_epoch=False)
    _append_keyset(sql, "s.start", "s.run_id", request, as_epoch=False)
    sql.params.append(request.limit + 1)
    return BuiltQuery(
        sql.statement("recorder_runs", "ORDER BY s.start ASC, s.run_id ASC"),
        tuple(sql.params),
        tuple(columns),
        "run_id",
        "start",
        (),
    )


def _attribute_expr(schema: Schema) -> tuple[str, list[str]] | None:
    joins: list[str] = []
    shared = schema.has_table("state_attributes") and schema.has(
        "state_attributes", "shared_attrs"
    )
    legacy = schema.has("states", "attributes")
    if shared:
        joins.append(
            "LEFT JOIN state_attributes AS sa ON sa.attributes_id = s.attributes_id"
        )
        if legacy:
            return "COALESCE(sa.shared_attrs, s.attributes) AS attributes", joins
        return "sa.shared_attrs AS attributes", joins
    if legacy:
        return "s.attributes AS attributes", joins
    return None


def _append_state_times(schema: Schema, sql: _Sql, columns: list[str]) -> None:
    if schema.has("states", "last_updated_ts"):
        sql.select.append("s.last_updated_ts AS last_updated_ts")
    if schema.has("states", "last_updated"):
        sql.select.append("s.last_updated AS last_updated_at")
    if schema.has("states", "last_changed_ts"):
        sql.select.append("s.last_changed_ts AS last_changed_ts")
    if schema.has("states", "last_changed"):
        sql.select.append("s.last_changed AS last_changed_at")
    columns.extend(
        ["last_updated", "last_updated_ts", "last_changed", "last_changed_ts"]
    )
    if schema.has("states", "last_reported_ts"):
        sql.select.append("s.last_reported_ts AS last_reported_ts")
        columns.extend(["last_reported", "last_reported_ts"])


def _state_time_column(schema: Schema) -> tuple[str, bool]:
    if schema.has("states", "last_updated_ts"):
        return "s.last_updated_ts", True
    if schema.has("states", "last_updated"):
        return "s.last_updated", False
    raise SchemaMismatch("The states table has no last_updated time.")


def _event_time_column(
    schema: Schema, sql: _Sql, columns: list[str]
) -> tuple[str, bool]:
    if schema.has("events", "time_fired_ts"):
        sql.select.append("s.time_fired_ts AS time_fired_ts")
        columns.extend(["time_fired", "time_fired_ts"])
        return "s.time_fired_ts", True
    if schema.has("events", "time_fired"):
        sql.select.append("s.time_fired AS time_fired_at")
        columns.extend(["time_fired", "time_fired_ts"])
        return "s.time_fired", False
    raise SchemaMismatch("The events table has no time_fired time.")


def _append_context(sql: _Sql, columns: list[str]) -> None:
    sql.select.extend(
        [
            "s.context_id_bin AS context_id_bin",
            "s.context_user_id_bin AS context_user_id_bin",
            "s.context_parent_id_bin AS context_parent_id_bin",
        ]
    )
    columns.extend(["context_id", "context_user_id", "context_parent_id"])


def _changed_only_clause(schema: Schema) -> str:
    # Current schemas store NULL in last_changed_ts when it equals last_updated_ts.
    # Older schemas store both timestamps, equal only when the state value changed.
    if schema.has("states", "last_changed_ts") and schema.has(
        "states", "last_updated_ts"
    ):
        return "(s.last_changed_ts IS NULL OR s.last_changed_ts = s.last_updated_ts)"
    if schema.has("states", "last_changed") and schema.has("states", "last_updated"):
        return "s.last_changed = s.last_updated"
    raise SchemaMismatch("This database cannot filter to real state changes.")


def _append_range(
    sql: _Sql, column: str, request: ExportRequest, *, as_epoch: bool
) -> None:
    if request.start is not None:
        sql.add(f"{column} >= %s", _bound(request.start, as_epoch=as_epoch))
    if request.end is not None:
        sql.add(f"{column} < %s", _bound(request.end, as_epoch=as_epoch))


def _append_keyset(
    sql: _Sql,
    column: str,
    id_column: str,
    request: ExportRequest,
    *,
    as_epoch: bool,
) -> None:
    if request.after_time is None and request.after_id is None:
        return
    if request.after_time is None or request.after_id is None:
        raise RequestError("Resume with both after_time and after_id.")
    bound = _bound(request.after_time, as_epoch=as_epoch)
    sql.add(
        f"({column} > %s OR ({column} = %s AND {id_column} > %s))",
        bound,
        bound,
        request.after_id,
    )


def _bound(value: datetime, *, as_epoch: bool) -> float | datetime:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    aware = aware.astimezone(UTC)
    if as_epoch:
        return aware.timestamp()
    return aware.replace(tzinfo=None)


def _placeholders(count: int) -> str:
    return ", ".join(["%s"] * count)
