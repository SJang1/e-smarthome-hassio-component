"""Power outlet (wallsocket) entity for Daelim Smart Home."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    DOMAIN,
    DEVICE_WALLSOCKET, 
    STATE_ON, 
    STATE_OFF,
)
from .coordinator import DaelimDataUpdateCoordinator
from .entity import DaelimEntity

_LOGGER = logging.getLogger(__name__)


class DaelimOutletSwitch(DaelimEntity, SwitchEntity):
    """Representation of a Daelim Smart Home standby power outlet."""

    _attr_device_class = SwitchDeviceClass.OUTLET

    def __init__(
        self,
        coordinator: DaelimDataUpdateCoordinator,
        device_info: dict,
    ) -> None:
        """Initialize the outlet switch."""
        super().__init__(coordinator, DEVICE_WALLSOCKET, device_info)
        # Entity name is just "대기전력" - device name provides the location
        self._attr_name = "대기전력"
        self._attr_icon = "mdi:power-socket-eu"
        
        # Override device info to create separate "Outlet" device group
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"outlet_{self._uid}")},
            name=f"대기전력 {self._uname}",
            manufacturer="대림건설 (Daelim)",
            model="e편한세상 대기전력콘센트",
            via_device=(DOMAIN, "main"),
        )

    @property
    def is_on(self) -> bool:
        """Return true if outlet is on."""
        state = self.device_state
        if state:
            arg1 = state.get("arg1")
            _LOGGER.debug("Outlet %s state: arg1=%s (type=%s), full_state=%s", 
                         self._uid, arg1, type(arg1).__name__, state)
            # Check for both string "on" and possible variations
            return arg1 == STATE_ON or arg1 == "On" or arg1 == "ON" or arg1 == True or arg1 == 1 or arg1 == "1"
        _LOGGER.debug("Outlet %s: no device_state found", self._uid)
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the outlet."""
        await self.coordinator.api.set_wallsocket(self._uid, STATE_ON)
        # Notify HA of immediate state change
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the outlet (cut standby power)."""
        await self.coordinator.api.set_wallsocket(self._uid, STATE_OFF)
        # Notify HA of immediate state change
        self.async_write_ha_state()
