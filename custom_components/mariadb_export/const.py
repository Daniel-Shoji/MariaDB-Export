"""Constants for the MariaDB Export integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import (
    CONF_ENTITY_ID,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    Platform,
)

DOMAIN: Final = "mariadb_export"
SERVICE_EXPORT: Final = "export"

CONF_DATABASE: Final = "database"
CONF_UNIX_SOCKET: Final = "unix_socket"
CONF_SSL: Final = "ssl"
CONF_SOURCE: Final = "source"
SOURCE_MANUAL: Final = "manual"
SOURCE_RECORDER: Final = "recorder"

CONF_EXPORT_DIR: Final = "export_dir"
CONF_DEFAULT_FORMAT: Final = "default_format"
CONF_DEFAULT_LIMIT: Final = "default_limit"
CONF_STATEMENT_TIMEOUT: Final = "statement_timeout"

CONF_DATASET: Final = "dataset"
CONF_FORMAT: Final = "format"
CONF_QUERY: Final = "query"
CONF_LIMIT: Final = "limit"
CONF_FILENAME: Final = "filename"
CONF_INCLUDE_ATTRIBUTES: Final = "include_attributes"
CONF_INCLUDE_CONTEXT: Final = "include_context"
CONF_CHANGED_ONLY: Final = "changed_only"
CONF_EVENT_TYPE: Final = "event_type"
CONF_STATISTIC_ID: Final = "statistic_id"
CONF_CONFIG_ENTRY: Final = "config_entry"
CONF_START: Final = "start"
CONF_END: Final = "end"
CONF_AFTER_TIME: Final = "after_time"
CONF_AFTER_ID: Final = "after_id"

DEFAULT_EXPORT_DIR: Final = "mariadb_export"
DEFAULT_FORMAT: Final = "csv"
DEFAULT_LIMIT: Final = 250_000
MAX_LIMIT: Final = 2_000_000
DEFAULT_STATEMENT_TIMEOUT: Final = 900
MAX_STATEMENT_TIMEOUT: Final = 86_400

PLATFORMS: Final = [Platform.SENSOR]

DEFAULT_OPTIONS: Final = {
    CONF_EXPORT_DIR: DEFAULT_EXPORT_DIR,
    CONF_DEFAULT_FORMAT: DEFAULT_FORMAT,
    CONF_DEFAULT_LIMIT: DEFAULT_LIMIT,
    CONF_STATEMENT_TIMEOUT: DEFAULT_STATEMENT_TIMEOUT,
}

__all__ = [
    "CONF_AFTER_ID",
    "CONF_AFTER_TIME",
    "CONF_CHANGED_ONLY",
    "CONF_CONFIG_ENTRY",
    "CONF_DATABASE",
    "CONF_DATASET",
    "CONF_DEFAULT_FORMAT",
    "CONF_DEFAULT_LIMIT",
    "CONF_END",
    "CONF_ENTITY_ID",
    "CONF_EVENT_TYPE",
    "CONF_EXPORT_DIR",
    "CONF_FILENAME",
    "CONF_FORMAT",
    "CONF_HOST",
    "CONF_INCLUDE_ATTRIBUTES",
    "CONF_INCLUDE_CONTEXT",
    "CONF_LIMIT",
    "CONF_PASSWORD",
    "CONF_PORT",
    "CONF_QUERY",
    "CONF_SOURCE",
    "CONF_SSL",
    "CONF_START",
    "CONF_STATEMENT_TIMEOUT",
    "CONF_STATISTIC_ID",
    "CONF_UNIX_SOCKET",
    "CONF_USERNAME",
    "DEFAULT_EXPORT_DIR",
    "DEFAULT_FORMAT",
    "DEFAULT_LIMIT",
    "DEFAULT_OPTIONS",
    "DEFAULT_STATEMENT_TIMEOUT",
    "DOMAIN",
    "MAX_LIMIT",
    "MAX_STATEMENT_TIMEOUT",
    "PLATFORMS",
    "SERVICE_EXPORT",
    "SOURCE_MANUAL",
    "SOURCE_RECORDER",
]
