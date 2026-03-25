"""Config flow for Tuya Lock Monitor."""
from __future__ import annotations

import logging
import traceback
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode

from .const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_DEVICE_ID,
    CONF_ENDPOINT,
    CONF_LOCAL_IP,
    CONF_LOCAL_KEY,
    CONF_LOCAL_VERSION,
    CONF_MODE,
    DEFAULT_ENDPOINT,
    DEFAULT_LOCAL_VERSION,
    DOMAIN,
    ENDPOINTS,
    LOCAL_VERSIONS,
    MODE_CLOUD,
    MODE_LOCAL,
)
from .coordinator import TuyaLockCoordinator

_LOGGER = logging.getLogger(__name__)


async def _validate_cloud(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, str]:
    """Test cloud credentials and return any errors."""
    coordinator = TuyaLockCoordinator(
        hass,
        data[CONF_ACCESS_ID],
        data[CONF_ACCESS_SECRET],
        data[CONF_DEVICE_ID],
        data[CONF_ENDPOINT],
        local_ip=data.get(CONF_LOCAL_IP) or None,
        local_version=data.get(CONF_LOCAL_VERSION, DEFAULT_LOCAL_VERSION),
    )
    try:
        await coordinator._async_update_data()
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Tuya cloud validation failed: %s | %s", err, type(err).__name__)
        _LOGGER.debug("Traceback:\n%s", traceback.format_exc())
        msg = str(err).lower()
        if "network" in msg or "connection" in msg or "timeout" in msg:
            return {"base": "cannot_connect"}
        if any(x in msg for x in ("token", "2002", "2406", "invalid", "signature", "sign", "auth")):
            return {"base": "invalid_auth"}
        return {"base": "unknown"}
    return {}


async def _validate_local(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, str]:
    """Test local connection and return any errors."""
    coordinator = TuyaLockCoordinator(
        hass,
        access_id="",
        access_secret="",
        device_id=data[CONF_DEVICE_ID],
        endpoint="",
        local_ip=data[CONF_LOCAL_IP].strip(),
        local_version=data.get(CONF_LOCAL_VERSION, DEFAULT_LOCAL_VERSION),
        local_key_direct=data[CONF_LOCAL_KEY].strip(),
    )
    try:
        await coordinator._async_update_data()
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Tuya local validation failed: %s | %s", err, type(err).__name__)
        _LOGGER.debug("Traceback:\n%s", traceback.format_exc())
        msg = str(err).lower()
        if any(x in msg for x in ("timeout", "connection", "network", "refused", "host")):
            return {"base": "cannot_connect"}
        return {"base": "local_failed"}
    return {}


class TuyaLockMonitorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup UI."""

    VERSION = 1

    @staticmethod
    @config_entries.callback
    def async_get_options_flow(
        entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return TuyaLockMonitorOptionsFlow(entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: choose connection mode."""
        if user_input is not None:
            if user_input[CONF_MODE] == MODE_LOCAL:
                return await self.async_step_local()
            return await self.async_step_cloud()

        schema = vol.Schema(
            {
                vol.Required(CONF_MODE, default=MODE_CLOUD): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            {
                                "value": MODE_CLOUD,
                                "label": "Cloud (recommended — requires Tuya IoT Platform account)",
                            },
                            {
                                "value": MODE_LOCAL,
                                "label": "Local only — enter local key manually, no cloud account needed",
                            },
                        ],
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2a: cloud credentials (and optional local IP for hybrid mode)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input.get(CONF_LOCAL_IP):
                user_input[CONF_LOCAL_IP] = user_input[CONF_LOCAL_IP].strip()
            errors = await _validate_cloud(self.hass, user_input)
            if not errors:
                await self.async_set_unique_id(user_input[CONF_DEVICE_ID])
                self._abort_if_unique_id_configured()
                user_input[CONF_MODE] = MODE_CLOUD
                return self.async_create_entry(
                    title=f"Tuya Lock ({user_input[CONF_DEVICE_ID]})",
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_ACCESS_ID): str,
                vol.Required(CONF_ACCESS_SECRET): str,
                vol.Required(CONF_DEVICE_ID): str,
                vol.Required(CONF_ENDPOINT, default=DEFAULT_ENDPOINT): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            {"value": url, "label": f"{region} — {url}"}
                            for region, url in ENDPOINTS.items()
                        ],
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(CONF_LOCAL_IP): str,
                vol.Optional(
                    CONF_LOCAL_VERSION, default=DEFAULT_LOCAL_VERSION
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            {"value": v, "label": f"Protocol {v}"} for v in LOCAL_VERSIONS
                        ],
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="cloud", data_schema=schema, errors=errors)

    async def async_step_local(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2b: local-only — device ID, local key, IP, protocol version."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input[CONF_LOCAL_IP] = user_input[CONF_LOCAL_IP].strip()
            user_input[CONF_LOCAL_KEY] = user_input[CONF_LOCAL_KEY].strip()
            errors = await _validate_local(self.hass, user_input)
            if not errors:
                await self.async_set_unique_id(user_input[CONF_DEVICE_ID])
                self._abort_if_unique_id_configured()
                user_input[CONF_MODE] = MODE_LOCAL
                return self.async_create_entry(
                    title=f"Tuya Lock ({user_input[CONF_DEVICE_ID]})",
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): str,
                vol.Required(CONF_LOCAL_KEY): str,
                vol.Required(CONF_LOCAL_IP): str,
                vol.Optional(
                    CONF_LOCAL_VERSION, default=DEFAULT_LOCAL_VERSION
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            {"value": v, "label": f"Protocol {v}"} for v in LOCAL_VERSIONS
                        ],
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="local", data_schema=schema, errors=errors)


class TuyaLockMonitorOptionsFlow(config_entries.OptionsFlow):
    """Allow settings to be changed after setup without re-entering credentials."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        mode = self._entry.data.get(CONF_MODE, MODE_CLOUD)

        if user_input is not None:
            for key in (CONF_LOCAL_IP, CONF_LOCAL_KEY):
                if user_input.get(key):
                    user_input[key] = user_input[key].strip()
            return self.async_create_entry(title="", data=user_input)

        if mode == MODE_LOCAL:
            # Local-only: allow updating local key, IP, and version
            current_key = self._entry.options.get(
                CONF_LOCAL_KEY, self._entry.data.get(CONF_LOCAL_KEY, "")
            )
            current_ip = self._entry.options.get(
                CONF_LOCAL_IP, self._entry.data.get(CONF_LOCAL_IP, "")
            )
            current_version = self._entry.options.get(
                CONF_LOCAL_VERSION,
                self._entry.data.get(CONF_LOCAL_VERSION, DEFAULT_LOCAL_VERSION),
            )
            schema = vol.Schema(
                {
                    vol.Required(CONF_LOCAL_KEY, default=current_key): str,
                    vol.Required(CONF_LOCAL_IP, default=current_ip): str,
                    vol.Optional(
                        CONF_LOCAL_VERSION, default=current_version
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": v, "label": f"Protocol {v}"} for v in LOCAL_VERSIONS
                            ],
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            )
        else:
            # Cloud mode: allow updating optional local IP and version
            current_ip = self._entry.options.get(
                CONF_LOCAL_IP, self._entry.data.get(CONF_LOCAL_IP, "")
            )
            current_version = self._entry.options.get(
                CONF_LOCAL_VERSION,
                self._entry.data.get(CONF_LOCAL_VERSION, DEFAULT_LOCAL_VERSION),
            )
            schema = vol.Schema(
                {
                    vol.Optional(CONF_LOCAL_IP, default=current_ip): str,
                    vol.Optional(
                        CONF_LOCAL_VERSION, default=current_version
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": v, "label": f"Protocol {v}"} for v in LOCAL_VERSIONS
                            ],
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            )

        return self.async_show_form(step_id="init", data_schema=schema)
