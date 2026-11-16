"""Tests for the read-only SQL guard."""

from __future__ import annotations

import pytest

from exporter.models import RequestError
from exporter.sql_guard import prepare_custom, validate_select


def test_select_and_cte_are_allowed() -> None:
    """Plain reads pass through."""

    assert validate_select("  SELECT 1  ") == "SELECT 1"
    assert validate_select("WITH c AS (SELECT 1) SELECT * FROM c")
    assert validate_select("SELECT 1;") == "SELECT 1"
    assert (
        validate_select("SELECT 'delete this' AS label")
        == "SELECT 'delete this' AS label"
    )
    assert validate_select("-- note\nSELECT 1") == "-- note\nSELECT 1"
    assert (
        validate_select("SELECT 1 /* into outfile */") == "SELECT 1 /* into outfile */"
    )
    assert "REPLACE(" in validate_select("SELECT REPLACE(state, ',', ' ')")


def test_writes_and_multiple_statements_are_rejected() -> None:
    """Writes, stacked statements, and server-side file access are rejected."""

    rejected = [
        "INSERT INTO states VALUES (1)",
        "SELECT 1; DROP TABLE states",
        "SELECT * FROM states INTO OUTFILE '/tmp/x'",
        "SELECT SLEEP(10)",
        "SELECT LOAD_FILE('/etc/passwd')",
        "UPDATE states SET state = '1'",
        "SELECT * FROM states FOR UPDATE",
        "REPLACE INTO states VALUES (1)",
        "",
        "/* unfinished",
        "SELECT 'unterminated",
    ]
    for sql in rejected:
        with pytest.raises(RequestError):
            validate_select(sql)


def test_custom_query_is_wrapped_with_a_limit() -> None:
    """The server is asked to stop after the requested number of rows."""

    sql, params = prepare_custom(
        "SELECT entity_id FROM states_meta ORDER BY entity_id",
        25,
    )

    assert "mariadb_export_query" in sql
    assert sql.endswith("LIMIT %s")
    assert "LIMIT 18446744073709551615" in sql
    assert params == (26,)
