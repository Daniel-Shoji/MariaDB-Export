"""Tests for row conversion and file writers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from exporter.models import Dataset, ExportFormat
from exporter.normalize import freeze, normalize_row
from exporter.writers import open_writer


def test_state_rows_fill_a_null_last_changed_from_last_updated() -> None:
    """NULL last_changed_ts means the state changed at last_updated_ts."""

    row = normalize_row(
        Dataset.STATES,
        {
            "state_id": 7,
            "entity_id": "sensor.kitchen",
            "state": "21.5",
            "attributes": '{"unit_of_measurement":"°C"}',
            "last_updated_ts": 1767225600.0,
            "last_changed_ts": None,
            "last_reported_ts": None,
            "origin_idx": 0,
            "context_id_bin": bytes.fromhex("00112233445566778899aabbccddeeff"),
        },
        (
            "state_id",
            "entity_id",
            "state",
            "attributes",
            "last_updated",
            "last_updated_ts",
            "last_changed",
            "last_changed_ts",
            "origin",
            "context_id",
        ),
    )

    assert row["last_changed"] == row["last_updated"]
    assert row["last_changed_ts"] is None
    assert row["last_updated"].startswith("2026-")
    assert row["origin"] == "local"
    assert row["context_id"] == "00112233445566778899aabbccddeeff"
    assert "°C" in row["attributes"]


def test_statistics_name_the_mean_type() -> None:
    """mean_type integers become none, arithmetic, or circular."""

    row = normalize_row(
        Dataset.STATISTICS,
        {
            "id": 3,
            "statistic_id": "sensor.wind_direction",
            "mean_type": 2,
            "has_sum": 0,
            "start_ts": 1767225600,
            "mean": Decimal("10.5"),
            "sum": 4,
        },
        (
            "id",
            "statistic_id",
            "mean_type",
            "mean_type_value",
            "has_sum",
            "start",
            "mean",
        ),
    )

    assert row["mean_type"] == "circular"
    assert row["mean_type_value"] == 2
    assert row["has_sum"] is False
    assert row["mean"] == "10.5"
    assert row["start"] is not None


def test_freeze_makes_values_safe_for_json() -> None:
    """Decimals, timestamps, and binary values get a stable text form."""

    assert freeze(Decimal("1.2500")) == "1.2500"
    assert freeze(float("nan")) is None
    assert freeze(datetime(2026, 1, 1, tzinfo=UTC)) == "2026-01-01T00:00:00+00:00"
    assert freeze(b"\x01\x02") == "0102"


def test_writers_include_headers_and_empty_documents(tmp_path) -> None:
    """CSV keeps a header when there are no rows, and JSON stays valid."""

    columns = ("state_id", "entity_id", "ok")
    row = {"state_id": 1, "entity_id": "sensor.kitchen", "ok": True}

    csv_path = tmp_path / "states.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = open_writer(handle, ExportFormat.CSV, columns)
        writer.write(row)
        writer.finish()
    text = csv_path.read_text(encoding="utf-8-sig")
    assert text.splitlines()[0] == "state_id,entity_id,ok"
    assert "true" in text

    empty_csv = tmp_path / "empty.csv"
    with empty_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = open_writer(handle, ExportFormat.CSV, columns)
        writer.finish()
    assert empty_csv.read_text(encoding="utf-8").splitlines() == [
        "state_id,entity_id,ok"
    ]

    json_path = tmp_path / "states.json"
    with json_path.open("w", encoding="utf-8", newline="") as handle:
        writer = open_writer(handle, ExportFormat.JSON, columns)
        writer.write(row)
        writer.finish()
    assert json.loads(json_path.read_text(encoding="utf-8")) == [row]

    lines_path = tmp_path / "states.jsonl"
    with lines_path.open("w", encoding="utf-8", newline="") as handle:
        writer = open_writer(handle, ExportFormat.JSONL, columns)
        writer.write(row)
        writer.finish()
    assert json.loads(lines_path.read_text(encoding="utf-8")) == row
