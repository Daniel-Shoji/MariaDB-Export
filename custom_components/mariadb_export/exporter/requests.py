"""Fill in defaults and reject export calls that do not fit the dataset."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from .models import Dataset, ExportFormat, ExportRequest, RequestError

_MAX_ITEMS = 200
_MAX_ITEM_LENGTH = 255


def build_request(
    *,
    dataset: str,
    export_format: str | None,
    default_format: str,
    start: datetime | None,
    end: datetime | None,
    entity_ids: Sequence[object],
    event_types: Sequence[object],
    statistic_ids: Sequence[object],
    query: str | None,
    limit: object,
    default_limit: int,
    max_limit: int,
    include_attributes: bool,
    include_context: bool,
    changed_only: bool,
    after_time: datetime | None,
    after_id: object,
    filename: str | None,
    now: datetime,
) -> ExportRequest:
    """Build a validated request from a service call."""

    try:
        parsed_dataset = Dataset(dataset)
    except ValueError as err:
        raise RequestError("Choose a dataset.") from err
    chosen_format = export_format or default_format
    try:
        parsed_format = ExportFormat(chosen_format)
    except ValueError as err:
        raise RequestError("Choose a csv, json, or jsonl export.") from err
    entities = string_list(entity_ids)
    events = string_list(event_types)
    statistics = string_list(statistic_ids)
    if parsed_dataset in {Dataset.STATISTICS, Dataset.STATISTICS_SHORT_TERM}:
        if entities and statistics:
            raise RequestError("Use either entity_id or statistic_id for statistics.")
        if entities:
            statistics = entities
            entities = ()
    chosen_limit = default_limit if limit is None else _whole_number(limit, "limit")
    if chosen_limit < 1 or chosen_limit > max_limit:
        raise RequestError(f"The row limit must be from 1 to {max_limit}.")
    request = ExportRequest(
        dataset=parsed_dataset,
        export_format=parsed_format,
        start=start,
        end=end,
        entity_ids=entities,
        event_types=events,
        statistic_ids=statistics,
        query=query,
        limit=chosen_limit,
        include_attributes=include_attributes,
        include_context=include_context,
        changed_only=changed_only,
        after_time=after_time,
        after_id=None if after_id is None else _whole_number(after_id, "after_id"),
        filename=filename,
    )
    return complete_request(request, now)


def string_list(value: Sequence[object] | object) -> tuple[str, ...]:
    """Accept a string, a comma-separated string, or a list of either."""

    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        items: list[str] = []
        for item in value:
            items.extend(string_list(item))
        return tuple(items)
    raise RequestError("Use a list of names.")


def complete_request(request: ExportRequest, now: datetime) -> ExportRequest:
    """Apply the default time window and validate the call."""

    clock = _ensure_utc(now)
    start = _optional_utc(request.start)
    end = _optional_utc(request.end)
    after_time = _optional_utc(request.after_time)
    window = request.dataset.default_window()
    if request.dataset is not Dataset.CUSTOM and start is None and end is None:
        if window is not None:
            end = clock
            start = clock - window
    elif start is not None and end is None and request.dataset is not Dataset.CUSTOM:
        end = clock
    completed = replace(
        request,
        start=start,
        end=end,
        after_time=after_time,
        entity_ids=_clean_items(request.entity_ids, "entity id"),
        event_types=_clean_items(request.event_types, "event type"),
        statistic_ids=_clean_items(request.statistic_ids, "statistic id"),
    )
    validate_request(completed)
    return completed


def validate_request(request: ExportRequest) -> None:
    """Reject combinations that would silently drop a filter."""

    if request.limit < 1:
        raise RequestError("The row limit must be at least 1.")
    if (
        request.start is not None
        and request.end is not None
        and request.end <= request.start
    ):
        raise RequestError("The end time must be after the start time.")
    cursor_parts = (request.after_time is not None, request.after_id is not None)
    if cursor_parts == (True, False) or cursor_parts == (False, True):
        raise RequestError("Resume with both after_time and after_id.")
    if request.after_id is not None and request.after_id < 0:
        raise RequestError("after_id must be zero or greater.")
    dataset = request.dataset
    if dataset is Dataset.CUSTOM:
        if not request.query or not request.query.strip():
            raise RequestError("Enter a SELECT query.")
        if request.start is not None or request.end is not None:
            raise RequestError("Put the time filter in the custom query.")
        if request.after_time is not None or request.after_id is not None:
            raise RequestError("A custom query cannot resume with after_time.")
        if request.entity_ids or request.event_types or request.statistic_ids:
            raise RequestError("Put filters in the custom query.")
        if request.changed_only:
            raise RequestError("changed_only applies to the states dataset.")
        return
    if request.query:
        raise RequestError("query is only used when the dataset is custom.")
    if dataset is not Dataset.STATES and request.entity_ids:
        raise RequestError("entity_id filters the states dataset.")
    if dataset is not Dataset.EVENTS and request.event_types:
        raise RequestError("event_type filters the events dataset.")
    if (
        dataset not in {Dataset.STATISTICS, Dataset.STATISTICS_SHORT_TERM}
        and request.statistic_ids
    ):
        raise RequestError("statistic_id filters statistics datasets.")
    if dataset is not Dataset.STATES and request.changed_only:
        raise RequestError("changed_only applies to the states dataset.")


def _clean_items(items: tuple[str, ...], label: str) -> tuple[str, ...]:
    if len(items) > _MAX_ITEMS:
        raise RequestError(f"Use at most {_MAX_ITEMS} {label} values.")
    cleaned: list[str] = []
    for item in items:
        value = item.strip()
        if not value:
            continue
        if len(value) > _MAX_ITEM_LENGTH or "\x00" in value:
            raise RequestError(f"A {label} value is invalid.")
        cleaned.append(value)
    return tuple(cleaned)


def _optional_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return _ensure_utc(value)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _whole_number(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RequestError(f"{label} must be a whole number.")
    if isinstance(value, float) and not value.is_integer():
        raise RequestError(f"{label} must be a whole number.")
    number = int(value)
    if number < 0:
        raise RequestError(f"{label} must be zero or greater.")
    return number
