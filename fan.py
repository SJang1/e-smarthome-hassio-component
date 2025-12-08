"""Fan platform for Daelim Smart Home (Ventilation/환기)."""
from __future__ import annotations

import logging
import math
from typing import Any

from homeassistant.components.fan import (
    FanEntity,
    FanEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from .const import DOMAIN, DEVICE_FAN, STATE_ON, STATE_OFF
from .coordinator import DaelimDataUpdateCoordinator
from .entity import DaelimEntity

_LOGGER = logging.getLogger(__name__)

# Fan speed levels (01=low, 02=medium, 03=high)
SPEED_LEVELS = ["01", "02", "03"]
SPEED_NAMES = {
    "01": "약 (Low)",
    "02": "중 (Medium)",
    "03": "강 (High)",
}

# Preset modes
PRESET_MODES = {
    "00": "일반 (Normal)",
    "01": "자동 (Auto)",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daelim Smart Home fan entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DaelimDataUpdateCoordinator = data["coordinator"]
    
    entities: list[DaelimFan] = []
    
    for fan_info in coordinator.api.fan:
        entities.append(
            DaelimFan(
                coordinator=coordinator,
                device_info=fan_info,
            )
        )
    
    async_add_entities(entities)


class DaelimFan(DaelimEntity, FanEntity):
    """Representation of a Daelim Smart Home fan/ventilation."""

    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )
    _attr_speed_count = len(SPEED_LEVELS)
    _attr_preset_modes = list(PRESET_MODES.values())

    def __init__(
        self,
        coordinator: DaelimDataUpdateCoordinator,
        device_info: dict,
    ) -> None:
        """Initialize the fan."""
        super().__init__(coordinator, DEVICE_FAN, device_info)
        self._attr_name = f"환기 {self._uname}"
        self._attr_icon = "mdi:fan"

    @property
    def is_on(self) -> bool:
        """Return true if fan is on."""
        state = self.device_state
        if state:
            arg1 = state.get("arg1")
            _LOGGER.debug("Fan %s state: arg1=%s, arg2(speed)=%s, arg3(mode)=%s, full_state=%s", 
                         self._uid, arg1, state.get("arg2"), state.get("arg3"), state)
            return arg1 == STATE_ON
        _LOGGER.debug("Fan %s: no device_state found", self._uid)
        return False

    @property
    def percentage(self) -> int | None:
        """Return the current speed percentage."""
        state = self.device_state
        if state and state.get("arg1") == STATE_ON:
            speed_code = state.get("arg2", "02")
            if speed_code in SPEED_LEVELS:
                return ordered_list_item_to_percentage(SPEED_LEVELS, speed_code)
        return None

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        state = self.device_state
        if state:
            mode_code = state.get("arg3", "00")
            return PRESET_MODES.get(mode_code, "일반 (Normal)")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        state = self.device_state
        if state:
            return {
                "running_time": state.get("arg4", "00:00:00"),
                "speed_code": state.get("arg2"),
                "mode_code": state.get("arg3"),
            }
        return {}

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan."""
        speed_code = None
        mode_code = None
        
        if percentage is not None:
            speed_code = percentage_to_ordered_list_item(SPEED_LEVELS, percentage)
        
        if preset_mode is not None:
            for code, name in PRESET_MODES.items():
                if name == preset_mode:
                    mode_code = code
                    break
        
        await self.coordinator.api.set_fan(
            self._uid, 
            STATE_ON, 
            speed=speed_code,
            mode=mode_code,
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the fan."""
        await self.coordinator.api.set_fan(self._uid, STATE_OFF)
        await self.coordinator.async_request_refresh()

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed percentage."""
        if percentage == 0:
            await self.async_turn_off()
        else:
            speed_code = percentage_to_ordered_list_item(SPEED_LEVELS, percentage)
            await self.coordinator.api.set_fan(self._uid, STATE_ON, speed=speed_code)
            await self.coordinator.async_request_refresh()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set preset mode."""
        mode_code = None
        for code, name in PRESET_MODES.items():
            if name == preset_mode:
                mode_code = code
                break
        
        if mode_code:
            await self.coordinator.api.set_fan(self._uid, STATE_ON, mode=mode_code)
            await self.coordinator.async_request_refresh()
