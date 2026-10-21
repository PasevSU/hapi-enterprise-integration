"""hAPI Enterprise Home Assistant integration.

Two opt-in features:

1. A fail-closed HTTP bridge for token-protected portal APIs (YAML configured):

    hapi_enterprise:
      backend_url: http://<addon-hostname>:8099

   Only portal-scoped read and download requests are forwarded. Admin APIs are never
   proxied by this bridge. The bridge also serves the public portal page and its assets
   on Home Assistant's own address (`/api/hapi_enterprise/portal/<id>`,
   `/api/hapi_enterprise/public/v1/...`) - see `PublicGateway` below. Everything runs on
   the Home Assistant port (8123 by default); the integration never opens a port of its
   own. The pre-0.55 `/api/public/v1/...` alias stays available and answers with
   `Deprecation` + `Link: rel="successor-version"` headers.

2. Telemetry sensors configured through the UI (config/options flow), polling the
   add-on admin API with a user-supplied admin token.
"""
from __future__ import annotations
import logging
import re
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote
from aiohttp import ClientError, web
import voluptuous as vol
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_BACKEND_URL,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import PortalEnterpriseCoordinator

_LOGGER = logging.getLogger(__name__)

# YAML mode is optional (`hapi_enterprise: backend_url: ...`); the UI config flow works
# without it. The integration defines `async_setup`, so Home Assistant (hassfest) requires
# a CONFIG_SCHEMA — without one the YAML key would be reported as invalid.
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {vol.Optional(CONF_BACKEND_URL): cv.string},
            extra=vol.ALLOW_EXTRA,
        )
    },
    extra=vol.ALLOW_EXTRA,
)

_ALLOWED = re.compile(
    r"^p/([a-z0-9][a-z0-9-]{0,62})"
    r"(?:/(?:files(?:/[a-f0-9]{24}(?:/download)?)?|manifest|openapi\.json|qr\.svg|storage))?$"
)

# Public API Gateway (PG-6), exposed on Home Assistant's own IP and port.
# Only the read-only public surface is reachable; admin APIs are never proxied.
_PUBLIC_TAIL = re.compile(
    r"^portals/(?P<slug>[a-z0-9][a-z0-9-]{0,62})(?:/files)?$"
    r"|^files/(?P<file>[a-f0-9]{1,64})(?:/(?:access|download))?$"
)


async def _forward(hass, request, url, headers, params, extra_headers=None):
    """Stream an upstream response without buffering (Range/resume friendly)."""
    session = async_get_clientsession(hass)
    async with session.get(url, headers=headers, params=params, timeout=120, allow_redirects=False) as upstream:
        response_headers = {
            "Content-Type": upstream.headers.get("Content-Type", "application/octet-stream"),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        }
        if extra_headers:
            response_headers.update(extra_headers)
        response = web.StreamResponse(status=upstream.status, headers=response_headers)
        for field in ("Content-Length", "Content-Range", "Accept-Ranges", "ETag", "Last-Modified"):
            if upstream.headers.get(field):
                response.headers[field] = upstream.headers[field]
        if upstream.headers.get("Content-Disposition"):
            response.headers["Content-Disposition"] = upstream.headers["Content-Disposition"]
        await response.prepare(request)
        async for chunk in upstream.content.iter_chunked(65536):
            await response.write(chunk)
        await response.write_eof()
        return response


def _read_static_files() -> dict[str, str]:
    """Read the portal assets once, off the event loop (blocking I/O rule)."""
    base = Path(__file__).parent
    return {name: (base / name).read_text(encoding="utf-8") for name in ("portal.html", "portal.js", "portal.css")}


async def async_setup(hass, config):
    """Register the bridge views; UI (config flow) setup works without YAML."""
    settings = config.get(DOMAIN, {})
    backend = settings.get("backend_url", "")
    hass.data.setdefault(DOMAIN, {})
    # Files are read once in an executor, never inside a request handler.
    static = await hass.async_add_executor_job(_read_static_files)

    class PortalPage(HomeAssistantView):
        url = "/api/hapi_enterprise/portal/{slug}"
        name = "api:hapi_enterprise:page"
        requires_auth = False

        async def get(self, request, slug):
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", slug):
                raise web.HTTPNotFound()
            # This page contains no credentials. The browser sends the fragment token
            # in X-Portal-Key; backend validates it on every catalog/download request.
            content = static["portal.html"]
            return web.Response(text=content, content_type="text/html", headers={
                "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
            })

    class PortalAsset(HomeAssistantView):
        url = "/api/hapi_enterprise/assets/{asset}"
        name = "api:hapi_enterprise:asset"
        requires_auth = False

        async def get(self, request, asset):
            if asset not in ("portal.js", "portal.css"):
                raise web.HTTPNotFound()
            content = static[asset]
            return web.Response(text=content, content_type="application/javascript" if asset.endswith(".js") else "text/css", headers={
                "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            })

    # The portal page and its assets are static files - they need no backend.
    hass.http.register_view(PortalPage())
    hass.http.register_view(PortalAsset())

    # Fail closed: never proxy to an arbitrary host from a user request. Returning True
    # keeps the UI-driven (config flow) setup working when no YAML bridge is configured.
    if not isinstance(backend, str) or not re.fullmatch(r"https?://[a-zA-Z0-9_.-]+:[0-9]{2,5}", backend):
        _LOGGER.debug("hAPI Enterprise: no YAML backend_url; configure the integration from the UI")
        return True
    backend = backend.rstrip("/")

    class PortalAPI(HomeAssistantView):
        url = "/api/hapi_enterprise/v1/{tail:.*}"
        name = "api:hapi_enterprise:public"
        requires_auth = False  # Explicit portal API key authorization is enforced by the Node backend.

        async def get(self, request, tail):
            if not _ALLOWED.fullmatch(tail):
                raise web.HTTPNotFound()
            # No HA Authorization header is forwarded. Portal key is sent as a separate header.
            portal_key = request.headers.get("X-Portal-Key", "")
            file_key = request.headers.get("X-File-Key", "")
            if not portal_key or len(portal_key) > 512 or len(file_key) > 512:
                raise web.HTTPUnauthorized()
            headers = {"Authorization": "Bearer " + portal_key}
            if file_key:
                headers["X-File-Key"] = file_key
            # Preserve resumable downloads end-to-end. The Node backend validates ranges.
            if request.headers.get("Range"):
                headers["Range"] = request.headers["Range"]
            if request.headers.get("If-Range"):
                headers["If-Range"] = request.headers["If-Range"]
            url = backend + "/api/v1/" + tail
            # Query params are forwarded only for pagination/filtering; portal_token is deliberately not accepted.
            allowed = {"q", "limit", "offset", "order", "direction", "category", "group", "topic", "tag", "path"}
            params = [(k, v) for k, v in request.query.items() if k in allowed]
            session = async_get_clientsession(hass)
            try:
                async with session.get(url, headers=headers, params=params, timeout=120, allow_redirects=False) as upstream:
                    content_type = upstream.headers.get("Content-Type", "application/octet-stream")
                    response = web.StreamResponse(status=upstream.status, headers={
                        "Content-Type": content_type,
                        "Cache-Control": "no-store",
                        "X-Content-Type-Options": "nosniff",
                        "Referrer-Policy": "no-referrer",
                    })
                    for field in ("Content-Length", "Content-Range", "Accept-Ranges", "ETag", "Last-Modified"):
                        if upstream.headers.get(field):
                            response.headers[field] = upstream.headers[field]
                    if upstream.headers.get("Content-Disposition"):
                        response.headers["Content-Disposition"] = upstream.headers["Content-Disposition"]
                    await response.prepare(request)
                    async for chunk in upstream.content.iter_chunked(65536):
                        await response.write(chunk)
                    await response.write_eof()
                    return response
            except (ClientError, TimeoutError):
                raise web.HTTPBadGateway()

    class PublicGateway(HomeAssistantView):
        """Public API Gateway served by Home Assistant itself.

        Canonical: https://<ha-host>:8123/api/hapi_enterprise/public/v1/portals/<slug>

        No HA session is required; the Node backend decides every request
        (FREE / KEY_REQUIRED / DISABLED, quotas, expiry). Admin paths are not here.
        The channel lives on the Home Assistant port - no separate port is exposed.
        """

        url = "/api/hapi_enterprise/public/v1/{tail:.*}"
        name = "api:hapi_enterprise:gateway"
        requires_auth = False
        deprecated = False

        async def get(self, request, tail):
            if not _PUBLIC_TAIL.fullmatch(tail):
                raise web.HTTPNotFound()
            headers = {}
            portal_key = request.headers.get("X-Portal-Key", "")
            if portal_key:
                if len(portal_key) > 512:
                    raise web.HTTPUnauthorized()
                headers["X-Portal-Key"] = portal_key
            # Range is preserved so resumable downloads work end-to-end.
            for field in ("Range", "If-Range"):
                if request.headers.get(field):
                    headers[field] = request.headers[field]
            # Query parameters: only the optional portal key is forwarded.
            params = [(k, v) for k, v in request.query.items() if k == "key" and len(v) <= 512]
            extra = None
            if self.deprecated:
                extra = {
                    "Deprecation": "true",
                    "Link": '</api/hapi_enterprise/public/v1/' + tail + '>; rel="successor-version"',
                }
            try:
                return await _forward(hass, request, backend + "/api/public/v1/" + tail, headers, params, extra)
            except (ClientError, TimeoutError):
                raise web.HTTPBadGateway

    class LegacyPublicGateway(PublicGateway):
        """Pre-0.55 alias, kept so QR codes and links created earlier keep working."""

        url = "/api/public/v1/{tail:.*}"
        name = "api:hapi_enterprise:legacy_gateway"
        deprecated = True

    hass.http.register_view(PortalAPI())
    hass.http.register_view(PublicGateway())
    hass.http.register_view(LegacyPublicGateway())
    return True


def _entry_settings(entry: ConfigEntry) -> tuple[str, str, int]:
    """Resolve the effective settings; options override the initial data."""
    settings = {**entry.data, **entry.options}
    backend_url = str(settings.get(CONF_BACKEND_URL, "")).strip().rstrip("/")
    token = str(settings.get(CONF_TOKEN, "")).strip()
    try:
        scan_interval = int(settings.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    except (TypeError, ValueError):
        scan_interval = DEFAULT_SCAN_INTERVAL
    return backend_url, token, scan_interval


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the telemetry sensors from a config entry."""
    backend_url, token, scan_interval = _entry_settings(entry)
    coordinator = PortalEnterpriseCoordinator(hass, backend_url, token, scan_interval)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await coordinator.async_config_entry_first_refresh()
    # Options changes must apply immediately, without removing the integration.
    entry.async_on_unload(entry.add_update_listener(async_update_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok


async def async_update_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle an options update by refreshing the coordinator in place."""
    backend_url, token, scan_interval = _entry_settings(entry)
    coordinator = hass.data.setdefault(DOMAIN, {}).get(entry.entry_id)
    if not isinstance(coordinator, PortalEnterpriseCoordinator):
        return
    coordinator.backend_url = backend_url
    coordinator.token = token
    coordinator.update_interval = timedelta(seconds=scan_interval)
    await coordinator.async_request_refresh()
