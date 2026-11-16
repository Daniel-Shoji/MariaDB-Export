"""Tests for recorder SELECT generation."""

from __future__ import annotations

from datetime import UTC, datetime

from exporter.models import Dataset
from exporter.queries import build_query
from support import legacy_schema, modern_schema, request


def test_modern_states_join_metadata_and_keep_values_as_parameters() -> None:
    """Current schemas read entity ids from states_meta."""

    built = build_query(
        modern_schema(),
        request(
            entity_ids=("sensor.kitchen",),
            changed_only=True,
            include_context=True,
        ),
    )

    assert "JOIN states_meta" in built.sql
    assert "shared_attrs" in built.sql
    assert "s.entity_id" not in built.sql
    assert "last_changed_ts IS NULL" in built.sql
    assert "s.last_updated_ts >=" in built.sql
    assert "s.last_updated_ts <" in built.sql
    assert "context_id_bin" in built.sql
    assert "sensor.kitchen" not in built.sql
    assert "sensor.kitchen" in built.params
    assert built.params[-1] == 11
    assert "attributes" in built.columns
    assert "origin" in built.columns
    assert built.id_field == "state_id"


def test_legacy_states_read_the_old_columns() -> None:
    """Older databases still store the entity and attributes on states."""

    built = build_query(legacy_schema(), request(entity_ids=("light.kitchen",)))

    assert "states_meta" not in built.sql
    assert "s.entity_id IN" in built.sql
    assert "s.attributes AS attributes" in built.sql
    assert "s.last_updated >=" in built.sql
    assert isinstance(built.params[1], datetime)
    assert built.params[1].tzinfo is None


def test_events_statistics_and_runs_use_their_own_tables() -> None:
    """Each dataset points at the recorder table that holds it."""

    schema = modern_schema()
    events = build_query(
        schema,
        request(dataset=Dataset.EVENTS, event_types=("automation_triggered",)),
    )
    assert "JOIN event_types" in events.sql
    assert "shared_data" in events.sql
    assert events.params[0] == "automation_triggered"

    statistics = build_query(
        schema,
        request(
            dataset=Dataset.STATISTICS_SHORT_TERM,
            statistic_ids=("sensor.kitchen",),
        ),
    )
    assert "FROM `statistics_short_term`" in statistics.sql
    assert "JOIN statistics_meta" in statistics.sql
    assert "s.`sum`" in statistics.sql
    assert "mean_type_value" in statistics.columns
    assert statistics.params[0] == "sensor.kitchen"

    runs = build_query(schema, request(dataset=Dataset.RECORDER_RUNS))
    assert "FROM `recorder_runs`" in runs.sql
    assert runs.time_field == "start"


def test_resume_cursor_uses_the_time_and_the_id() -> None:
    """A truncated export can continue without repeating the last row."""

    moment = datetime(2026, 1, 1, 6, tzinfo=UTC)
    built = build_query(
        modern_schema(),
        request(after_time=moment, after_id=40),
    )

    assert "s.state_id > %s" in built.sql
    assert built.params[-2] == 40
    assert 40 in built.params
