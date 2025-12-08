"""Button platform for Daelim Smart Home (Elevator Call)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import DaelimDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daelim Smart Home buttons."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DaelimDataUpdateCoordinator = data["coordinator"]
    
    entities: list[ButtonEntity] = []
    
    # Add elevator call button
    entities.append(DaelimElevatorButton(coordinator))
    
    async_add_entities(entities)


class DaelimElevatorButton(ButtonEntity):
    """Representation of Daelim Smart Home elevator call button."""

    _attr_has_entity_name = True
    _attr_name = "엘리베이터 호출 (Elevator Call)"
    _attr_icon = "mdi:elevator-passenger"

    def __init__(
        self,
        coordinator: DaelimDataUpdateCoordinator,
    ) -> None:
        """Initialize the button."""
        self.coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_elevator_call"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "controls")},
            name="Daelim Smart Home Controls",
            manufacturer="대림건설 (Daelim)",
            model="e편한세상 Smart Home",
        )

    async def async_press(self) -> None:
        """Handle button press - call elevator."""
        success = await self.coordinator.api.call_elevator()
        if success:
            _LOGGER.info("Elevator call sent successfully")
        else:
            _LOGGER.warning("Failed to call elevator")
