# TeamSpeak Server für Home Assistant

Custom-Integration, die einen **TeamSpeak-3-Server** über die ServerQuery-Schnittstelle abfragt und die aktuell verbundenen Clients als Sensor in Home Assistant bereitstellt.

**Wichtig:** Diese Integration liest ausschließlich Daten. Es werden keine Befehle an den Server gesendet, die Clients oder Serverzustände verändern.

## Funktionen

- **Sensor „TeamSpeak Clients online"**: Anzahl der aktiven (Nicht-Query-)Clients
- **Attribute pro Client**: Name, Kanal, Ping, Ping-Streuung, Idle-Zeit (Sekunden), Away/Mute-Status, Plattform, Client-Version, Land, Servergruppen
- **Serverattribute**: Servername, Server-Version, maximale Client-Anzahl, Clients pro Kanal
- Einrichtung über die Home-Assistant-UI (Config Flow), automatischer Reauth-Dialog bei geänderten Zugangsdaten
- Keine externen Python-Abhängigkeiten (reine Standardbibliothek)

## Voraussetzungen

1. **TeamSpeak-3-Server** erreichbar unter Host/IP, ServerQuery-Port Standard `10011` (TCP).
2. **Eigener ServerQuery-Account** (nicht den `serveradmin` für Home Assistant verwenden):

   Auf dem Server (SSH/Query-Login als `serveradmin`):

   ```
   login serveradmin <DEIN_PASSWORT>
   serverqueryadd client_login_name=homeassistant
   ```

   Die Antwort enthält `client_login_password=...` – dies zusammen mit dem Namen `homeassistant` in der Integration eintragen. Der Account braucht mindestens die Rechte `b_virtualserver_info_view`, `b_virtualserver_client_list` und `b_virtualserver_channel_list`.

## Installation

### Variante A: manuell

1. Ordner `custom_components/teamspeak/` in dein Home-Assistant-Konfigurationsverzeichnis kopieren, sodass `<config>/custom_components/teamspeak/manifest.json` existiert.
2. Home Assistant neu starten.
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → „TeamSpeak Server"*.

### Variante B: HACS (benutzerdefiniertes Repository)

1. In HACS → ⋮ → *Benutzerdefiniertes Repository hinzufügen* mit dem Repository-URL dieser Erweiterung und Kategorie *Integration*.
2. „TeamSpeak Server" suchen und installieren, danach Home Assistant neu starten.

## Konfiguration

| Feld | Beschreibung | Standard |
| --- | --- | --- |
| Host | IP oder Domain des TS-Servers | – |
| ServerQuery-Port | TCP-Port der Query-Schnittstelle | 10011 |
| Benutzername / Passwort | ServerQuery-Zugangsdaten | – |
| Virtuelle Server-ID | `sid` des virtuellen Servers | 1 |
| Abfrageintervall | Sekunden zwischen zwei Abfragen (min. 2) | 30 |

Hinweis: Pro Abfrage wird eine neue Query-Sitzung aufgebaut (connect → login → Abfragen → quit), da der TS-Server inaktive Query-Verbindungen selbst trennt. Das Intervall nicht zu klein wählen, sonst droht der Flood-Schutz des Servers (siehe Fehlerbehebung).

## Welche Clients online sind

Der Sensor `sensor.teamspeak_clients_online` zeigt als Zustand die Anzahl und in seinen **Attributen** alle Details. In Home Assistant unter *Entwicklerwerkzeuge → Zustände* den Sensor auswählen, dann rechts die Attribute ansehen. Unter dem Attribut `clients` steht für jeden verbundenen (Nicht-Query-)Client ein Eintrag:

| Feld | Bedeutung |
| --- | --- |
| `name` | Nickname des Clients |
| `channel` | Kanalname, in dem der Client sich befindet |
| `clid` / `cid` | interne Client- bzw. Kanal-ID |
| `ping`, `ping_deviation` | Ping in ms bzw. Streuung (leer, wenn der Server keine Werte liefert) |
| `idle_time` | Idle-Dauer in Sekunden |
| `away` | „Away“-Status (`true`/`false`) |
| `input_muted` / `output_muted` | Mikrofon- bzw. Kopfhörer-Stummschaltung |
| `platform` | Betriebssystem des Clients (z. B. `Windows`) |
| `version` | Client-Version |
| `country` | Ländercode (z. B. `DE`) |
| `servergroups` | Liste der Servergruppen-IDs |

Zusätzlich liefert der Sensor die Attribute `server_name`, `server_version`, `server_maxclients`, `clients_online` und `channel_clients` (Anzahl Clients je Kanal).

## Beispiele

### Automatisierung: Benachrichtigung, wenn jemand den Server betritt

```yaml
automation:
  - alias: "TeamSpeak: Neue Clients benachrichtigen"
    trigger:
      - platform: numeric_state
        entity_id: sensor.teamspeak_clients_online
        above: 0
    action:
      - service: notify.mobile_app_dein_handy
        data:
          title: "TeamSpeak"
          message: >-
            {% for c in state_attr('sensor.teamspeak_clients_online', 'clients') | default([]) %}
              {{ c.name }} in {{ c.channel }} – Ping {{ c.ping }} ms
            {% endfor %}
```

### Dashboard-Karte (Markdown)

```yaml
type: markdown
title: 🎙 TeamSpeak
content: >-
  **{{ state_attr('sensor.teamspeak_clients_online', 'server_name') }}**
  – {{ states('sensor.teamspeak_clients_online') }} /
  {{ state_attr('sensor.teamspeak_clients_online', 'server_maxclients') }} online

  {% for c in state_attr('sensor.teamspeak_clients_online', 'clients') | default([]) %}
  - **{{ c.name }}** in {{ c.channel }}
    {% if c.ping is not none %} – {{ c.ping }} ms{% endif %}
    {% if c.away %} – afk{% endif %}
    {% if c.output_muted %} – 🔇{% endif %}
    {% if c.platform %} ({{ c.platform }} {% if c.version %}{{ c.version }}{% endif %}){% endif %}
  {% endfor %}

  {% if states('sensor.teamspeak_clients_online') | int(0) == 0 %}
  _Niemand online._
  {% endif %}
```

### Vorlage: Wer ist online? (z. B. für Benachrichtigungen)

```yaml
{% set clients = state_attr('sensor.teamspeak_clients_online', 'clients') | default([], true) %}
{% if clients | length > 0 %}
  Online: {{ clients | map(attribute='name') | list | join(', ') }}
{% else %}
  Niemand online.
{% endif %}
```

## Fehlerbehebung

- **„Ungültige ServerQuery-Zugangsdaten"**: Passwort prüfen; Query-Accounts sind **nicht** die Serveradmin-Zugangsdaten aus der `ts3server.ini`.
- **„Verbindung fehlgeschlagen"**: Port `10011/tcp` in der Firewall/Portweiterleitung des Servers offen? (`serverquery_port` in der `ts3server.ini`).
- **„Verbindung fehlgeschlagen" trotz erreichbarem Server**: Wurde ein **Domainname** eingetragen, der auf die öffentliche Router-IP zeigt (z. B. via DDNS)? Von *innen* aus dem Heimnetz schlägt das fehl, wenn der Router kein NAT-Loopback beherrscht oder der Port nicht weitergeleitet ist – auch wenn die TeamSpeak-Clients im Hausnetz funktionieren. Abhilfe: die **LAN-IP des Servers** eintragen (z. B. `192.168.x.x`) oder NAT-Loopback/Portweiterleitung für `10011/tcp` am Router aktivieren. Für die konkrete Ursache (DNS, Timeout, verweigert) mit aktiviertem Debug-Logging im Log nachsehen.
- **Verbindungen werden gedrosselt/gebannt („flood")**: Intervall erhöhen (≥ 15 s empfohlen) und die IP von Home Assistant optional in die Query-Whitelist des Servers aufnehmen.
- **Keine Clientdaten trotz Login**: Dem Query-Account die oben genannten Rechte zuweisen (Servergruppen des Accounts prüfen).
- **Ping-Attribute bleiben leer**: Nicht jeder Server liefert über ServerQuery ein `connection_ping` für Voice-Clients (abhängig von Server-Version/Konfiguration). Fehlt der Wert, bleiben die Attribute `ping`/`ping_deviation` leer – das ist kein Fehler. Query-Clients (z. B. die Abfrage selbst) besitzen nie Ping-Werte und werden ohnehin nicht gezählt.
- **Debug-Logging aktivieren**:

  ```yaml
  logger:
    logs:
      custom_components.teamspeak: debug
  ```

## Tests

Standalone-Tests inklusive Fake-ServerQuery-Server (ohne Home Assistant):

```bash
python tests/test_ts3_api.py
```

Optional: `tests/live_test.py` führt einen echten Abfragelauf gegen einen laufenden Server durch (Aufruf mit `<host> <query-user> <passwort>`). Das Skript enthält voreingestellte Zugangsdaten – es nur lokal verwenden und **nicht** in öffentliche Repositories übernehmen.