"""Sensor for the most recent MariaDB export."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from .const import DOMAIN
from .types import MariaDBConfigEntry


async def async_setup_entry(
    hass: Any,
    entry: MariaDBConfigEntry,
    async_add_entities: Any,
) -> None:
    """Create the status sensor for one database."""

    async_add_entities([LastExportSensor(entry)])


class LastExportSensor(SensorEntity):
    """Shows whether the latest export succeeded."""

    _attr_has_entity_name = True
    _attr_translation_key = "last_export"
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: MariaDBConfigEntry) -> None:
        """Attach the sensor to the config entry."""

        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_last_export"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="MariaDB Export",
            model="Home Assistant recorder",
            sw_version=entry.runtime_data.version,
        )

    async def async_added_to_hass(self) -> None:
        """Refresh when an export updates the shared status."""

        self.async_on_remove(
            self._entry.runtime_data.status.listen(self.async_write_ha_state)
        )

    @property
    def native_value(self) -> str:
        """Return idle, running, success, or error."""

        return self._entry.runtime_data.status.state.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the file and row count from the latest export."""

        status = self._entry.runtime_data.status
        attributes: dict[str, Any] = {
            "rows": status.rows,
            "dataset": status.dataset,
            "format": status.export_format,
            "file": status.file,
            "truncated": status.truncated,
            "finished_at": status.finished_at,
            "server_version": status.server_version,
            "last_id": status.last_id,
            "last_time": status.last_time,
        }
        if status.error:
            attributes["error"] = status.error
        if status.warnings:
            attributes["warnings"] = list(status.warnings)
        return attributes
