"""Konstanten für die TeamSpeak-Integration."""

DOMAIN = "teamspeak"

# Zusätzliche Konfigurationsfelder (über die Standard-Consts hinaus).
CONF_SID = "sid"
CONF_INTERVAL = "interval"

# Standardwerte.
DEFAULT_PORT = 10011
DEFAULT_SID = 1
DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 2

# clientlist-Flags: holt Idle-, Away-, Mute-, Gruppen-, Plattform-, Versions-
# und Land-Daten in einem einzigen Befehl. Ohne Flags wäre pro Client ein
# eigenes clientinfo nötig; ab ~10 Befehlen pro Zeitfenster greift aber der
# Flood-Schutz des TS-Servers und trennt die Verbindung (Sensor -> unavailable).
CLIENTLIST_FLAGS = "-away -voice -times -groups -info -country"