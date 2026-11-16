"""MariaDB Export for Home Assistant."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.loader import async_get_integration

from .connection import RecorderUnavailable, resolve_connection
from .const import (
    CONF_AFTER_ID,
    CONF_AFTER_TIME,
    CONF_CHANGED_ONLY,
    CONF_CONFIG_ENTRY,
    CONF_DATASET,
    CONF_DEFAULT_FORMAT,
    CONF_DEFAULT_LIMIT,
    CONF_END,
    CONF_ENTITY_ID,
    CONF_EVENT_TYPE,
    CONF_EXPORT_DIR,
    CONF_FILENAME,
    CONF_FORMAT,
    CONF_INCLUDE_ATTRIBUTES,
    CONF_INCLUDE_CONTEXT,
    CONF_LIMIT,
    CONF_QUERY,
    CONF_START,
    CONF_STATEMENT_TIMEOUT,
    CONF_STATISTIC_ID,
    DEFAULT_FORMAT,
    DEFAULT_LIMIT,
    DEFAULT_OPTIONS,
    DEFAULT_STATEMENT_TIMEOUT,
    DOMAIN,
    MAX_LIMIT,
    MAX_STATEMENT_TIMEOUT,
    PLATFORMS,
    SERVICE_EXPORT,
)
from .exporter.models import (
    ConnectionConfig,
    Dataset,
    ExportError,
    ExportFormat,
    ExportRequest,
    ExportResult,
    InvalidAuth,
    RequestError,
)
from .exporter.paths import validate_export_dir
from .exporter.requests import build_request
from .exporter.session import MariaDBSession, ping_database
from .exporter.status import ExportStatus
from .recorder_url import recorder_database_url
from .types import DomainData, MariaDBConfigEntry, RuntimeData

_LOGGER = logging.getLogger(__name__)

_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_CONFIG_ENTRY): cv.string,
        vol.Required(CONF_DATASET): vol.In({item.value for item in Dataset}),
        vol.Optional(CONF_START): cv.datetime,
        vol.Optional(CONF_END): cv.datetime,
        vol.Optional(CONF_ENTITY_ID): cv.entity_ids,
        vol.Optional(CONF_EVENT_TYPE): vol.Any(cv.string, [cv.string]),
        vol.Optional(CONF_STATISTIC_ID): vol.Any(cv.string, [cv.string]),
        vol.Optional(CONF_FORMAT): vol.In({item.value for item in ExportFormat}),
        vol.Optional(CONF_QUERY): cv.string,
        vol.Optional(CONF_LIMIT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_LIMIT)
        ),
        vol.Optional(CONF_FILENAME): cv.string,
        vol.Optional(CONF_INCLUDE_ATTRIBUTES, default=True): cv.boolean,
        vol.Optional(CONF_INCLUDE_CONTEXT, default=False): cv.boolean,
        vol.Optional(CONF_CHANGED_ONLY, default=False): cv.boolean,
        vol.Optional(CONF_AFTER_TIME): cv.datetime,
        vol.Optional(CONF_AFTER_ID): vol.All(vol.Coerce(int), vol.Range(min=0)),
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: MariaDBConfigEntry) -> bool:
    """Connect to MariaDB and register the export action."""

    config = _connection_for_entry(hass, entry)
    try:
        version = await hass.async_add_executor_job(ping_database, config)
    except InvalidAuth as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except ExportError as err:
        raise ConfigEntryNotReady(str(err)) from err
    export_dir = str(
        entry.options.get(CONF_EXPORT_DIR, DEFAULT_OPTIONS[CONF_EXPORT_DIR])
    )
    try:
        directory = validate_export_dir(Path(hass.config.config_dir), export_dir)
        directory.mkdir(parents=True, exist_ok=True)
    except ExportError as err:
        raise ConfigEntryError(str(err)) from err
    except OSError as err:
        raise ConfigEntryNotReady("The export folder could not be created.") from err
    integration = await async_get_integration(hass, DOMAIN)
    status = ExportStatus()
    status.server_version = version
    entry.runtime_data = RuntimeData(status=status, version=integration.version or "0")
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    domain = hass.data.setdefault(DOMAIN, DomainData())
    domain.entries += 1
    if not hass.services.has_service(DOMAIN, SERVICE_EXPORT):

        async def _handler(call: ServiceCall) -> dict[str, Any]:
            return await _async_handle_export(hass, call)

        hass.services.async_register(
            DOMAIN,
            SERVICE_EXPORT,
            _handler,
            schema=_SERVICE_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MariaDBConfigEntry) -> bool:
    """Unload one database."""

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unloaded:
        return False
    domain: DomainData = hass.data[DOMAIN]
    domain.entries -= 1
    if domain.entries <= 0:
        hass.services.async_remove(DOMAIN, SERVICE_EXPORT)
        hass.data.pop(DOMAIN, None)
    return True


def _connection_for_entry(hass: HomeAssistant, entry: MariaDBConfigEntry) -> Any:
    try:
        return resolve_connection(entry.data, recorder_database_url(hass))
    except RecorderUnavailable as err:
        raise ConfigEntryNotReady(str(err)) from err
    except ExportError as err:
        raise ConfigEntryError(str(err)) from err


async def _async_handle_export(
    hass: HomeAssistant, call: ServiceCall
) -> dict[str, Any]:
    entry = _entry_for_call(hass, call)
    runtime = entry.runtime_data
    if runtime.busy:
        raise HomeAssistantError("An export is already running for this database.")
    options = {**DEFAULT_OPTIONS, **entry.options}
    data = call.data
    try:
        request = build_request(
            dataset=str(data[CONF_DATASET]),
            export_format=data.get(CONF_FORMAT),
            default_format=str(options.get(CONF_DEFAULT_FORMAT, DEFAULT_FORMAT)),
            start=data.get(CONF_START),
            end=data.get(CONF_END),
            entity_ids=data.get(CONF_ENTITY_ID, ()),
            event_types=data.get(CONF_EVENT_TYPE, ()),
            statistic_ids=data.get(CONF_STATISTIC_ID, ()),
            query=data.get(CONF_QUERY),
            limit=data.get(CONF_LIMIT),
            default_limit=int(options.get(CONF_DEFAULT_LIMIT, DEFAULT_LIMIT)),
            max_limit=MAX_LIMIT,
            include_attributes=bool(data[CONF_INCLUDE_ATTRIBUTES]),
            include_context=bool(data[CONF_INCLUDE_CONTEXT]),
            changed_only=bool(data[CONF_CHANGED_ONLY]),
            after_time=data.get(CONF_AFTER_TIME),
            after_id=data.get(CONF_AFTER_ID),
            filename=data.get(CONF_FILENAME),
            now=datetime.now(UTC),
        )
    except RequestError as err:
        raise ServiceValidationError(str(err)) from err
    timeout = int(options.get(CONF_STATEMENT_TIMEOUT, DEFAULT_STATEMENT_TIMEOUT))
    timeout = min(max(timeout, 0), MAX_STATEMENT_TIMEOUT)
    try:
        directory = validate_export_dir(
            Path(hass.config.config_dir),
            str(options.get(CONF_EXPORT_DIR, DEFAULT_OPTIONS[CONF_EXPORT_DIR])),
        )
        config = resolve_connection(entry.data, recorder_database_url(hass))
    except ExportError as err:
        raise ServiceValidationError(str(err)) from err
    runtime.busy = True
    runtime.status.mark_running(request.dataset.value)
    try:
        result = await hass.async_add_executor_job(
            _run_export,
            config,
            request,
            directory,
            timeout,
        )
    except RequestError as err:
        runtime.status.mark_error(str(err), finished_at=_now())
        raise ServiceValidationError(str(err)) from err
    except ExportError as err:
        runtime.status.mark_error(str(err), finished_at=_now())
        raise HomeAssistantError(str(err)) from err
    except Exception as err:
        _LOGGER.exception("MariaDB export failed")
        runtime.status.mark_error("Export failed.", finished_at=_now())
        raise HomeAssistantError("Export failed.") from err
    finally:
        runtime.busy = False
    relative = result.path.resolve().relative_to(Path(hass.config.config_dir).resolve())
    finished = _now()
    runtime.status.mark_success(
        rows=result.rows,
        dataset=result.dataset,
        export_format=result.export_format,
        file=relative.as_posix(),
        truncated=result.truncated,
        warnings=result.warnings,
        last_id=result.last_id,
        last_time=result.last_time,
        finished_at=finished,
    )
    payload = {
        "path": relative.as_posix(),
        "rows": result.rows,
        "truncated": result.truncated,
        "last_id": result.last_id,
        "last_time": result.last_time,
        "bytes": result.bytes_written,
        "dataset": result.dataset,
        "format": result.export_format,
        "warnings": list(result.warnings),
    }
    _LOGGER.info(
        "Exported %s %s rows to %s",
        result.rows,
        result.dataset,
        relative.as_posix(),
    )
    hass.bus.async_fire(
        "mariadb_export_completed",
        {"entry_id": entry.entry_id, **payload},
    )
    return payload


def _run_export(
    config: ConnectionConfig,
    request: ExportRequest,
    directory: Path,
    statement_timeout: int,
) -> ExportResult:
    """Run the blocking export on the executor thread."""

    return MariaDBSession(config).export(
        request,
        directory,
        statement_timeout=statement_timeout,
    )


def _entry_for_call(hass: HomeAssistant, call: ServiceCall) -> MariaDBConfigEntry:
    loaded = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    requested = call.data.get(CONF_CONFIG_ENTRY)
    if requested:
        matches = [entry for entry in loaded if entry.entry_id == requested]
        if not matches:
            raise ServiceValidationError("Choose a configured MariaDB Export entry.")
        return matches[0]
    if len(loaded) == 1:
        return loaded[0]
    if not loaded:
        raise HomeAssistantError("MariaDB Export is not ready.")
    raise ServiceValidationError(
        "More than one database is configured. Choose a config entry."
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
