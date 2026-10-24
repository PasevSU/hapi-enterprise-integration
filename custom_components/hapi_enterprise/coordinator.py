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
    # Версията на add-on-а идва от самия него — така HA показва коя версия реално
    # работи, а не коя е била инсталирана някога.
    "version": "version",
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
    out.update(_normalize_guidance(payload.get("guidance")))
    out.update(_normalize_security(payload.get("security")))
    out.update(_normalize_qr(payload.get("qr")))
    return out


def _normalize_qr(qr: object) -> dict:
    """Flatten the add-on's `qr` block (QR revisions and physical archives).

    Числата идват готови от add-on-а (`portal-qr.stats`) — интеграцията не брои
    повторно, за да не се разминат панелът и Home Assistant.
    """
    if not isinstance(qr, dict):
        return {
            "qr_active": None,
            "qr_blocked": None,
            "qr_archives": None,
            "locked_files": None,
            "tree_max_depth": None,
            "integrity_failed": None,
        }
    integrity = qr.get("integrity")
    return {
        "qr_active": qr.get("active"),
        "qr_blocked": qr.get("blocked"),
        "qr_archives": qr.get("archives"),
        "locked_files": qr.get("lockedFiles"),
        "tree_max_depth": qr.get("maxDepth"),
        "integrity_failed": (integrity.get("failures") if isinstance(integrity, dict) else None),
    }


def _normalize_security(security: object) -> dict:
    """Flatten the add-on's `security` block (Stage D) onto entity keys.

    Две неща се различават нарочно: натрупаните броячи (`denied.*`) растат вечно и по
    тях не може да се вдигне тревога, която някога да угасне; `window` гледа последните
    5 минути и точно той храни `binary_sensor.public_gateway_security_alert`.
    """
    if not isinstance(security, dict):
        return {
            "active_portal_sessions": None,
            "token_validation_failures": None,
            "revoked_token_attempts": None,
            "cross_portal_denials": None,
            "security_recent_denials": None,
            "security_window_cross_portal": None,
            "security_window_revoked": None,
            "security_require_token": None,
        }
    denied = security.get("denied")
    denied = denied if isinstance(denied, dict) else {}
    window = security.get("window")
    window = window if isinstance(window, dict) else {}
    return {
        "active_portal_sessions": security.get("activePortalSessions"),
        # „Проверката не мина“ = непознат + изтекъл токен + невалидна бисквитка.
        "token_validation_failures": security.get("validationFailures"),
        "revoked_token_attempts": denied.get("revokedRefused"),
        "cross_portal_denials": denied.get("crossPortal"),
        "security_recent_denials": window.get("total"),
        "security_window_cross_portal": window.get("crossPortal"),
        "security_window_revoked": window.get("revokedRefused"),
        "security_require_token": security.get("requireToken"),
    }


def _normalize_guidance(guidance: object) -> dict:
    """Flatten the add-on's `guidance` block (Stage E) onto entity keys.

    The add-on computes the decision once: which component is unhealthy, for how
    long, and what to check. The integration does NOT re-implement thresholds —
    it only reads them, so Home Assistant and the panel can never disagree.
    A missing block (older add-on) stays `unknown` instead of being treated as
    "healthy": we do not know, and saying "ok" would be a measurement we do not have.
    """
    if not isinstance(guidance, dict):
        return {
            "health": "unknown",
            "recommended_action": None,
            "recommended_component": None,
            "recommended_reason": None,
            "recommended_severity": None,
            "guidance_basis": None,
            "guidance_window_seconds": None,
            "mirror_problem": None,
            "http_error_rate": None,
            "latency_p95": None,
            "download_denial_rate": None,
        }
    checks = guidance.get("checks")
    checks = checks if isinstance(checks, dict) else {}
    recommended = guidance.get("recommended")
    recommended = recommended if isinstance(recommended, dict) else {}
    window = guidance.get("window")
    window = window if isinstance(window, dict) else None
    status = guidance.get("status")
    return {
        "health": status if isinstance(status, str) and status else "unknown",
        "recommended_action": recommended.get("action"),
        "recommended_component": recommended.get("component"),
        "recommended_reason": recommended.get("reason"),
        "recommended_severity": recommended.get("severity"),
        "guidance_basis": guidance.get("basis"),
        "guidance_window_seconds": window.get("seconds") if window else None,
        "mirror_problem": checks.get("mirror_problem"),
        "http_error_rate": checks.get("http_error_rate"),
        "latency_p95": checks.get("latency_p95"),
        "download_denial_rate": checks.get("download_denial_rate"),
    }
