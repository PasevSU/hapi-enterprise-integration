"""Binary sensors for hAPI Enterprise: is something broken right now?

Защо отделна платформа, а не още един `sensor`: Home Assistant има типове за точно
тези две неща — `problem` („има проблем, виж атрибутите“) и `connectivity`
(„връзката с устройството е жива“). Така автоматизациите се пишат с `state: "on"`,
без да се сравняват низове от `sensor.hapi_health`.

Прагът НЕ се смята тук: `mirror_problem` идва готов от add-on-а
(`guidance.checks.mirror_problem`, вж. `hapi_enterprise/decision-sensors.js`), за да
не може панелът и Home Assistant да казват различни неща за едно и също измерване.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import PortalEnterpriseCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class PortalBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describe a hAPI Enterprise binary sensor."""

    key: str


_BINARY_SENSORS: tuple[PortalBinarySensorEntityDescription, ...] = (
    PortalBinarySensorEntityDescription(
        key="mirror_problem",
        translation_key="mirror_problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:harddisk-plus",
    ),
    PortalBinarySensorEntityDescription(
        key="api_available",
        translation_key="api_available",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        icon="mdi:lan-connect",
    ),
    # Тревога по ПРОЗОРЕЦА (5 мин), не по натрупания брояч: иначе би светела вечно след
    # първия отказ. Вдига се само за крос-портални опити и за отнет токен.
    PortalBinarySensorEntityDescription(
        key="public_gateway_security_alert",
        translation_key="public_gateway_security_alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:shield-lock-outline",
    ),
)

BINARY_SENSOR_KEYS = tuple(description.key for description in _BINARY_SENSORS)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform from a config entry."""
    coordinator: PortalEnterpriseCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        PortalProblemBinarySensor(coordinator, entry, description)
        for description in _BINARY_SENSORS
    )


class PortalProblemBinarySensor(BinarySensorEntity):
    """`mirror_problem` (problem) and `api_available` (connectivity)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PortalEnterpriseCoordinator,
        entry: ConfigEntry,
        description: PortalBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
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
        """Availability differs per key — a dead API must still show as `off`.

        За `api_available` сензорът НЕ бива да изчезва, когато API-то не отговаря:
        точно това е състоянието, което трябва да се види. Останалите сензори
        следват координатора.
        """
        if self.entity_description.key == "api_available":
            return True
        return self.coordinator.last_update_success and self.coordinator.data is not None

    @property
    def is_on(self) -> bool | None:
        """True = има проблем (mirror/security) / API-то отговаря (availability)."""
        if self.entity_description.key == "api_available":
            return bool(self.coordinator.last_update_success)
        data = self.coordinator.data or {}
        if self.entity_description.key == "public_gateway_security_alert":
            # Само ПРОЗОРЕЦЪТ (последните 5 мин), не натрупаният брояч: иначе тревогата
            # би светела вечно след първия отказ. Брои се крос-порталният опит и опитът
            # с отнет токен — те са сигурностни, не „грешен адрес“.
            cross = data.get("security_window_cross_portal")
            revoked = data.get("security_window_revoked")
            if cross is None and revoked is None:
                return None
            return (cross or 0) + (revoked or 0) > 0
        value = data.get("mirror_problem")
        # Липсващото измерване не е „проблем“: `None` → `unknown`, а не „on“.
        return None if value is None else bool(value)

    @property
    def extra_state_attributes(self) -> dict | None:
        """The recommended check, so the attribute says what to look at."""
        if self.entity_description.key != "mirror_problem":
            return None
        data = self.coordinator.data or {}
        attributes = {
            "recommended_component": data.get("recommended_component"),
            "recommended_reason": data.get("recommended_reason"),
            "recommended_severity": data.get("recommended_severity"),
            "guidance_status": data.get("health"),
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
