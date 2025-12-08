"""Valve platform for Daelim Smart Home (Gas valve)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.valve import ValveEntity, ValveEntityFeature, ValveDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    DOMAIN,
    DEVICE_GAS, 
    STATE_ON, 
    STATE_OFF,
)
from .coordinator import DaelimDataUpdateCoordinator
from .entity import DaelimEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daelim Smart Home gas valves."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DaelimDataUpdateCoordinator = data["coordinator"]
    
    entities: list[ValveEntity] = []
    
    # Add gas valve entities
    for gas_info in coordinator.api.gas:
        entities.append(
            DaelimGasValve(
                coordinator=coordinator,
                device_info=gas_info,
            )
        )
    
    async_add_entities(entities)


class DaelimGasValve(DaelimEntity, ValveEntity):
    """Representation of a Daelim Smart Home gas valve."""

    _attr_device_class = ValveDeviceClass.GAS
    _attr_reports_position = False  # Binary valve (open/closed), not positional

    def __init__(
        self,
        coordinator: DaelimDataUpdateCoordinator,
        device_info: dict,
    ) -> None:
        """Initialize the gas valve."""
        super().__init__(coordinator, DEVICE_GAS, device_info)
        self._attr_name = "가스밸브"
        self._attr_supported_features = ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE
        
        # Override device info for gas valve
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"gas_{self._uid}")},
            name=f"가스 {self._uname}",
            manufacturer="대림건설 (Daelim)",
            model="e편한세상 가스밸브",
            via_device=(DOMAIN, "main"),
        )

    @property
    def is_closed(self) -> bool:
        """Return true if gas valve is closed."""
        state = self.device_state
        if state:
            arg1 = state.get("arg1")
            _LOGGER.debug("Gas valve %s state: arg1=%s, full_state=%s", 
                         self._uid, arg1, state)
            return arg1 != STATE_ON
        _LOGGER.debug("Gas valve %s: no device_state found", self._uid)
        return True  # Default to closed for safety

    async def async_open_valve(self, **kwargs: Any) -> None:
        """Open gas valve."""
        _LOGGER.warning(
            "Opening gas valve remotely - please verify this is allowed by your system"
        )
        await self.coordinator.api.set_gas(self._uid, STATE_ON)
        # Notify HA of immediate state change
        self.async_write_ha_state()

    async def async_close_valve(self, **kwargs: Any) -> None:
        """Close gas valve (safety lock)."""
        await self.coordinator.api.set_gas(self._uid, STATE_OFF)
        # Notify HA of immediate state change
        self.async_write_ha_state()
