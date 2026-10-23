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

SENSOR_KEYS = tuple(description.key for description in _TOTAL_SENSORS)


def _to_int(value: object) -> int | None:
    """Coerce a JSON number/string to int, or None."""
    if value is None:
        return None
    try:
        return int(value)
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
