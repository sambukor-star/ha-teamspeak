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