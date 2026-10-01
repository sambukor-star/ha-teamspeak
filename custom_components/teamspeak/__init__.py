"""Die TeamSpeak-Integration (TeamSpeak-3-ServerQuery)."""

from __future__ import annotations

import logging

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from .api import DEFAULT_PORT, TeamSpeakServerQuery
from .const import DEFAULT_SCAN_INTERVAL
from .coordinator import TeamSpeakCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup_entry(
    hass: HomeAssistant, entry: TeamSpeakConfigEntry
) -> bool:
    """Richtet die TeamSpeak-Integration aus einem Config-Entry ein."""
    client = TeamSpeakServerQuery(
        host=entry.data[CONF_HOST],
        port=int(entry.data.get(CONF_PORT) or DEFAULT_PORT),
    )
    coordinator = TeamSpeakCoordinator(hass, client, entry)

    # Schlägt der erste Login fehl, wird der Reauth-Flow angestoßen.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = TeamSpeakRuntimeData(coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: TeamSpeakConfigEntry
) -> bool:
    """Entlädt die TeamSpeak-Integration."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry.runtime_data = None
    return unload_ok


class TeamSpeakConfigEntry:
    """Duck-Typing-Annotierung für den Config-Entry der Integration."""

    runtime_data: TeamSpeakRuntimeData | None


class TeamSpeakRuntimeData:
    """Laufzeitdaten des Entries (Koordinator)."""

    __slots__ = ("coordinator",)

    def __init__(self, coordinator: TeamSpeakCoordinator) -> None:
        self.coordinator = coordinator