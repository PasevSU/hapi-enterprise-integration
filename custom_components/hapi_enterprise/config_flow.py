"""Config flow for the hAPI Enterprise integration."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import voluptuous as vol
from aiohttp import ClientError
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_BACKEND_URL,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MAX_TOKEN_LENGTH,
    MIN_SCAN_INTERVAL,
    MIN_TOKEN_LENGTH,
    NAME,
)

_URL_RE = re.compile(r"^https?://[a-zA-Z0-9_.-]+(?::[0-9]{1,5})?(?:/[^\s]*)?$")

_URL_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
)
_TOKEN_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)
_INTERVAL_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=MIN_SCAN_INTERVAL,
        max=MAX_SCAN_INTERVAL,
        step=10,
        mode=selector.NumberSelectorMode.BOX,
        unit_of_measurement="seconds",
    )
)


def _validate(values: dict[str, Any], *, token_required: bool) -> dict[str, str]:
    """Validate user input and return a field -> error-key mapping."""
    errors: dict[str, str] = {}

    url = (values.get(CONF_BACKEND_URL) or "").strip()
    if not _URL_RE.fullmatch(url):
        errors[CONF_BACKEND_URL] = "invalid_url"

    token = (values.get(CONF_TOKEN) or "").strip()
    if token:
        if len(token) < MIN_TOKEN_LENGTH:
            errors[CONF_TOKEN] = "token_too_short"
        elif len(token) > MAX_TOKEN_LENGTH:
            errors[CONF_TOKEN] = "token_too_long"
    elif token_required:
        errors[CONF_TOKEN] = "token_required"

    scan = values.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    if not isinstance(scan, (int, float)) or scan < MIN_SCAN_INTERVAL or scan > MAX_SCAN_INTERVAL:
        errors[CONF_SCAN_INTERVAL] = "invalid_scan_interval"

    return errors


async def _async_test_connection(hass: HomeAssistant, backend_url: str, token: str) -> str | None:
    """Verify the add-on admin API before creating or updating an entry.

    Returns an error key for the form, or None when the endpoint answered.
    """
    session = async_get_clientsession(hass)
    try:
        async with asyncio.timeout(10):
            async with session.get(
                backend_url.rstrip("/") + "/admin/api/whoami",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            ) as resp:
                if resp.status in (401, 403):
                    return "invalid_auth"
                if resp.status >= 400:
                    return "cannot_connect"
    except (ClientError, TimeoutError, OSError):
        return "cannot_connect"
    return None


def _data_schema(defaults: dict[str, Any], *, token_required: bool) -> vol.Schema:
    """Build the form schema, prefilled from existing values."""
    token_key = (
        vol.Required(CONF_TOKEN, default=defaults.get(CONF_TOKEN, ""))
        if token_required
        else vol.Optional(CONF_TOKEN, default="")
    )
    return vol.Schema(
        {
            vol.Required(
                CONF_BACKEND_URL, default=defaults.get(CONF_BACKEND_URL, "")
            ): _URL_SELECTOR,
            token_key: _TOKEN_SELECTOR,
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=int(defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
            ): _INTERVAL_SELECTOR,
        }
    )


class PortalEnterpriseConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial user configuration flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input, token_required=True)
            if not errors:
                backend_url = user_input[CONF_BACKEND_URL].strip().rstrip("/")
                token = user_input[CONF_TOKEN].strip()
                # test-before-configure: never create an entry the add-on rejects.
                connection_error = await _async_test_connection(self.hass, backend_url, token)
                if connection_error:
                    errors["base"] = connection_error
                else:
                    user_input[CONF_BACKEND_URL] = backend_url
                    user_input[CONF_TOKEN] = token
                    await self.async_set_unique_id(backend_url)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(title=NAME, data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=_data_schema(user_input or {}, token_required=True),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(entry) -> OptionsFlow:
        """Return the options flow."""
        return PortalEnterpriseOptionsFlow(entry)


class PortalEnterpriseOptionsFlow(OptionsFlow):
    """Handle editing the connection settings."""

    def __init__(self, entry) -> None:
        """Initialize with the existing config entry."""
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the options step."""
        errors: dict[str, str] = {}
        current = {**self._entry.data, **self._entry.options}

        if user_input is not None:
            errors = _validate(user_input, token_required=False)
            if not errors:
                backend_url = user_input[CONF_BACKEND_URL].strip().rstrip("/")
                token = (user_input.get(CONF_TOKEN) or "").strip()
                # An empty token keeps the stored one; verify what will actually be used.
                effective_token = token or str(current.get(CONF_TOKEN, ""))
                connection_error = await _async_test_connection(self.hass, backend_url, effective_token)
                if connection_error:
                    errors["base"] = connection_error
                else:
                    cleaned: dict[str, Any] = {
                        CONF_BACKEND_URL: backend_url,
                        CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    }
                    if token:
                        cleaned[CONF_TOKEN] = token
                    return self.async_create_entry(title="", data=cleaned)

        return self.async_show_form(
            step_id="init",
            data_schema=_data_schema(current, token_required=False),
            errors=errors,
        )
