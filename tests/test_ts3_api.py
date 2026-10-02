"""Standalone-Tests für den TeamSpeak-ServerQuery-Client (ohne Home Assistant).

Läuft mit reinem Python, kein pytest nötig:

    python tests/test_ts3_api.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "teamspeak"))

from api import (  # noqa: E402
    TS3AuthError,
    TS3Error,
    TS3ProtocolError,
    TeamSpeakServerQuery,
    _unescape,
    parse_line,
    parse_response,
)

OK = "error id=0 msg=ok\r\n"


class FakeTS3Server:
    """Minimaler Fake eines TeamSpeak-3-ServerQuery-Servers."""

    def __init__(self) -> None:
        self.server = None
        self.port: int | None = None
        self.clientinfo_calls = 0
        self.flags_supported = True

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = int(self.server.sockets[0].getsockname()[1])

    async def stop(self) -> None:
        assert self.server is not None
        self.server.close()
        await self.server.wait_closed()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            writer.write(
                b"TS3\r\n"
                b"Welcome to the TeamSpeak 3 ServerQuery interface, "
                b'for command help type "help".\r\n'
                b"\r\n"
            )
            await writer.drain()
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                cmd = raw.decode("utf-8", "replace").strip()
                if cmd.startswith("clientinfo"):
                    self.clientinfo_calls += 1
                writer.write(self._answer(cmd).encode("utf-8"))
                await writer.drain()
                if cmd == "quit":
                    break
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()

    def _answer(self, cmd: str) -> str:
        """Beantwortet ein ServerQuery-Kommando des Clients."""
        if cmd.startswith("login "):
            if (
                "client_login_name=homeassistant" in cmd
                and "client_login_password=secret" in cmd
            ):
                return OK
            return "error id=512 msg=invalid login\r\n"
        if cmd.startswith("use "):
            if "sid=1" in cmd:
                return OK
            return "error id=768 msg=invalid sid\r\n"
        if cmd == "serverinfo":
            return (
                "virtualserver_name=Mein\\sServer virtualserver_version=3.13.7 "
                "virtualserver_maxclients=32\r\n"
                "error id=0 msg=ok\r\n"
            )
        if cmd == "channellist":
            return (
                "cid=1 pid=0 channel_name=Standard\\sKanal total_clients=1"
                "|cid=2 pid=1 channel_name=Lobby total_clients=0\r\n"
                "error id=0 msg=ok\r\n"
            )
        if cmd == "clientlist":
            return (
                "clid=7 cid=1 client_type=0 client_nickname=Max\\sMustermann"
                "|clid=8 cid=3 client_type=1 client_nickname=query\\suser\r\n"
                "error id=0 msg=ok\r\n"
            )
        if cmd.startswith("clientlist"):
            if not self.flags_supported:
                return "error id=256 msg=unknown command\r\n"
            return (
                "clid=21 cid=1 client_type=0 client_nickname=Alpha "
                "client_away=0 client_input_muted=0 client_output_muted=0 "
                "client_idle_time=1500 client_servergroups=6,13 "
                "client_platform=Windows client_version=3.6.2 client_country=DE"
                "|clid=22 cid=2 client_type=0 client_nickname=Be\\sTräger "
                "client_away=1 client_input_muted=1 client_output_muted=0 "
                "client_idle_time=90000 client_servergroups=7 "
                "client_platform=Linux client_version=3.6.1 client_country=AT"
                "|clid=23 cid=2 client_type=0 client_nickname=Charlie "
                "client_away=0 client_input_muted=0 client_output_muted=1 "
                "client_idle_time=200 client_servergroups= "
                "client_platform=macOS client_version=3.6.1 client_country=CH"
                "|clid=24 cid=1 client_type=1 client_nickname=serverquery\r\n"
                "error id=0 msg=ok\r\n"
            )
        if cmd.startswith("clientinfo"):
            if "clid=7" in cmd:
                return (
                    "clid=7 cid=1 client_away=0 client_input_muted=0 "
                    "client_output_muted=1 connection_ping=25.5 "
                    "client_idle_time=45000 client_platform=Windows "
                    "client_version=3.6.2 client_country=DE "
                    "client_servergroups=6,7,13 "
                    "client_nickname=Max\\sMustermann\r\n"
                    "error id=0 msg=ok\r\n"
                )
            return "error id=1538 msg=invalid clientID\r\n"
        if cmd == "quit":
            return OK
        return "error id=256 msg=unknown command\r\n"


async def main() -> None:
    """Führt alle Testfälle aus."""
    # Unit-Tests: Escape-Behandlung und Parser
    assert _unescape(r"Max\sMustermann\/XY\pA\\path") == "Max Mustermann/XY|A\\path"
    assert parse_line("key=hello\\sworld num=42") == {
        "key": "hello world",
        "num": "42",
    }
    parsed = parse_response(["cid=1 channel_name=Standard\\sKanal|cid=2 channel_name=Lobby"])
    assert parsed == [
        {"cid": "1", "channel_name": "Standard Kanal"},
        {"cid": "2", "channel_name": "Lobby"},
    ], parsed

    # Fake-Server: voller Zyklus
    fake = FakeTS3Server()
    await fake.start()
    try:
        client = TeamSpeakServerQuery("127.0.0.1", port=fake.port, timeout=5)
        await client.connect()
        await client.login("homeassistant", "secret")
        await client.use_server(1)
        serverinfo = await client.serverinfo()
        assert serverinfo["virtualserver_name"] == "Mein Server"
        assert serverinfo["virtualserver_version"] == "3.13.7"
        channels = await client.channellist()
        assert len(channels) == 2
        assert channels[0]["channel_name"] == "Standard Kanal"
        clientlist = await client.clientlist()
        assert len(clientlist) == 2
        assert clientlist[1]["client_type"] == "1"
        info = await client.clientinfo("7")
        assert info["connection_ping"] == "25.5"
        assert info["client_servergroups"] == "6,7,13"
        await client.close()
    finally:
        await fake.stop()

    # Fake-Server: erweitertes clientlist mit Flags (neuer Coordinator-Pfad)
    fake = FakeTS3Server()
    await fake.start()
    try:
        client = TeamSpeakServerQuery("127.0.0.1", port=fake.port, timeout=5)
        await client.connect()
        await client.login("homeassistant", "secret")
        await client.use_server(1)
        enriched = await client.clientlist(
            "-away -voice -times -groups -info -country"
        )
        assert len(enriched) == 4
        alpha, be, charlie, query_row = enriched
        assert alpha["client_nickname"] == "Alpha"
        assert alpha["client_servergroups"] == "6,13"
        assert be["client_nickname"] == "Be Träger"
        assert be["client_idle_time"] == "90000"
        assert be["client_away"] == "1"
        assert be["client_input_muted"] == "1"
        assert be["client_platform"] == "Linux"
        assert charlie["client_output_muted"] == "1"
        assert charlie["client_servergroups"] == ""
        assert query_row["client_type"] == "1"
        await client.close()
    finally:
        await fake.stop()

    # Fake-Server: Server kennt die clientlist-Flags nicht -> saubere
    # Fehlermeldung (id bleibt unbekannt), kein Verbindungsabbruch, damit der
    # Coordinator auf clientlist + clientinfo zurückfallen kann.
    fake = FakeTS3Server()
    fake.flags_supported = False
    await fake.start()
    try:
        client = TeamSpeakServerQuery("127.0.0.1", port=fake.port, timeout=5)
        await client.connect()
        await client.login("homeassistant", "secret")
        try:
            await client.clientlist("-away -voice -times -groups -info -country")
        except TS3Error as err:
            assert "256" in str(err), str(err)
        else:
            raise AssertionError("TS3Error für unbekannte clientlist-Flags erwartet")
        plain = await client.clientlist()
        assert len(plain) == 2
        await client.close()
    finally:
        await fake.stop()

    # Coordinator-Zusammenführung (nur wenn homeassistant installiert ist)
    try:
        import homeassistant  # noqa: F401
    except ImportError:
        print("homeassistant nicht installiert -> Coordinator-Tests übersprungen.")
    else:
        sys.path.insert(0, str(ROOT))
        from custom_components.teamspeak.coordinator import _build_client_data

        raw = {
            "clid": "22",
            "cid": "2",
            "client_nickname": "Be Träger",
            "client_type": "0",
            "client_away": "1",
            "client_input_muted": "1",
            "client_output_muted": "0",
            "client_idle_time": "90000",
            "client_servergroups": "7",
            "client_platform": "Linux",
            "client_version": "3.6.1",
            "client_country": "AT",
        }
        data = _build_client_data("22", raw, {}, {"2": "Lobby"})
        assert data.name == "Be Träger"
        assert data.channel_name == "Lobby"
        assert data.away is True
        assert data.idle_time == 90.0
        assert data.input_muted is True
        assert data.output_muted is False
        assert data.platform == "Linux"
        assert data.version == "3.6.1"
        assert data.country == "AT"
        assert data.servergroups == [7]

        # Rückfallpfad: Werte kommen bevorzugt aus clientinfo
        detail = {
            "client_nickname": "Aus Detail",
            "connection_ping": "25.5",
            "connection_ping_deviation": "3.5",
            "client_idle_time": "4200",
            "client_servergroups": "6,7,13",
        }
        raw_plain = {"clid": "7", "cid": "1", "client_type": "0"}
        data2 = _build_client_data("7", raw_plain, detail, {"1": "Standard Kanal"})
        assert data2.name == "Aus Detail"
        assert data2.ping == 25.5
        assert data2.ping_deviation == 3.5
        assert data2.idle_time == 4.2
        assert data2.servergroups == [6, 7, 13]
        assert data2.channel_name == "Standard Kanal"

    # Fake-Server: fehlerhafte Zugangsdaten
    fake = FakeTS3Server()
    await fake.start()
    try:
        client = TeamSpeakServerQuery("127.0.0.1", port=fake.port, timeout=5)
        await client.connect()
        try:
            await client.login("homeassistant", "wrong")
        except TS3AuthError:
            pass
        else:
            raise AssertionError("TS3AuthError wurde nicht ausgelöst")
        await client.close()
    finally:
        await fake.stop()

    # Fake-Server: use mit ungültiger sid
    fake = FakeTS3Server()
    await fake.start()
    try:
        client = TeamSpeakServerQuery("127.0.0.1", port=fake.port, timeout=5)
        await client.connect()
        await client.login("homeassistant", "secret")
        try:
            await client.use_server(5)
        except TS3Error as err:
            assert "768" in str(err), str(err)
        else:
            raise AssertionError("TS3Error für ungültige sid wurde nicht ausgelöst")
        await client.close()
    finally:
        await fake.stop()

    # Verbindung zu einem toten Port
    try:
        client = TeamSpeakServerQuery("127.0.0.1", port=1, timeout=2)
        try:
            await client.connect()
        except TS3ProtocolError:
            pass
        else:
            raise AssertionError("Protokollfehler bei totem Port erwartet")
        await client.close()
    finally:
        pass

    print("Alle TeamSpeak-ServerQuery-Tests erfolgreich.")


if __name__ == "__main__":
    asyncio.run(main())