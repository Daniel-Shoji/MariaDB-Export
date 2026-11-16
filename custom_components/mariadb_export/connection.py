"""Resolve the connection stored on a config entry."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .const import (
    CONF_DATABASE,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SOURCE,
    CONF_SSL,
    CONF_UNIX_SOCKET,
    CONF_USERNAME,
    SOURCE_MANUAL,
    SOURCE_RECORDER,
)
from .exporter.models import ConnectionConfig, ExportError
from .exporter.urls import parse_db_url


class RecorderUnavailable(ExportError):
    """The recorder database URL is not available yet."""


def resolve_connection(
    entry_data: Mapping[str, Any], recorder_url: str | None
) -> ConnectionConfig:
    """Return the connection for an entry.

    Recorder-backed entries read the live recorder URL, including its password,
    so the password is not copied into this integration's config entry.
    """

    if entry_data.get(CONF_SOURCE, SOURCE_MANUAL) == SOURCE_RECORDER:
        if not recorder_url:
            raise RecorderUnavailable("The recorder is not running.")
        return parse_db_url(recorder_url)
    socket = entry_data.get(CONF_UNIX_SOCKET) or None
    return ConnectionConfig(
        host=str(entry_data.get(CONF_HOST) or "localhost"),
        port=int(entry_data[CONF_PORT]),
        database=str(entry_data[CONF_DATABASE]),
        username=str(entry_data[CONF_USERNAME]),
        password=str(entry_data.get(CONF_PASSWORD, "")),
        unix_socket=str(socket) if socket else None,
        ssl=bool(entry_data.get(CONF_SSL, False)),
    )


def manual_entry_data(config: ConnectionConfig) -> dict[str, Any]:
    """Serialize a manual connection, including its password."""

    data: dict[str, Any] = {
        CONF_SOURCE: SOURCE_MANUAL,
        CONF_HOST: config.host,
        CONF_PORT: config.port,
        CONF_DATABASE: config.database,
        CONF_USERNAME: config.username,
        CONF_PASSWORD: config.password,
        CONF_SSL: config.ssl,
    }
    if config.unix_socket:
        data[CONF_UNIX_SOCKET] = config.unix_socket
    return data


def recorder_entry_data() -> dict[str, Any]:
    """Serialize a recorder-backed entry without copying the password."""

    return {CONF_SOURCE: SOURCE_RECORDER}


def unique_id_for(source: str, config: ConnectionConfig) -> str:
    """Return the unique id for this entry."""

    if source == SOURCE_RECORDER:
        return SOURCE_RECORDER
    return f"{SOURCE_MANUAL}:{config.identity()}"


def title_for(source: str, config: ConnectionConfig) -> str:
    """Return the title shown in the integrations list."""

    if source == SOURCE_RECORDER:
        return f"Recorder ({config.database})"
    if config.unix_socket:
        return f"{config.database} @ {config.unix_socket}"
    return f"{config.database} @ {config.host}"
