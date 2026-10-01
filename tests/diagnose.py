"""Netzwerk-Diagnose: Welche Ports/Adressen antworten?"""

from __future__ import annotations

import errno
import select
import socket

HOST = "cloud.schrade-home.de"
PORTS = (10011, 10022, 30033, 41144)
TIMEOUT = 8.0


def tcp_state(ip: str, port: int) -> str:
    """Vollständiger TCP-Connect mit sauberer Ergebnisunterscheidung."""
    af = socket.AF_INET6 if ":" in ip else socket.AF_INET
    s = socket.socket(af, socket.SOCK_STREAM)
    s.setblocking(False)
    try:
        s.connect((ip, port))
    except BlockingIOError:
        pass  # Verbindung läuft -> unten auf Abschluss warten
    except OSError as err:
        return f"sofort abgelehnt ({errno.errorcode.get(err.errno, err.errno)})"
    try:
        writable = select.select([], [s], [], TIMEOUT)[1]
        if not writable:
            return f"TIMEOUT (Pakete verworfen, Firewall?) nach {TIMEOUT}s"
        return "OFFEN" if s.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) == 0 else "Fehler"
    finally:
        s.close()


print("IPv4:", socket.gethostbyname_ex(HOST))
try:
    infos = socket.getaddrinfo(HOST, None, proto=socket.IPPROTO_TCP, family=socket.AF_INET6)
    print("IPv6:", sorted({i[4][0] for i in infos}))
except socket.gaierror:
    print("IPv6: keine AAAA-Adresse")

for ip in sorted({i[4][0] for i in socket.getaddrinfo(HOST, 10011, proto=socket.IPPROTO_TCP)}):
    for port in PORTS:
        print(f"{ip}:{port} -> {tcp_state(ip, port)}")