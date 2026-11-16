"""Tests for URLs, paths, and request defaults."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from exporter.form import connection_from_fields
from exporter.models import (
    Dataset,
    InvalidConnection,
    NotMariaDBError,
    RequestError,
    UnsafePath,
)
from exporter.paths import build_filename, safe_filename, validate_export_dir
from exporter.requests import build_request, complete_request
from exporter.urls import parse_db_url
from support import request


def test_parse_recorder_urls() -> None:
    """MariaDB URLs keep the account, and other engines are refused."""

    parsed = parse_db_url(
        "mysql+pymysql://ha_export:p%40ss@10.0.0.8:3307/homeassistant?charset=utf8mb4"
    )
    assert parsed.host == "10.0.0.8"
    assert parsed.port == 3307
    assert parsed.username == "ha_export"
    assert parsed.password == "p@ss"
    assert parsed.database == "homeassistant"
    assert parsed.ssl is False

    socketed = parse_db_url(
        "mariadb+aiomysql://reader:secret@/homeassistant?unix_socket=/run/mysqld/mysqld.sock&ssl=true"
    )
    assert socketed.unix_socket == "/run/mysqld/mysqld.sock"
    assert socketed.ssl is True
    assert socketed.host == "localhost"

    with pytest.raises(NotMariaDBError) as raised:
        parse_db_url("sqlite:////config/home-assistant_v2.db")
    assert raised.value.scheme == "sqlite"


def test_manual_fields_require_a_host_or_socket() -> None:
    """A blank host is valid only with a Unix socket."""

    config = connection_from_fields(
        host="",
        port="3306",
        database="homeassistant",
        username="ha_export",
        password="secret",
        unix_socket="/run/mysqld/mysqld.sock",
        ssl=False,
    )
    assert config.unix_socket == "/run/mysqld/mysqld.sock"
    assert config.port == 3306

    with pytest.raises(InvalidConnection) as raised:
        connection_from_fields(
            host="",
            port=3306,
            database="homeassistant",
            username="ha_export",
            password="",
            unix_socket="",
            ssl=False,
        )
    assert raised.value.code == "missing_host"


def test_export_directory_stays_inside_config() -> None:
    """Absolute paths and parent segments are refused."""

    root = Path("/config")
    assert validate_export_dir(root, "mariadb_export") == Path("/config/mariadb_export")
    assert validate_export_dir(root, "exports/history") == Path(
        "/config/exports/history"
    )
    for relative in ("../secrets", "/etc/passwd", "foo/../../etc", ""):
        with pytest.raises(UnsafePath):
            validate_export_dir(root, relative)


def test_file_names_are_basenames_with_the_chosen_extension() -> None:
    """User file names cannot choose a directory or a different extension."""

    assert safe_filename("../kitchen.csv", "json") == "kitchen.json"
    assert safe_filename("room temperature", "csv") == "room_temperature.csv"
    named = request(filename="kitchen.csv")
    assert build_filename(named, datetime(2026, 1, 2, tzinfo=UTC)) == "kitchen.csv"


def test_omitted_times_use_the_dataset_window() -> None:
    """States default to the last day, and custom queries keep the caller's SQL."""

    now = datetime(2026, 6, 15, 12, tzinfo=UTC)
    states = complete_request(request(start=None, end=None), now)
    assert states.end == now
    assert states.start == now - timedelta(days=1)

    statistics = build_request(
        dataset="statistics",
        export_format=None,
        default_format="jsonl",
        start=None,
        end=None,
        entity_ids=["sensor.kitchen"],
        event_types=(),
        statistic_ids=(),
        query=None,
        limit=None,
        default_limit=100,
        max_limit=1000,
        include_attributes=True,
        include_context=False,
        changed_only=False,
        after_time=None,
        after_id=None,
        filename=None,
        now=now,
    )
    assert statistics.dataset is Dataset.STATISTICS
    assert statistics.export_format.value == "jsonl"
    assert statistics.statistic_ids == ("sensor.kitchen",)
    assert statistics.entity_ids == ()
    assert statistics.limit == 100
    assert statistics.start == now - timedelta(days=31)

    with pytest.raises(RequestError):
        build_request(
            dataset="custom",
            export_format="csv",
            default_format="csv",
            start=now,
            end=None,
            entity_ids=(),
            event_types=(),
            statistic_ids=(),
            query="SELECT 1",
            limit=10,
            default_limit=10,
            max_limit=100,
            include_attributes=False,
            include_context=False,
            changed_only=False,
            after_time=None,
            after_id=None,
            filename=None,
            now=now,
        )
