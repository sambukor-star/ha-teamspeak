"""Roh-Socket-Debug: Zeigt exakt, was der TS3-Server sendet und wann.

Verwendung:
    python tests/debug_raw.py <host> <query-user> <passwort>

Alternativ per Umgebungsvariablen: TS3_HOST, TS3_USER, TS3_PASSWORD.
"""

from __future__ import annotations

import os
import socket
import sys
import time

HOST = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TS3_HOST", "")
USER = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("TS3_USER", "serveradmin")
PASSWORD = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("TS3_PASSWORD", "")

if not HOST or not USER or not PASSWORD:
    raise SystemExit(
        "Verwendung: python tests/debug_raw.py <host> <query-user> <passwort>\n"
        "oder Umgebungsvariablen setzen: TS3_HOST, TS3_USER, TS3_PASSWORD"
    )


def recv_until_idle(sock: socket.socket, idle: float = 8.0) -> None:
    """Liest, bis für ``idle`` Sekunden nichts mehr kommt oder Server schließt."""
    start = time.time()
    sock.settimeout(idle)
    while True:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            print(f"[{time.time() - start:5.1f}s] <idle>")
            return
        if not chunk:
            print(f"[{time.time() - start:5.1f}s] <<< SERVER HAT VERBINDUNG GESCHLOSSEN >>>")
            return
        print(f"[{time.time() - start:5.1f}s] >>> {chunk!r}")


sock = socket.create_connection((HOST, 10011), timeout=6)
print(f"TCP verbunden mit {HOST}:10011")
recv_until_idle(sock)

print(f"-> sende login ({USER})")
sock.sendall(
    f"login client_login_name={USER} client_login_password={PASSWORD}\r\n".encode()
)
recv_until_idle(sock)

print("-> sende version")
sock.sendall(b"version\r\n")
recv_until_idle(sock)

print("-> sende use sid=1")
sock.sendall(b"use sid=1\r\n")
recv_until_idle(sock)

print("-> sende clientlist")
sock.sendall(b"clientlist\r\n")
data = b""
sock.settimeout(5)
try:
    while b"error id=" not in data:
        data += sock.recv(4096)
except socket.timeout:
    pass
print(repr(data))

records = [r for r in data.decode("utf-8", "replace").split("\n")[0].split("|") if r.strip()]
real_clid = None
for r in records:
    kv = dict(p.split("=", 1) for p in r.strip().strip("\r").split(" ") if "=" in p)
    if kv.get("client_type") == "0":
        real_clid = kv["clid"]
        print("\nRealer Client laut clientlist:", kv)

if real_clid:
    print(f"-> sende clientinfo clid={real_clid}")
    sock.sendall(f"clientinfo clid={real_clid}\r\n".encode())
    data = b""
    try:
        while b"error id=" not in data:
            data += sock.recv(4096)
    except socket.timeout:
        pass
    text = data.decode("utf-8", "replace").split("\n")[0]
    kv2 = dict(p.split("=", 1) for p in text.strip().strip("\r").split(" ") if "=" in p)
    print("Nickname:", kv2.get("client_nickname"), "| Plattform:", kv2.get("client_platform"))
    print("Alle connection_*-Keys:", sorted(k for k in kv2 if k.startswith("connection")))
    print("Ping-Keys:", {k: v for k, v in kv2.items() if "ping" in k})

sock.close()