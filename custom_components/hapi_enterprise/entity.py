"""Shared entity helpers for the hAPI Enterprise integration.

Двете платформи (`sensor`, `binary_sensor`) описват ЕДНО и също устройство. Дотук всяка
класова йерархия строеше речника си на ръка — шест еднакви копия, а връзката към самия
hAPI липсваше във всяко от тях. Тук описанието е на едно място и носи `configuration_url`:
от страницата на устройството в Home Assistant човек стига до панела на hAPI, вместо да
търси адреса в бележките си.
"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

from .const import CONF_PANEL_URL, DOMAIN

PANEL_PATH = "/ui/"


def panel_url(settings: dict[str, Any], backend_url: str) -> str:
    """Адресът на панела на hAPI за страницата на устройството.

    Редът е: изрично зададеният в настройките адрес (той може да е ingress или публичен
    адрес, който Home Assistant не вижда), иначе адресът на admin API-то + `/ui/`.
    Празен резултат значи „не знаем работещ адрес“ — тогава връзка НЕ се показва, защото
    мъртва връзка е по-лоша от липсваща.
    """
    explicit = str(settings.get(CONF_PANEL_URL) or "").strip().rstrip("/")
    if explicit:
        return explicit
    base = str(backend_url or "").strip().rstrip("/")
    if not base:
        return ""
    return base + PANEL_PATH


def portal_device_info(
    entry: ConfigEntry,
    backend_url: str,
    version: str | None = None,
) -> DeviceInfo:
    """Описанието на устройството — едно за всички обекти на интеграцията."""
    settings = {**entry.data, **entry.options}
    info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="hAPI",
        model="Enterprise Portal",
    )
    url = panel_url(settings, backend_url)
    if url:
        info["configuration_url"] = url
    if version:
        info["sw_version"] = str(version)
    return info
