"""Asynchroner TeamSpeak 3 ServerQuery-Client (nur Python-Standardbibliothek).

Implementiert den Teil des TeamSpeak-3-ServerQuery-Protokolls, der für die
Anzeige von Clients, Kanälen und Serverdaten nötig ist:

* Willkommenszeile des Servers lesen und Version extrahieren
* ``login`` (ServerQuery-Zugangsdaten)
* ``use sid=N`` (virtuellen Server auswählen)
* ``serverinfo`` / ``channellist`` / ``clientlist`` / ``clientinfo``
* ``quit`` (sauberes Trennen)

Das Protokoll arbeitet zeilenbasiert mit UTF-8 kodierten, selbst Escapenden
Key=Value-Paaren. Die Escape-Regeln sind in ``_unescape`` umgesetzt.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 10011

# Version aus der Willkommenszeile extrahieren (best effort).
_VERSION_RE = re.compile(r"\b(\d+\.\d+\.\d+(?:\.\d+)*(?:-[a-zA-Z0-9.]+)?)\b")

# Endekennung einer ServerQuery-Antwort.
_PROMPT = b"TS3"

# ServerQuery-Escape-Folgen => echtes Zeichen.
_ESCAPE_MAP = {
    r"\\": "\\",
    r"\/": "/",
    r"\s": " ",
    r"\p": "|",
    r"\a": "\a",
    r"\b": "\b",
    r"\f": "\f",
    r"\n": "\n",
    r"\r": "\r",
    r"\t": "\t",
    r"\v": "\v",
}


def _unescape(value: str) -> str:
    """Wandelt ServerQuery-Escape-Folgen in echte Zeichen um."""
    if "\\" not in value:
        return value
    result = ""
    i = 0
    while i < len(value):
        if value[i] != "\\" or i + 1 >= len(value):
            result += value[i]
            i += 1
            continue
        pair = value[i : i + 2]
        result += _ESCAPE_MAP.get(pair, pair)
        i += 2
    return result


def _escape(value: str) -> str:
    """Escaped einen Wert für die Übertragung als ServerQuery-Argument."""
    return (
        value.replace("\\", "\\\\")
        .replace(" ", "\\s")
        .replace("|", "\\p")
        .replace("/", "\\/")
    )


def parse_line(line: str) -> dict[str, Any]:
    """Parst eine ServerQuery-Zeile in ein dict aus Key-Value-Paaren."""
    entry: dict[str, Any] = {}
    for pair in line.split(" "):
        if not pair:
            continue
        key, _, raw = pair.partition("=")
        entry[key] = _unescape(raw)
    return entry


def parse_response(lines: list[str]) -> list[dict[str, Any]]:
    """Parst die Nutzdatenzeilen einer Antwort (Mehrfach-Einträge möglich)."""
    entries: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        # Mehrere Datensätze innerhalb einer Zeile sind mit | getrennt.
        for record in line.split("|"):
            if record.strip():
                entries.append(parse_line(record))
    return entries


@dataclass
class TeamSpeakClientData:
    """Aufbereitete Daten eines Clients (aus clientlist + clientinfo)."""

    clid: str
    cid: str
    name: str
    channel_name: str | None = None
    ping: float | None = None
    ping_deviation: float | None = None
    idle_time: float | None = None
    away: bool = False
    input_muted: bool = False
    output_muted: bool = False
    platform: str | None = None
    version: str | None = None
    country: str | None = None
    servergroups: list[int] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Stabil serialisierte Repräsentation (z. B. für HA-Attribute)."""
        return {
            "clid": self.clid,
            "cid": self.cid,
            "name": self.name,
            "channel": self.channel_name,
            "ping": self.ping,
            "ping_deviation": self.ping_deviation,
            "idle_time": self.idle_time,
            "away": self.away,
            "input_muted": self.input_muted,
            "output_muted": self.output_muted,
            "platform": self.platform,
            "version": self.version,
            "country": self.country,
            "servergroups": self.servergroups,
        }


class TS3Error(Exception):
    """Allgemeiner Fehler im ServerQuery-Client."""


class TS3AuthError(TS3Error):
    """Login fehlgeschlagen (id=512 «invalid login»)."""


class TS3ProtocolError(TS3Error):
    """Verbindungs- oder Protokollfehler."""


class TeamSpeakServerQuery:
    """Client für das TeamSpeak-3-ServerQuery-Protokoll."""

    def __init__(self, host: str, port: int = DEFAULT_PORT, timeout: float = 10.0) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._welcome_version: str | None = None

    # -- Verbindung -------------------------------------------------------

    async def connect(self) -> None:
        """Baut die TCP-Verbindung auf und liest die Willkommenszeile."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(host=self._host, port=self._port),
                timeout=self._timeout,
            )
        except (OSError, asyncio.TimeoutError) as err:
            raise TS3ProtocolError(
                f"Verbindung zu {self._host}:{self._port} fehlgeschlagen: {err}"
            ) from err

        welcome = await self._read_banner()
        header = " ".join(welcome)
        if "TeamSpeak 3 Server" not in header:
            raise TS3ProtocolError(f"Unerwartete Server-Antwort: {header!r}")
        match = _VERSION_RE.search(header)
        self._welcome_version = match.group(1) if match else None

    async def close(self) -> None:
        """Trennt die Verbindung (sendet ``quit``, wenn möglich)."""
        writer = self._writer
        if writer is None:
            return
        try:
            if not writer.is_closing():
                writer.write(b"quit\r\n")
                try:
                    await asyncio.wait_for(writer.drain(), timeout=1.0)
                except (OSError, asyncio.TimeoutError):
                    pass
        except OSError:
            pass
        try:
            writer.close()
            await asyncio.wait_for(writer.wait_closed(), timeout=2.0)
        except (OSError, asyncio.TimeoutError):
            pass
        self._writer = self._reader = None

    async def _read_banner(self) -> list[str]:
        """Liest die Begrüßungszeilen bis zur Leerzeile hinter dem Banner."""
        reader = self._reader
        if reader is None:
            raise TS3ProtocolError("Keine offene ServerQuery-Verbindung")
        banner: list[str] = []
        first = await asyncio.wait_for(reader.readline(), timeout=self._timeout)
        if not first:
            raise TS3ProtocolError("Server hat die Verbindung direkt geschlossen")
        text = first.decode("utf-8", "replace").rstrip("\r\n")
        _LOGGER.debug("TS3 recv (Banner): %s", text)
        if text and text != "TS3":
            banner.append(text)
        while True:
            try:
                raw = await asyncio.wait_for(reader.readline(), timeout=min(self._timeout, 3.0))
            except asyncio.TimeoutError:
                break  # Banner endet ohne Leerzeile -> weiter mit Befehlen
            if not raw:
                break
            line = raw.decode("utf-8", "replace").strip("\r\n")
            _LOGGER.debug("TS3 recv (Banner): %s", line)
            if not line:
                break
            banner.append(line)
            if raw.startswith(b"\r"):
                # Zeilenenden in der Form "\n\r": Es kommt keine Leerzeile als
                # Banner-Trenner; das Rest-\r bleibt als Fragment im Puffer und
                # wird bei der nächsten Antwort entfernt.
                break
        return banner

    async def _read_response(self) -> list[str]:
        """Liest Daten- und Statuszeilen bis zur Zeile ``error ...``."""
        reader = self._reader
        if reader is None:
            raise TS3ProtocolError("Keine offene ServerQuery-Verbindung")
        lines: list[str] = []
        while True:
            try:
                raw = await asyncio.wait_for(reader.readline(), timeout=self._timeout)
            except (OSError, asyncio.TimeoutError) as err:
                raise TS3ProtocolError(f"Antwort nicht vollständig gelesen: {err}") from err
            if not raw:
                raise TS3ProtocolError("Server hat die Verbindung geschlossen")
            line = raw.decode("utf-8", "replace").strip("\r\n")
            _LOGGER.debug("TS3 recv: %s", line)
            if not line:
                continue
            if line.startswith("error "):
                lines.append(line)
                break
            lines.append(line)
        return lines

    @property
    def welcome_version(self) -> str | None:
        """Serverversion aus der Willkommenszeile (``None`` wenn unbekannt)."""
        return self._welcome_version

    # -- Low-Level --------------------------------------------------------

    async def _send_command(
        self, command: str, args: dict[str, str] | None = None, raise_on_error: bool = True
    ) -> list[dict[str, Any]]:
        """Sendet einen Befehl und gibt die geparsten Nutzdaten zurück."""
        writer = self._writer
        reader = self._reader
        if writer is None or reader is None or writer.is_closing():
            raise TS3ProtocolError("Keine offene ServerQuery-Verbindung")

        payload = command
        if args:
            payload += " " + " ".join(
                f"{k}={_escape(v)}" for k, v in args.items()
            )
        _LOGGER.debug("TS3 send: %s", payload)

        try:
            writer.write(payload.encode("utf-8") + b"\r\n")
            await asyncio.wait_for(writer.drain(), timeout=self._timeout)
            lines = await self._read_response()
        except (OSError, asyncio.TimeoutError) as err:
            raise TS3ProtocolError(
                f"ServerQuery-Kommunikationsfehler bei {command!r}: {err}"
            ) from err

        # Letzte Zeile ist die Statuszeile (id, msg, extra_msg).
        status = parse_line(lines[-1]) if lines else {}
        try:
            error_id = int(status.get("id", "-1") or -1)
        except ValueError:
            error_id = -1
        if error_id != 0 and raise_on_error:
            msg = status.get("msg", "")
            if error_id == 512:
                raise TS3AuthError(msg or "Ungültige ServerQuery-Zugangsdaten")
            extra = status.get("extra_msg", "")
            detail = f"{msg} ({extra})" if extra else msg
            raise TS3Error(f"{command!r} fehlgeschlagen (id={error_id}): {detail}")
        return parse_response(lines[:-1])

    # -- High-Level -------------------------------------------------------

    async def login(self, username: str, password: str) -> None:
        """Authentifiziert die ServerQuery-Session."""
        await self._send_command(
            "login",
            {"client_login_name": username, "client_login_password": password},
        )

    async def use_server(self, sid: int) -> None:
        """Wählt den virtuellen Server aus, der abgefragt wird."""
        await self._send_command("use", {"sid": str(sid)})

    async def serverinfo(self) -> dict[str, Any]:
        """Liefert ``serverinfo`` des gewählten virtuellen Servers."""
        entries = await self._send_command("serverinfo")
        if not entries:
            raise TS3ProtocolError("serverinfo lieferte keine Daten")
        return entries[0]

    async def channellist(self) -> list[dict[str, Any]]:
        """Liefert ``channellist`` des gewählten virtuellen Servers."""
        return await self._send_command("channellist")

    async def clientlist(self, flags: str | None = None) -> list[dict[str, Any]]:
        """Liefert ``clientlist`` des gewählten virtuellen Servers.

        Mit ``flags`` (z. B. ``"-away -voice -times -groups -info -country"``)
        liefert der Server die Zusatzfelder direkt mit, sodass keine
        einzelnen ``clientinfo``-Abfragen pro Client nötig sind.
        """
        command = f"clientlist {flags}" if flags else "clientlist"
        return await self._send_command(command)

    async def clientinfo(self, clid: str) -> dict[str, Any]:
        """Liefert ``clientinfo`` für einen bestimmten Client."""
        entries = await self._send_command("clientinfo", {"clid": clid})
        if not entries:
            raise TS3ProtocolError(f"clientinfo für clid={clid} lieferte keine Daten")
        return entries[0]