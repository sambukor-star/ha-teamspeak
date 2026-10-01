"""Sensor-Plattform für die TeamSpeak-Integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import TeamSpeakCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Richtet die TeamSpeak-Sensoren aus einem Config-Entry ein."""
    coordinator: TeamSpeakCoordinator = entry.runtime_data.coordinator
    async_add_entities([TeamSpeakClientsOnlineSensor(coordinator, entry)])


class TeamSpeakSensorBase(CoordinatorEntity[TeamSpeakCoordinator], SensorEntity):
    """Gemeinsame Basis für TeamSpeak-Sensoren."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: TeamSpeakCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        host = str(entry.data.get("host", "teamspeak"))
        self._attr_device_info = DeviceInfo(
            identifiers={("teamspeak", entry.entry_id)},
            name=f"TeamSpeak {host}",
            manufacturer="TeamSpeak Systems GmbH",
            model="TeamSpeak 3 Server",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._entry = entry

    @property
    def _server_version(self) -> str | None:
        """Serverversion aus Willkommenszeile oder serverinfo."""
        version = self.coordinator.client.welcome_version
        if version:
            return str(version)
        serverinfo = (self.coordinator.data or {}).get("serverinfo") or {}
        return str(serverinfo["virtualserver_version"]) if "virtualserver_version" in serverinfo else None


class TeamSpeakClientsOnlineSensor(TeamSpeakSensorBase):
    """Sensor, der die Anzahl der verbundenen Clients anzeigt."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: TeamSpeakCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_clients_online"
        self._attr_name = "Clients online"
        self._attr_native_unit_of_measurement = "Clients"

    @property
    def native_value(self) -> int | None:
        """Aktuelle Anzahl der (Nicht-Query-)Clients."""
        data = self.coordinator.data
        if data is None:
            return None
        return int(data.get("count") or 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Clients und Serverinformationen als Attribute bereitstellen."""
        data = self.coordinator.data
        if data is None:
            return None

        serverinfo = data.get("serverinfo") or {}
        clients = data.get("clients") or []

        channel_clients: dict[str, int] = {}
        for client in clients:
            channel = str(client.get("channel") or "Unbekannt")
            channel_clients[channel] = channel_clients.get(channel, 0) + 1

        attrs: dict[str, Any] = {
            "server_name": str(serverinfo.get("virtualserver_name", "TeamSpeak 3 Server")),
            "server_version": self._server_version,
            "clients_online": int(data.get("count") or 0),
            "channel_clients": channel_clients,
            "clients": clients,
        }
        try:
            attrs["server_maxclients"] = int(serverinfo.get("virtualserver_maxclients") or 0)
        except (TypeError, ValueError):
            pass
        return attrs