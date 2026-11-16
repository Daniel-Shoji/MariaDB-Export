"""Safe file names and directories for exports."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from .models import ExportFormat, ExportRequest, UnsafePath

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_KNOWN_EXTENSIONS = (".csv", ".json", ".jsonl")
_MAX_NAME = 180


def validate_export_dir(config_dir: Path, relative: str) -> Path:
    """Resolve an export folder and keep it inside the config directory."""

    cleaned = relative.strip().replace("\\", "/")
    if not cleaned or cleaned.startswith("/"):
        raise UnsafePath("Choose an export folder inside the config directory.")
    parts = Path(cleaned).parts
    if not parts or ".." in parts:
        raise UnsafePath("Choose an export folder inside the config directory.")
    root = config_dir.resolve()
    target = (root / cleaned).resolve()
    if target != root and root not in target.parents:
        raise UnsafePath("Choose an export folder inside the config directory.")
    return target


def build_filename(request: ExportRequest, now: datetime) -> str:
    """Return a file name for this export."""

    if request.filename:
        return safe_filename(request.filename, request.export_format.extension)
    stamp = _clock(now)
    start = _bound_stamp(request.start)
    end = _bound_stamp(request.end)
    stem = f"{request.dataset.value}_{start}_{end}_{stamp}"
    return safe_filename(stem, request.export_format.extension)


def safe_filename(name: str, extension: str) -> str:
    """Reduce a file name to a single safe basename with the right extension."""

    if extension not in {item.value for item in ExportFormat}:
        raise UnsafePath("Choose a csv, json, or jsonl export.")
    base = Path(name).name
    cleaned = _UNSAFE.sub("_", base).strip("._")
    if not cleaned:
        raise UnsafePath("Enter a file name.")
    lower = cleaned.lower()
    for known in _KNOWN_EXTENSIONS:
        if lower.endswith(known):
            cleaned = cleaned[: -len(known)].strip("._")
            break
    if not cleaned:
        raise UnsafePath("Enter a file name.")
    return f"{cleaned}.{extension}"[:_MAX_NAME]


def _clock(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _bound_stamp(value: datetime | None) -> str:
    if value is None:
        return "open"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
