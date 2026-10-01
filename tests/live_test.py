"""Live-Test der TeamSpeak-Integration gegen einen echten Server.

Verwendung:
    python tests/live_test.py <host> <query-user> <passwort> [sid]

Alternativ per Umgebungsvariablen: TS3_HOST, TS3_USER, TS3_PASSWORD, TS3_SID.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "teamspeak"))

from api import (  # noqa: E402
    TS3AuthError,
    TS3Error,
    TS3ProtocolError,
    TeamSpeakServerQuery,
)

HOST = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TS3_HOST", "")
USER = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("TS3_USER", "")
PASSWORD = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("TS3_PASSWORD", "")
SID = int(sys.argv[4]) if len(sys.argv) > 4 else int(os.environ.get("TS3_SID", "1"))

if not HOST or not USER or not PASSWORD:
    raise SystemExit(
        "Verwendung: python tests/live_test.py <host> <query-user> <passwort> [sid]\n"
        "oder Umgebungsvariablen setzen: TS3_HOST, TS3_USER, TS3_PASSWORD [, TS3_SID]"
    )


async def probe(client: TeamSpeakServerQuery) -> None:
    """Fragt Server, Kanäle und Clients ab und gibt sie formatiert aus."""
    server = await client.serverinfo()
    print("== Server ==")
    print("  Name          :", server.get("virtualserver_name"))
    print("  Version       :", server.get("virtualserver_version") or client.welcome_version)
    print("  Plattform     :", server.get("virtualserver_platform"))
    print("  Uptime        :", server.get("virtualserver_uptime"), "Sekunden")
    print(
        "  Clients online:",
        server.get("virtualserver_clientsonline"),
        "/ max",
        server.get("virtualserver_maxclients"),
        "(davon Query:",
        server.get("virtualserver_queryclientsonline"),
        ")",
    )

    channels = await client.channellist()
    print(f"== Kanäle ({len(channels)}) ==")
    for ch in channels[:8]:
        print(
            f"  [{ch.get('cid')}] {ch.get('channel_name')}"
            f" (Clients: {ch.get('total_clients')}, max: {ch.get('channel_maxclients')})"
        )
    if len(channels) > 8:
        print(f"  ... und {len(channels) - 8} weitere")

    clients = await client.clientlist()
    real = [c for c in clients if c.get("client_type") == "0"]
    query = [c for c in clients if c.get("client_type") != "0"]
    chan_by_id = {ch.get("cid"): ch.get("channel_name") for ch in channels}
    print(f"== Clients ({len(real)} sichtbar, {len(query)} ServerQuery) ==")
    for cl in real:
        name = cl.get("client_nickname")
        chan = chan_by_id.get(cl.get("cid"), cl.get("cid"))
        try:
            info = await client.clientinfo(cl["clid"])
        except TS3Error as err:
            print(f"  {name!r} in {chan}: clientinfo fehlgeschlagen: {err}")
            continue
        print(f"  {name} in Kanal {chan}")
        print(
            f"      Ping: {info.get('connection_ping')} ms"
            f" (±{info.get('connection_ping_deviation')})"
        )
        print(
            f"      Idle: {info.get('client_idle_time')} ms |"
            f" Away: {info.get('client_away')} |"
            f" Mute in={info.get('client_input_muted')} out={info.get('client_output_muted')}"
        )
        print(
            f"      {info.get('client_platform')} | {info.get('client_version')} |"
            f" {info.get('client_country')} | Gruppen: {info.get('client_servergroups')}"
        )


async def main() -> None:
    """Führt den kompletten Abfragezyklus wie die Integration aus."""
    client = TeamSpeakServerQuery(HOST, timeout=10)
    print(f"Verbinde mit {HOST} ...")
    try:
        await client.connect()
        print(f"  Verbunden. ServerQuery-Banner-Version: {client.welcome_version}")
        await client.login(USER, PASSWORD)
        print("  Login OK.")
        await client.use_server(SID)
        print(f"  Virtueller Server {SID} ausgewählt.")
        await probe(client)
    except TS3AuthError as err:
        print(f"LOGIN FEHLGESCHLAGEN: {err}")
    except TS3ProtocolError as err:
        print(f"PROTOKOLL-/VERBINDUNGSFEHLER: {err}")
    except TS3Error as err:
        print(f"TS3-FEHLER: {err}")
    finally:
        await client.close()
        print("Verbindung geschlossen.")


if __name__ == "__main__":
    asyncio.run(main())