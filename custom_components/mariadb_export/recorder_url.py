"""Read the recorder database URL from Home Assistant."""

from __future__ import annotations

from homeassistant.components.recorder import get_instance
from homeassistant.core import HomeAssistant


def recorder_database_url(hass: HomeAssistant) -> str | None:
    """Return the recorder URL when the recorder is running."""

    try:
        instance = get_instance(hass)
    except KeyError:
        return None
    url = getattr(instance, "db_url", None)
    if isinstance(url, str) and url:
        return url
    return None
