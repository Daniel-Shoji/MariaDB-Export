"""Turn raw database values into stable export columns."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, assert_never

from .models import Dataset, SchemaMismatch

_MEAN_TYPES = {0: "none", 1: "arithmetic", 2: "circular"}


def normalize_row(
    dataset: Dataset, raw: Mapping[str, Any], columns: tuple[str, ...]
) -> dict[str, Any]:
    """Return one output row limited to the planned columns."""

    match dataset:
        case Dataset.STATES:
            full = _state_values(raw)
        case Dataset.EVENTS:
            full = _event_values(raw)
        case Dataset.STATISTICS | Dataset.STATISTICS_SHORT_TERM:
            full = _statistic_values(raw)
        case Dataset.RECORDER_RUNS:
            full = _run_values(raw)
        case Dataset.CUSTOM:
            full = {str(key): freeze(value) for key, value in raw.items()}
            return {key: full.get(key) for key in columns}
        case _ as unreachable:
            assert_never(unreachable)
    missing = [key for key in columns if key not in full]
    if missing:
        raise SchemaMismatch(f"Export column is not available: {', '.join(missing)}")
    return {key: freeze(full[key]) for key in columns}


def freeze(value: Any) -> Any:
    """Convert a database value into something CSV and JSON can both store."""

    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return _as_utc(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return str(value)


def _state_values(raw: Mapping[str, Any]) -> dict[str, Any]:
    updated = _time_value(raw.get("last_updated_ts"), raw.get("last_updated_at"))
    changed = _time_value(raw.get("last_changed_ts"), raw.get("last_changed_at"))
    reported = _time_value(raw.get("last_reported_ts"), raw.get("last_reported_at"))
    # A NULL last_changed_ts means the state value changed at last_updated_ts.
    changed_iso = changed[0] if changed[0] is not None else updated[0]
    reported_iso = reported[0] if reported[0] is not None else updated[0]
    return {
        "state_id": raw.get("state_id"),
        "entity_id": raw.get("entity_id"),
        "state": raw.get("state"),
        "attributes": raw.get("attributes"),
        "last_updated": updated[0],
        "last_updated_ts": updated[1],
        "last_changed": changed_iso,
        "last_changed_ts": changed[1],
        "last_reported": reported_iso,
        "last_reported_ts": reported[1],
        "origin": _origin(raw.get("origin_idx")),
        "context_id": _hex_id(raw.get("context_id_bin")),
        "context_user_id": _hex_id(raw.get("context_user_id_bin")),
        "context_parent_id": _hex_id(raw.get("context_parent_id_bin")),
    }


def _event_values(raw: Mapping[str, Any]) -> dict[str, Any]:
    fired = _time_value(raw.get("time_fired_ts"), raw.get("time_fired_at"))
    return {
        "event_id": raw.get("event_id"),
        "event_type": raw.get("event_type"),
        "event_data": raw.get("event_data"),
        "time_fired": fired[0],
        "time_fired_ts": fired[1],
        "origin": _origin(raw.get("origin_idx")),
        "context_id": _hex_id(raw.get("context_id_bin")),
        "context_user_id": _hex_id(raw.get("context_user_id_bin")),
        "context_parent_id": _hex_id(raw.get("context_parent_id_bin")),
    }


def _statistic_values(raw: Mapping[str, Any]) -> dict[str, Any]:
    start = _time_value(raw.get("start_ts"), raw.get("start_at"))
    created = _time_value(raw.get("created_ts"), raw.get("created_at"))
    last_reset = _time_value(raw.get("last_reset_ts"), raw.get("last_reset_at"))
    mean_type = _optional_int(raw.get("mean_type"))
    return {
        "id": raw.get("id"),
        "statistic_id": raw.get("statistic_id"),
        "source": raw.get("source"),
        "unit_of_measurement": raw.get("unit_of_measurement"),
        "unit_class": raw.get("unit_class"),
        "name": raw.get("name"),
        "has_mean": _optional_bool(raw.get("has_mean")),
        "has_sum": _optional_bool(raw.get("has_sum")),
        "mean_type": None if mean_type is None else _MEAN_TYPES.get(mean_type),
        "mean_type_value": mean_type,
        "start": start[0],
        "start_ts": start[1],
        "created": created[0],
        "created_ts": created[1],
        "mean": raw.get("mean"),
        "mean_weight": raw.get("mean_weight"),
        "min": raw.get("min"),
        "max": raw.get("max"),
        "last_reset": last_reset[0],
        "last_reset_ts": last_reset[1],
        "state": raw.get("state"),
        "sum": raw.get("sum"),
    }


def _run_values(raw: Mapping[str, Any]) -> dict[str, Any]:
    start = _time_value(None, raw.get("start"))
    end = _time_value(None, raw.get("end"))
    created = _time_value(None, raw.get("created"))
    return {
        "run_id": raw.get("run_id"),
        "start": start[0],
        "start_ts": start[1],
        "end": end[0],
        "end_ts": end[1],
        "closed_incorrect": _optional_bool(raw.get("closed_incorrect")),
        "created": created[0],
        "created_ts": created[1],
    }


def _time_value(timestamp: Any, fallback: Any) -> tuple[str | None, float | None]:
    if timestamp is not None and not isinstance(timestamp, datetime):
        try:
            epoch = float(timestamp)
        except (TypeError, ValueError):
            epoch = None
        if epoch is not None and math.isfinite(epoch):
            return _iso_from_epoch(epoch), epoch
    if isinstance(timestamp, datetime):
        aware = _as_utc(timestamp)
        return aware.isoformat(), aware.timestamp()
    if isinstance(fallback, datetime):
        aware = _as_utc(fallback)
        return aware.isoformat(), aware.timestamp()
    return None, None


def _iso_from_epoch(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _origin(value: Any) -> str | None:
    if value is None:
        return None
    try:
        index = int(value)
    except (TypeError, ValueError):
        return str(value)
    if index == 0:
        return "local"
    if index == 1:
        return "remote"
    return str(index)


def _hex_id(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.lower()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return str(value)


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None
