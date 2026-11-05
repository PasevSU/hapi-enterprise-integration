"""Diagnostics for the hAPI Enterprise integration.

Home Assistant can show a config entry's diagnostics when a user files an issue
(*Settings → Devices & services → hAPI Enterprise → Download diagnostics*). For an
integration whose whole point is verifiable integrity, the diagnostic must be safe to
paste in public: it carries what is needed to explain a failure and **never** the admin
token or anything shaped like a secret.

The redaction is deliberate and testable (``tests/ha-diag-redaction.cjs``): a report that
leaks the token would turn „помогни ми“ into a credential leak, and a report that hides
everything would be useless.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_BACKEND_URL, CONF_SCAN_INTERVAL, CONF_TOKEN, DOMAIN

#: Keys whose value must never leave the machine, whatever the shape.
SECRET_KEYS = ("token", "password", "secret", "api_key", "apikey", "authorization")

#: Markers used instead of a secret value. Fixed strings, so a reader can tell that
#: redaction happened at all (an empty value would look like „not configured“).
REDACTED = "**REDACTED**"


def _is_secret_key(key: str) -> bool:
    """Return True when *key* names a credential."""
    lowered = str(key).lower()
    return any(marker in lowered for marker in SECRET_KEYS)


def redact(value: Any, *, key: str = "") -> Any:
    """Return *value* with every credential replaced by :data:`REDACTED`.

    Works recursively: dictionaries, lists and tuples are walked, so a future payload
    that nests a token cannot slip through simply because it moved one level deeper.
    """
    if key and _is_secret_key(key):
        return REDACTED
    if isinstance(value, dict):
        return {k: redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item, key=key) for item in value]
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    snapshot = getattr(coordinator, "data", None)

    return {
        "entry": {
            "title": entry.title,
            "domain": entry.domain,
            # The URL is useful („does it point at the right port?“) and is not a secret.
            "backend_url": entry.data.get(CONF_BACKEND_URL),
            "scan_interval": entry.options.get(
                CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL)
            ),
            # Reported as a fact, never as a value: „has a token“ is what support needs.
            "token_configured": bool(
                entry.options.get(CONF_TOKEN) or entry.data.get(CONF_TOKEN)
            ),
        },
        "coordinator": {
            "last_update_success": getattr(coordinator, "last_update_success", None),
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if getattr(coordinator, "update_interval", None)
                else None
            ),
        },
        # The telemetry itself, redacted: counters and versions are safe, credentials are not.
        "data": redact(snapshot or {}),
    }
