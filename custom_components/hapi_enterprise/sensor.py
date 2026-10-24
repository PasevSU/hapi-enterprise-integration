"""Sensor platform for hAPI Enterprise telemetry."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.loader import async_get_integration

from .const import DOMAIN
from .coordinator import PortalEnterpriseCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class PortalSensorEntityDescription(SensorEntityDescription):
    """Describe a hAPI Enterprise sensor entity."""

    key: str
    suggested_display_precision: int = 0


_TOTAL_SENSORS: tuple[PortalSensorEntityDescription, ...] = (
    PortalSensorEntityDescription(
        key="visits",
        translation_key="visits",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    PortalSensorEntityDescription(
        key="downloads",
        translation_key="downloads",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    PortalSensorEntityDescription(
        key="files",
        translation_key="files",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    PortalSensorEntityDescription(
        key="portal_count",
        translation_key="portal_count",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    PortalSensorEntityDescription(
        key="file_bytes",
        translation_key="file_bytes",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    PortalSensorEntityDescription(
        key="database_bytes",
        translation_key="database_bytes",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    PortalSensorEntityDescription(
        key="telemetry_bytes",
        translation_key="telemetry_bytes",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    # Комуникация: кой влиза, какво тегли, откъде (виж `visitor-intel.js`).
    PortalSensorEntityDescription(
        key="unique_visitors",
        translation_key="unique_visitors",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    PortalSensorEntityDescription(
        key="visitors_new_24h",
        translation_key="visitors_new_24h",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    PortalSensorEntityDescription(
        key="download_visitors",
        translation_key="download_visitors",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    PortalSensorEntityDescription(
        key="denied_total",
        translation_key="denied_total",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    PortalSensorEntityDescription(
        key="admin_logins",
        translation_key="admin_logins",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    PortalSensorEntityDescription(
        key="countries_known",
        translation_key="countries_known",
        state_class=SensorStateClass.MEASUREMENT,
    ),
)

# --- Решение, не само число (Stage E) ---------------------------------------------
# `guidance` в `/admin/api/sensors` носи готовото решение: кой компонент, откога и какво
# да се провери. Интеграцията НЕ преизчислява прагове — иначе панелът и Home Assistant
# биха могли да казват различни неща за едно и също измерване.
_GUIDANCE_SENSORS: tuple[PortalSensorEntityDescription, ...] = (
    PortalSensorEntityDescription(
        key="health",
        translation_key="health",
        device_class=SensorDeviceClass.ENUM,
        options=["ok", "warning", "critical", "unknown"],
        icon="mdi:heart-pulse",
    ),
    PortalSensorEntityDescription(
        key="http_error_rate",
        translation_key="http_error_rate",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:alert-circle-outline",
    ),
    PortalSensorEntityDescription(
        key="latency_p95",
        translation_key="latency_p95",
        native_unit_of_measurement="ms",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:speedometer",
    ),
    PortalSensorEntityDescription(
        key="download_denial_rate",
        translation_key="download_denial_rate",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:cancel",
    ),
    PortalSensorEntityDescription(
        key="recommended_action",
        translation_key="recommended_action",
        icon="mdi:clipboard-check-outline",
    ),
)

# --- Сигурност (Stage D): издадени токени, откази и живи публични сесии ---------------
# Броячите идват ГOTОВИ от add-on-а (`security` в `/admin/api/sensors`). Натрупаните
# растат вечно, затова тревогата се вдига по `security_recent_denials` (прозорец), а тези
# сензори отговарят на въпроса „колко е имало“ — за отчет, не за аларма.
_SECURITY_SENSORS: tuple[PortalSensorEntityDescription, ...] = (
    PortalSensorEntityDescription(
        key="active_portal_sessions",
        translation_key="active_portal_sessions",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:account-key-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    PortalSensorEntityDescription(
        key="token_validation_failures",
        translation_key="token_validation_failures",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:shield-alert-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    PortalSensorEntityDescription(
        key="revoked_token_attempts",
        translation_key="revoked_token_attempts",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:link-off",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    PortalSensorEntityDescription(
        key="cross_portal_denials",
        translation_key="cross_portal_denials",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:swap-horizontal-bold",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

# QR ревизии, архиви и заключени публикувани файлове. Отговарят на въпроса „колко печата
# има и колко от съдържанието е с ограничен достъп“ — за отчет и за проследимост.
_QR_SENSORS: tuple[PortalSensorEntityDescription, ...] = (
    PortalSensorEntityDescription(
        key="qr_active",
        translation_key="qr_active",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:qrcode",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    PortalSensorEntityDescription(
        key="qr_blocked",
        translation_key="qr_blocked",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:qrcode-remove",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    PortalSensorEntityDescription(
        key="qr_archives",
        translation_key="qr_archives",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:folder-zip-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    PortalSensorEntityDescription(
        key="locked_files",
        translation_key="locked_files",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:file-lock-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    PortalSensorEntityDescription(
        key="integrity_failed",
        translation_key="integrity_failed",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:shield-alert-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

# Версия и синхрон: текст/enum, не числа — затова са в отделен списък със свой клас.
# Смисълът им е точно това, което липсваше: в Home Assistant да се вижда КОЯ версия
# работи add-on-ът и дали съвпада с версията на интеграцията (иначе едната половина
# може да е обновена, а другата не и това не се вижда отникъде).
_VERSION_SENSORS: tuple[PortalSensorEntityDescription, ...] = (
    PortalSensorEntityDescription(
        key="version",
        translation_key="version",
        icon="mdi:tag-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    PortalSensorEntityDescription(
        key="sync",
        translation_key="sync",
        device_class=SensorDeviceClass.ENUM,
        options=["ok", "mismatch", "unknown"],
        icon="mdi:sync",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

SENSOR_KEYS = tuple(
    description.key
    for description in (*_TOTAL_SENSORS, *_GUIDANCE_SENSORS, *_SECURITY_SENSORS, *_QR_SENSORS)
)


def _to_int(value: object) -> int | None:
    """Coerce a JSON number/string to int, or None."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: object) -> float | None:
    """Coerce a JSON number/string to float, or None.

    None is a real value here: „няма измерване“ не е нула. Сензорът трябва да покаже
    `unknown`, а не „0 % грешки“ — иначе липсата на данни изглежда като здраве.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform from a config entry."""
    coordinator: PortalEnterpriseCoordinator = hass.data[DOMAIN][entry.entry_id]
    integration = await async_get_integration(hass, DOMAIN)
    integration_version = getattr(integration, "version", None)
    async_add_entities(
        PortalEnterpriseTotalSensor(coordinator, entry, description)
        for description in _TOTAL_SENSORS
    )
    async_add_entities(
        PortalStatusSensor(coordinator, entry, description, integration_version)
        for description in _VERSION_SENSORS
    )
    async_add_entities(
        PortalGuidanceSensor(coordinator, entry, description)
        for description in _GUIDANCE_SENSORS
    )
    async_add_entities(
        PortalSecuritySensor(coordinator, entry, description)
        for description in _SECURITY_SENSORS
    )
    async_add_entities(
        PortalQrSensor(coordinator, entry, description)
        for description in _QR_SENSORS
    )


class PortalEnterpriseTotalSensor(SensorEntity):
    """A single total-telemetry sensor backed by the coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PortalEnterpriseCoordinator,
        entry: ConfigEntry,
        description: PortalSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "hAPI",
            "model": "Enterprise Portal",
            "sw_version": entry.data.get("addon_version"),
        }

    @property
    def available(self) -> bool:
        """Whether data is available for this sensor."""
        return self.coordinator.last_update_success and self.coordinator.data is not None

    @property
    def native_value(self) -> int | None:
        """Return the current value for the description key."""
        if self.coordinator.data is None:
            return None
        return _to_int(self.coordinator.data.get(self.entity_description.key))

    @property
    def should_poll(self) -> bool:
        """The coordinator handles polling."""
        return False

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator updates."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    def _handle_coordinator_update(self) -> None:
        """Refresh the entity state on coordinator updates."""
        self.async_write_ha_state()


class PortalStatusSensor(SensorEntity):
    """Version of the running add-on and whether it matches the integration."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PortalEnterpriseCoordinator,
        entry: ConfigEntry,
        description: PortalSensorEntityDescription,
        integration_version: str | None,
    ) -> None:
        """Initialize the version/status sensor."""
        self.entity_description = description
        self.coordinator = coordinator
        self.integration_version = integration_version
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "hAPI",
            "model": "Enterprise Portal",
            "sw_version": integration_version,
        }

    @property
    def available(self) -> bool:
        """Whether data is available for this sensor."""
        return self.coordinator.last_update_success and self.coordinator.data is not None

    @property
    def addon_version(self) -> str | None:
        """Version reported by the running add-on, not the installed one."""
        data = self.coordinator.data or {}
        value = data.get("version")
        return str(value) if value else None

    @property
    def native_value(self) -> str | None:
        """Add-on version, or the sync state (ok / mismatch / unknown)."""
        if self.entity_description.key == "version":
            return self.addon_version
        addon = self.addon_version
        if not addon or not self.integration_version:
            # Липсва стойност: не се твърди „съвпада“. `unknown` е валидна опция.
            return "unknown"
        return "ok" if addon == str(self.integration_version) else "mismatch"

    @property
    def extra_state_attributes(self) -> dict | None:
        """Both versions, so the reason for a mismatch is visible."""
        if self.entity_description.key != "sync":
            return None
        return {
            "addon_version": self.addon_version,
            "integration_version": self.integration_version,
        }

    @property
    def should_poll(self) -> bool:
        """The coordinator handles polling."""
        return False

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator updates."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    def _handle_coordinator_update(self) -> None:
        """Refresh the entity state on coordinator updates."""
        self.async_write_ha_state()


class PortalGuidanceSensor(SensorEntity):
    """The decision the add-on already made: health, measured rates, next action.

    Праговете НЕ се смятат тук (вж. `hapi_enterprise/decision-sensors.js`): ако ги
    дублираме, панелът и Home Assistant биха могли да показват различен статус за
    едни и същи измервания. Интеграцията само чете готовия отговор.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PortalEnterpriseCoordinator,
        entry: ConfigEntry,
        description: PortalSensorEntityDescription,
    ) -> None:
        """Initialize the guidance sensor."""
        self.entity_description = description
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "hAPI",
            "model": "Enterprise Portal",
            "sw_version": entry.data.get("addon_version"),
        }

    @property
    def available(self) -> bool:
        """Whether data is available for this sensor."""
        return self.coordinator.last_update_success and self.coordinator.data is not None

    @property
    def native_value(self) -> str | float | None:
        """Health state, a measured percentage/ms, or the recommended action."""
        data = self.coordinator.data or {}
        key = self.entity_description.key
        if key == "recommended_action":
            value = data.get("recommended_action")
            return str(value) if value else None
        if key == "health":
            value = data.get("health")
            return value if value in ("ok", "warning", "critical", "unknown") else "unknown"
        return _to_float(data.get(key))

    @property
    def extra_state_attributes(self) -> dict | None:
        """Why the decision was made: component, reason, basis and window."""
        key = self.entity_description.key
        if key not in ("health", "recommended_action"):
            return None
        data = self.coordinator.data or {}
        attributes = {
            "basis": data.get("guidance_basis"),
            "window_seconds": data.get("guidance_window_seconds"),
            "recommended_component": data.get("recommended_component"),
            "recommended_severity": data.get("recommended_severity"),
            "recommended_reason": data.get("recommended_reason"),
        }
        return {name: value for name, value in attributes.items() if value is not None}

    @property
    def should_poll(self) -> bool:
        """The coordinator handles polling."""
        return False

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator updates."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    def _handle_coordinator_update(self) -> None:
        """Refresh the entity state on coordinator updates."""
        self.async_write_ha_state()

class PortalQrSensor(SensorEntity):
    """QR ревизии, физически архиви и заключени публикувани файлове.

    Числата идват готови от add-on-а (`qr`, `portal-qr.stats`); тук не се брои повторно.
    `None` остава `unknown` — липсващото измерване не е нула.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PortalEnterpriseCoordinator,
        entry: ConfigEntry,
        description: PortalSensorEntityDescription,
    ) -> None:
        """Initialize the QR sensor."""
        self.entity_description = description
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "hAPI",
            "model": "Enterprise Portal",
            "sw_version": entry.data.get("addon_version"),
        }

    @property
    def available(self) -> bool:
        """Whether data is available for this sensor."""
        return self.coordinator.last_update_success and self.coordinator.data is not None

    @property
    def native_value(self) -> int | None:
        """Return the add-on's count, or None when it is not reported."""
        return _to_int((self.coordinator.data or {}).get(self.entity_description.key))


class PortalSecuritySensor(SensorEntity):
    """Броячи от Stage D: живи сесии, неуспешни проверки, отнети токени, крос-портал.

    Всичко идва готово от add-on-а (`security`), за да няма втори източник на истина
    между панела и Home Assistant. `None` остава `unknown` — липсващото измерване не е нула.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PortalEnterpriseCoordinator,
        entry: ConfigEntry,
        description: PortalSensorEntityDescription,
    ) -> None:
        """Initialize the security sensor."""
        self.entity_description = description
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "hAPI",
            "model": "Enterprise Portal",
            "sw_version": entry.data.get("addon_version"),
        }

    @property
    def available(self) -> bool:
        """Whether data is available for this sensor."""
        return self.coordinator.last_update_success and self.coordinator.data is not None

    @property
    def native_value(self) -> int | None:
        """Cumulative counter from the add-on's `security` block."""
        return _to_int((self.coordinator.data or {}).get(self.entity_description.key))

    @property
    def extra_state_attributes(self) -> dict | None:
        """Прозорецът (5 мин) и режимът — за да се види дали отказът е СЕГА."""
        data = self.coordinator.data or {}
        attributes = {
            "recent_denials_5m": data.get("security_recent_denials"),
            "require_portal_token": data.get("security_require_token"),
        }
        return {name: value for name, value in attributes.items() if value is not None}

    @property
    def should_poll(self) -> bool:
        """The coordinator handles polling."""
        return False

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator updates."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    def _handle_coordinator_update(self) -> None:
        """Refresh the entity state on coordinator updates."""
        self.async_write_ha_state()
