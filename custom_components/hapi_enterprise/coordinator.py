"""DataUpdateCoordinator for hAPI Enterprise telemetry."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, SENSORS_PATH

_LOGGER = logging.getLogger(__name__)

# The add-on speaks camelCase in `/admin/api/sensors`; the sensors use snake_case.
_TELEMETRY_KEYS = {
    "files": "files",
    "file_bytes": "fileBytes",
    "database_bytes": "databaseBytes",
    "telemetry_bytes": "telemetryBytes",
    "visits": "visits",
    "downloads": "downloads",
    # Сензори за комуникацията (виж visitor-intel.js): кой влиза, какво тегли, откъде.
    "unique_visitors": "uniqueVisitors",
    "visitors_new_24h": "visitorsNew24h",
    "download_visitors": "downloadVisitors",
    "denied_total": "deniedTotal",
    "admin_logins": "adminLogins",
    "countries_known": "countriesKnown",
}


class PortalEnterpriseCoordinator(DataUpdateCoordinator):
    """Poll the add-on admin API for portal telemetry."""

    def __init__(
        self,
        hass: HomeAssistant,
        backend_url: str,
        token: str,
        scan_interval: int,
    ) -> None:
        """Initialize the coordinator."""
        self.backend_url = backend_url.rstrip("/")
        self.token = token
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    @property
    def sensors_url(self) -> str:
        """Full URL of the sensors endpoint."""
        return f"{self.backend_url}{SENSORS_PATH}"

    async def _async_update_data(self) -> dict:
        """Fetch the add-on telemetry and normalize it for the sensors."""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        try:
            async with asyncio.timeout(30):
                session = async_get_clientsession(self.hass)
                async with session.get(self.sensors_url, headers=headers) as resp:
                    if resp.status in (401, 403):
                        raise UpdateFailed(
                            "hAPI Enterprise rejected the token (HTTP "
                            f"{resp.status}); check the admin token in Options"
                        )
                    if resp.status == 404:
                        raise UpdateFailed(
                            "hAPI Enterprise sensors endpoint not found; check "
                            "the backend URL points to the admin port (8098)"
                        )
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
        except asyncio.TimeoutError as err:
            raise UpdateFailed("Timeout contacting hAPI Enterprise") from err
        except UpdateFailed:
            raise
        except Exception as err:  # noqa: BLE001 - surface any transport error
            raise UpdateFailed(f"Error contacting hAPI Enterprise: {err}") from err

        if not isinstance(data, dict):
            raise UpdateFailed("hAPI Enterprise returned an unexpected payload")
        return _normalize(data)


def _normalize(payload: dict) -> dict:
    """Map the add-on payload onto the keys used by the sensors."""
    out: dict = {}
    for sensor_key, payload_key in _TELEMETRY_KEYS.items():
        out[sensor_key] = payload.get(payload_key)
    portals = payload.get("portals")
    out["portal_count"] = len(portals) if isinstance(portals, list) else None
    out["generated_at"] = payload.get("generatedAt")
    return out
