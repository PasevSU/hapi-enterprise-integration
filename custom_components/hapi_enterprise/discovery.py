"""Auto-detection of the hAPI app for the integration's config flow.

Защо съществува: дотук настройката искаше ръчно въвеждане на два адреса и токен, а те са
известни на самия Home Assistant — приложението е инсталирано до него и опциите му се четат
през Supervisor. Затова формата идва попълнена, а ръчното въвеждане остава само резервният
път (HA без Supervisor, приложение на друг хост, различен порт).

Правилата тук са нарочно предпазливи:

* нищо не се записва — връщат се само стойности за попълване на формата;
* всяка стъпка е в ``try/except``: липсващ Supervisor или отнето право не е грешка, а
  „не можах да открия“;
* адресът се проверява с истинска заявка към ``/health``, за да не се попълни порт, който
  отговаря 403 (ingress 8098 приема само Supervisor и loopback).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
from typing import Any

from aiohttp import ClientError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_BACKEND_URL,
    CONF_PANEL_URL,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    DEFAULT_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# Порт 8099 е административното API (изисква токен, достъпно от ядрото на HA).
# Порт 8098 е ingress: отговаря само на Supervisor и loopback, затова е последна опция.
ADMIN_PORT = 8099
INGRESS_PORT = 8098
HEALTH_TIMEOUT = 5
_NAME_HINTS = ("hapi enterprise", "hapi_enterprise")


@dataclass(slots=True)
class Detected:
    """Стойности, намерени без намеса на човека."""

    backend_url: str | None = None
    token: str | None = None
    panel_url: str | None = None
    scan_interval: int = DEFAULT_SCAN_INTERVAL
    source: str = "manual"
    notes: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """True, когато адресът и токенът са намерени и формата може само да се потвърди."""
        return bool(self.backend_url and self.token)

    def as_defaults(self) -> dict[str, Any]:
        """Върни само намереното, за да не се трият стойности при частично откриване."""
        defaults: dict[str, Any] = {CONF_SCAN_INTERVAL: self.scan_interval}
        if self.backend_url:
            defaults[CONF_BACKEND_URL] = self.backend_url
        if self.panel_url:
            defaults[CONF_PANEL_URL] = self.panel_url
        if self.token:
            defaults[CONF_TOKEN] = self.token
        return defaults


def _text(addon: Any, *names: str) -> str:
    """Събери полетата на приложението в един низ за сравнение."""
    return " ".join(str(getattr(addon, name, "") or "") for name in names).lower()


def _is_hapi(addon: Any) -> bool:
    """Познай hAPI по име, slug или hostname — и трите се срещат в различните издания."""
    haystack = _text(addon, "name", "slug", "hostname")
    return any(hint in haystack for hint in _NAME_HINTS)


async def _async_supervisor_addon(hass: HomeAssistant) -> Any | None:
    """Върни информацията за hAPI от Supervisor или None, ако не е наличен."""
    try:
        from homeassistant.components.hassio.handler import get_supervisor_client
    except ImportError:
        # HA без Supervisor (Container/Core) — няма какво да открием.
        return None

    try:
        client = get_supervisor_client(hass)
        installed = await client.addons.list()
    except Exception:  # noqa: BLE001 — липсващ Supervisor не е грешка за формата
        _LOGGER.debug("hAPI: Supervisor недостъпен за автоматично откриване")
        return None

    for addon in installed:
        if not _is_hapi(addon):
            continue
        slug = getattr(addon, "slug", None)
        if not slug:
            return addon
        try:
            return await client.addons.addon_info(slug)
        except Exception:  # noqa: BLE001 — по-добре частичните данни от списъка
            return addon
    return None


async def _async_reachable(hass: HomeAssistant, url: str) -> bool:
    """Провери дали адресът отговаря на /health (без токен)."""
    session = async_get_clientsession(hass)
    try:
        async with asyncio.timeout(HEALTH_TIMEOUT):
            async with session.get(url.rstrip("/") + "/health") as resp:
                return resp.status < 500
    except (ClientError, TimeoutError, OSError):
        return False


def _candidate_hosts(addon: Any) -> list[str]:
    """Възможните имена на приложението в мрежата на Supervisor."""
    hosts: list[str] = []
    for value in (getattr(addon, "hostname", None), getattr(addon, "slug", None)):
        host = str(value or "").strip()
        if host and host not in hosts:
            hosts.append(host)
    return hosts


async def async_detect(hass: HomeAssistant) -> Detected:
    """Открий адреса, токена и интервала на hAPI без ръчно въвеждане.

    Редът е: запазени стойности → Supervisor (име, hostname, опции) → проверка на порта.
    Връща ``Detected`` винаги; празните полета просто не се попълват.
    """
    addon = await _async_supervisor_addon(hass)
    if addon is None:
        return Detected()

    detected = Detected(source="supervisor")

    host = next(iter(_candidate_hosts(addon)), "")
    if host:
        for port in (ADMIN_PORT, INGRESS_PORT):
            url = f"http://{host}:{port}"
            if await _async_reachable(hass, url):
                detected.backend_url = url
                break
        if detected.backend_url is None:
            detected.notes.append("backend_unreachable")

    options = getattr(addon, "options", None) or {}
    if isinstance(options, dict):
        token = str(options.get(CONF_TOKEN) or "").strip()
        if token:
            detected.token = token
        else:
            detected.notes.append("token_missing")

    if not detected.backend_url:
        detected.notes.append("url_missing")
    return detected
