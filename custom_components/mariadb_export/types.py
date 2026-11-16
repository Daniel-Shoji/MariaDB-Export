"""Types shared by the Home Assistant wiring."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .exporter.status import ExportStatus


@dataclass
class RuntimeData:
    """Per-entry state kept while the integration is loaded."""

    status: ExportStatus
    version: str
    busy: bool = False


class MariaDBConfigEntry(ConfigEntry[RuntimeData]):
    """Config entry with runtime data."""


@dataclass
class DomainData:
    """Process-wide bookkeeping for the integration."""

    entries: int = 0
