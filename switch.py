"""Switch platform for Daelim Smart Home (Gas valve, Standby outlets, All-off)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    DOMAIN, 
    DEVICE_GAS, 
    DEVICE_WALLSOCKET, 
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
    """Set up Daelim Smart Home switches."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DaelimDataUpdateCoordinator = data["coordinator"]
    
    entities: list[SwitchEntity] = []
    
    # Add gas valve switches
    for gas_info in coordinator.api.gas:
        entities.append(
            DaelimGasSwitch(
                coordinator=coordinator,
                device_info=gas_info,
            )
        )
    
    # Add standby power outlet switches
    for wallsocket_info in coordinator.api.wallsocket:
        entities.append(
            DaelimWallsocketSwitch(
                coordinator=coordinator,
                device_info=wallsocket_info,
            )
        )
    
    # Add master "All Off" switch
    entities.append(
        DaelimAllOffSwitch(
            coordinator=coordinator,
        )
    )
    
    async_add_entities(entities)


class DaelimGasSwitch(DaelimEntity, SwitchEntity):
    """Representation of a Daelim Smart Home gas valve."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self,
        coordinator: DaelimDataUpdateCoordinator,
        device_info: dict,
    ) -> None:
        """Initialize the gas switch."""
        super().__init__(coordinator, DEVICE_GAS, device_info)
        self._attr_name = f"가스 {self._uname}"
        self._attr_icon = "mdi:gas-cylinder"

    @property
    def is_on(self) -> bool:
        """Return true if gas valve is open (on)."""
        state = self.device_state
        if state:
            return state.get("arg1") == STATE_ON
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Open gas valve.
        
        Note: For safety, opening the gas valve remotely may not be allowed
        by all systems. This is typically only used to unlock after closing.
        """
        _LOGGER.warning(
            "Opening gas valve remotely - please verify this is allowed by your system"
        )
        await self.coordinator.api.set_gas(self._uid, STATE_ON)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Close gas valve (safety lock)."""
        await self.coordinator.api.set_gas(self._uid, STATE_OFF)
        await self.coordinator.async_request_refresh()


class DaelimWallsocketSwitch(DaelimEntity, SwitchEntity):
    """Representation of a Daelim Smart Home standby power outlet."""

    _attr_device_class = SwitchDeviceClass.OUTLET

    def __init__(
        self,
        coordinator: DaelimDataUpdateCoordinator,
        device_info: dict,
    ) -> None:
        """Initialize the wallsocket switch."""
        super().__init__(coordinator, DEVICE_WALLSOCKET, device_info)
        self._attr_name = f"대기전력 {self._uname}"
        self._attr_icon = "mdi:power-socket-eu"

    @property
    def is_on(self) -> bool:
        """Return true if outlet is on."""
        state = self.device_state
        if state:
            return state.get("arg1") == STATE_ON
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the outlet."""
        await self.coordinator.api.set_wallsocket(self._uid, STATE_ON)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the outlet (cut standby power)."""
        await self.coordinator.api.set_wallsocket(self._uid, STATE_OFF)
        await self.coordinator.async_request_refresh()


class DaelimAllOffSwitch(SwitchEntity):
    """Representation of Daelim Smart Home all-off (일괄차단) control."""

    _attr_has_entity_name = True
    _attr_name = "일괄차단 (All Off)"
    _attr_icon = "mdi:power-off"

    def __init__(
        self,
        coordinator: DaelimDataUpdateCoordinator,
    ) -> None:
        """Initialize the all-off switch."""
        self.coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_all_off"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "controls")},
            name="Daelim Smart Home Controls",
            manufacturer="대림건설 (Daelim)",
            model="e편한세상 Smart Home",
        )
        self._is_on = False

    @property
    def is_on(self) -> bool:
        """Return false - this is a momentary switch."""
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Execute all-off command."""
        await self.coordinator.api.set_all_off()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """No action - all-off is a one-way command."""
        pass
