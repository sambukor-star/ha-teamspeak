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
from .const import CLIENTLIST_FLAGS, DEFAULT_SCAN_INTERVAL

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

            # Clients inkl. Zusatzfelder (Idle, Away, Mute, Gruppen, Plattform,
            # Version, Land) in EINEM clientlist-Befehl abfragen. Früher wurde
            # pro Client ein einzelnes clientinfo gesendet; ab ~6 Clients
            # überschritt das das Kommandobudget des TS-Flood-Schutzes
            # (Standard ~10 Befehle pro Zeitfenster) -> der Server trennte die
            # Query-Verbindung und der Sensor fiel auf "Nicht verfügbar"/None.
            detail_available = True
            try:
                raw_clients = await client.clientlist(CLIENTLIST_FLAGS)
            except TS3Error as err:
                _LOGGER.debug(
                    "clientlist mit Flags nicht möglich (%s); Rückfall auf "
                    "clientlist + clientinfo pro Client",
                    err,
                )
                detail_available = False
                raw_clients = await client.clientlist()

            channel_names = {
                str(ch.get("cid")): str(ch.get("channel_name") or "")
                for ch in channels
            }

            clients: list[dict[str, Any]] = []
            for raw in raw_clients:
                if str(raw.get("client_type", "0")) == "1":
                    # ServerQuery-Clients (Typ 1) nicht mitzählen.
                    continue
                clid = str(raw.get("clid"))
                detail: dict[str, Any] = {}
                if not detail_available:
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


def _combined(detail: dict[str, Any], raw: dict[str, Any], key: str) -> Any:
    """Wert bevorzugt aus clientinfo, sonst aus der (erweiterten) clientlist."""
    value = detail.get(key)
    return raw.get(key) if value is None else value


def _parse_servergroups(value: Any) -> list[int]:
    """Wandelt ``"6,7,13"`` in eine Liste von Gruppen-IDs um."""
    groups: list[int] = []
    for part in str(value or "").split(","):
        part = part.strip()
        if part:
            try:
                groups.append(int(part))
            except ValueError:
                pass
    return groups


def _build_client_data(
    clid: str,
    raw: dict[str, Any],
    detail: dict[str, Any],
    channel_names: dict[str, str],
) -> TeamSpeakClientData:
    """Führt clientlist- und (sofern vorhanden) clientinfo-Daten zusammen.

    Läuft die Abfrage über ``clientlist`` mit Zusatz-Flags (siehe
    ``CLIENTLIST_FLAGS``), stecken alle Felder bereits in ``raw`` und
    ``detail`` bleibt leer. Sonst stammen die Werte aus dem clientinfo.
    """
    idle_ms = _to_float(_combined(detail, raw, "client_idle_time"))
    return TeamSpeakClientData(
        clid=clid,
        cid=str(raw.get("cid") or detail.get("cid") or ""),
        name=str(detail.get("client_nickname")
                 or raw.get("client_nickname") or clid),
        channel_name=channel_names.get(str(raw.get("cid") or "")),
        ping=_to_float(detail.get("connection_ping")),
        ping_deviation=_to_float(detail.get("connection_ping_deviation")),
        idle_time=idle_ms / 1000.0 if idle_ms is not None else None,
        away=str(_combined(detail, raw, "client_away") or "0") == "1",
        input_muted=str(_combined(detail, raw, "client_input_muted") or "0") == "1",
        output_muted=str(_combined(detail, raw, "client_output_muted") or "0") == "1",
        platform=str(_combined(detail, raw, "client_platform") or "") or None,
        version=str(_combined(detail, raw, "client_version") or "") or None,
        country=str(_combined(detail, raw, "client_country") or "") or None,
        servergroups=_parse_servergroups(
            _combined(detail, raw, "client_servergroups")
        ),
    )