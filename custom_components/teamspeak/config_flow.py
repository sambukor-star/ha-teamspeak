"""Config-Flow für die TeamSpeak-Integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .api import TS3AuthError, TS3Error, TeamSpeakServerQuery
from .const import (
    CONF_INTERVAL,
    CONF_SID,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SID,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.positive_int,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_SID, default=DEFAULT_SID): cv.positive_int,
        vol.Required(CONF_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            cv.positive_int, vol.Range(min=MIN_SCAN_INTERVAL)
        ),
    }
)

STEP_REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): str,
    }
)


class CannotConnect(HomeAssistantError):
    """Fehler: Server nicht erreichbar."""


class InvalidAuth(HomeAssistantError):
    """Fehler: Zugangsdaten ungültig."""


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Prüft Verbindung, Login und Virtual-Server-Auswahl."""
    client = TeamSpeakServerQuery(
        host=data[CONF_HOST],
        port=int(data.get(CONF_PORT) or DEFAULT_PORT),
    )
    try:
        await client.connect()
        await client.login(data[CONF_USERNAME], data[CONF_PASSWORD])
        await client.use_server(int(data.get(CONF_SID) or DEFAULT_SID))
        await client.serverinfo()
    except TS3AuthError as err:
        raise InvalidAuth(str(err)) from err
    except TS3Error as err:
        # Konkrete Ursache (DNS, Timeout, Verweigert, Protokoll) für die
        # Fehlersuche ins Log schreiben; die UI zeigt nur einen Sammeltext.
        _LOGGER.warning("TeamSpeak-Verbindungstest fehlgeschlagen: %s", err)
        raise CannotConnect(str(err)) from err
    finally:
        await client.close()


class TeamSpeakConfigFlow(config_entries.ConfigFlow, domain="teamspeak"):
    """Config-Flow für TeamSpeak-Server."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Von Hand im UI angelegter Entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if int(user_input.get(CONF_INTERVAL) or 0) < MIN_SCAN_INTERVAL:
                errors["base"] = "invalid_interval"
            else:
                unique_id = f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                try:
                    await validate_input(self.hass, user_input)
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except InvalidAuth:
                    errors["base"] = "invalid_auth"
                except Exception:  # noqa: BLE001
                    errors["base"] = "unknown"
                else:
                    return self.async_create_entry(
                        title=f"TeamSpeak {user_input[CONF_HOST]}",
                        data=user_input,
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Reauth wurde ausgelöst (z. B. id=512 beim Login)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Neues Passwort vom Nutzer abfragen."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            try:
                await validate_input(self.hass, data)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                self.hass.config_entries.async_update_entry(entry, data=data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"host": entry.data.get(CONF_HOST, "")},
        )