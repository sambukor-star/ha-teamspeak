"""Daten-Koordinator für die TeamSpeak-Integration (Abfrageschicht)."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import TS3AuthError, TS3Error, TeamSpeakClientData, TeamSpeakServerQuery
from .const import DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class TeamSpeakCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fragt den TeamSpeak-Server für jeden Zyklus frisch ab.

    ServerQuery-Verbindungen werden vom Server nach kurzer Inaktivität
    getrennt; ein Dauerbetrieb über eine einzige Verbindung würde zudem
    als Flood-Muster auffallen. Deshalb gilt pro Zyklus:
    ``connect -> login -> use -> Abfragen -> quit``.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: TeamSpeakServerQuery,
        entry: Any,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"TeamSpeak {entry.data.get('host', 'Server')}",
            update_interval=timedelta(
                seconds=entry.data.get("interval", DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client
        self._entry = entry

    async def _async_update_data(self) -> dict[str, Any]:
        """Fragt Server-, Kanal- und Clientdaten ab."""
        try:
            return await self._fetch_data()
        except TS3AuthError as err:
            # Löst in Home Assistant automatisch den Reauth-Flow aus.
            raise ConfigEntryAuthFailed(str(err)) from err
        except TS3Error as err:
            raise UpdateFailed(str(err)) from err

    async def _fetch_data(self) -> dict[str, Any]:
        """Führt die eigentlichen ServerQuery-Befehle aus."""
        entry = self._entry
        client = self.client
        await client.connect()
        try:
            await client.login(entry.data["username"], entry.data["password"])
            await client.use_server(int(entry.data.get("sid") or 1))

            serverinfo = await client.serverinfo()
            channels = await client.channellist()
            clientlist = await client.clientlist()

            channel_names = {
                str(ch.get("cid")): str(ch.get("channel_name") or "")
                for ch in channels
            }

            clients: list[dict[str, Any]] = []
            for raw in clientlist:
                if str(raw.get("client_type", "0")) == "1":
                    # ServerQuery-Clients (Typ 1) nicht mitzählen.
                    continue
                clid = str(raw.get("clid"))
                try:
                    detail = await client.clientinfo(clid)
                except TS3Error:
                    _LOGGER.debug("clientinfo für clid=%s fehlgeschlagen", clid)
                    detail = {}
                data = _build_client_data(clid, raw, detail, channel_names)
                clients.append(data.as_dict())

            return {
                "serverinfo": serverinfo,
                "channels": channels,
                "clients": clients,
                "count": len(clients),
            }
        finally:
            await client.close()


def _to_float(value: Any) -> float | None:
    """Verlustarm in float umwandeln (``None`` bei ungültigen Werten)."""
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _build_client_data(
    clid: str,
    raw: dict[str, Any],
    detail: dict[str, Any],
    channel_names: dict[str, str],
) -> TeamSpeakClientData:
    """Führt clientlist- und clientinfo-Daten eines Clients zusammen."""
    idle_ms = _to_float(detail.get("client_idle_time"))
    servergroups: list[int] = []
    for part in str(detail.get("client_servergroups", "") or "").split(","):
        part = part.strip()
        if part:
            try:
                servergroups.append(int(part))
            except ValueError:
                pass

    return TeamSpeakClientData(
        clid=clid,
        cid=str(raw.get("cid") or detail.get("cid") or ""),
        name=str(detail.get("client_nickname")
                 or raw.get("client_nickname") or clid),
        channel_name=channel_names.get(str(raw.get("cid") or "")),
        ping=_to_float(detail.get("connection_ping")),
        ping_deviation=_to_float(detail.get("connection_ping_deviation")),
        idle_time=idle_ms / 1000.0 if idle_ms is not None else None,
        away=str(detail.get("client_away", "0")) == "1",
        input_muted=str(detail.get("client_input_muted", "0")) == "1",
        output_muted=str(detail.get("client_output_muted", "0")) == "1",
        platform=str(detail.get("client_platform") or "") or None,
        version=str(detail.get("client_version") or "") or None,
        country=str(detail.get("client_country") or "") or None,
        servergroups=servergroups,
    )