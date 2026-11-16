"""Stream export rows to CSV, JSON, or JSON Lines."""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from typing import Any, Protocol, assert_never

from .models import ExportFormat


class RowWriter(Protocol):
    """A streaming file writer."""

    def write(self, row: Mapping[str, Any]) -> None:
        """Write one row."""

    def finish(self) -> None:
        """Close the document, including when no rows were written."""


def open_writer(
    handle: Any, export_format: ExportFormat, columns: tuple[str, ...]
) -> RowWriter:
    """Return a writer for the chosen format."""

    match export_format:
        case ExportFormat.CSV:
            return CsvWriter(handle, columns)
        case ExportFormat.JSON:
            return JsonArrayWriter(handle)
        case ExportFormat.JSONL:
            return JsonLinesWriter(handle)
        case _ as unreachable:
            assert_never(unreachable)


class CsvWriter:
    """CSV with a header row, including when the export is empty."""

    def __init__(self, handle: Any, columns: tuple[str, ...]) -> None:
        """Prepare a header from the planned columns."""

        self._columns = list(columns)
        self._writer = csv.DictWriter(
            handle,
            fieldnames=self._columns,
            lineterminator="\n",
            extrasaction="ignore",
        )
        self._writer.writeheader()

    def write(self, row: Mapping[str, Any]) -> None:
        """Write one record."""

        self._writer.writerow({key: _csv_value(row.get(key)) for key in self._columns})

    def finish(self) -> None:
        """Nothing remains to close for CSV."""


class JsonArrayWriter:
    """A JSON array written one row at a time."""

    def __init__(self, handle: Any) -> None:
        """Open the array."""

        self._handle = handle
        self._count = 0
        self._handle.write("[")

    def write(self, row: Mapping[str, Any]) -> None:
        """Append one object."""

        if self._count:
            self._handle.write(",")
        self._handle.write("\n")
        json.dump(dict(row), self._handle, ensure_ascii=False, allow_nan=False)
        self._count += 1

    def finish(self) -> None:
        """Close the array."""

        if self._count:
            self._handle.write("\n")
        self._handle.write("]\n")


class JsonLinesWriter:
    """One JSON object per line."""

    def __init__(self, handle: Any) -> None:
        """Store the handle."""

        self._handle = handle

    def write(self, row: Mapping[str, Any]) -> None:
        """Write one line."""

        json.dump(dict(row), self._handle, ensure_ascii=False, allow_nan=False)
        self._handle.write("\n")

    def finish(self) -> None:
        """JSON Lines has no footer."""


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return format(value, ".15g")
    return str(value)
