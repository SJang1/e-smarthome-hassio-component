"""Switch platform for Daelim Smart Home (Standby power outlets only)."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DaelimDataUpdateCoordinator
from .outlet import DaelimOutletSwitch

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daelim Smart Home switches (outlets only)."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DaelimDataUpdateCoordinator = data["coordinator"]
    
    entities: list[SwitchEntity] = []
    
    # Add standby power outlet switches (from outlet.py)
    for wallsocket_info in coordinator.api.wallsocket:
        entities.append(
            DaelimOutletSwitch(
                coordinator=coordinator,
                device_info=wallsocket_info,
            )
        )
    
    async_add_entities(entities)
