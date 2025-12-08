"""Light platform for Daelim Smart Home."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DEVICE_LIGHT, STATE_ON, STATE_OFF
from .coordinator import DaelimDataUpdateCoordinator
from .entity import DaelimEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daelim Smart Home lights."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DaelimDataUpdateCoordinator = data["coordinator"]
    
    entities: list[DaelimLight] = []
    
    # Add individual lights
    for light_info in coordinator.api.lights:
        entities.append(
            DaelimLight(
                coordinator=coordinator,
                device_info=light_info,
            )
        )
    
    # Add "All Lights" control if there are any lights
    if coordinator.api.lights:
        entities.append(
            DaelimAllLights(
                coordinator=coordinator,
            )
        )
    
    async_add_entities(entities)


class DaelimLight(DaelimEntity, LightEntity):
    """Representation of a Daelim Smart Home light."""

    def __init__(
        self,
        coordinator: DaelimDataUpdateCoordinator,
        device_info: dict,
    ) -> None:
        """Initialize the light."""
        super().__init__(coordinator, DEVICE_LIGHT, device_info)
        
        # Check if dimming is supported
        self._supports_dimming = device_info.get("dimming", "n") == "y"
        
        if self._supports_dimming:
            self._attr_color_mode = ColorMode.BRIGHTNESS
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        else:
            self._attr_color_mode = ColorMode.ONOFF
            self._attr_supported_color_modes = {ColorMode.ONOFF}
        
        self._attr_name = self._uname

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        state = self.device_state
        if state:
            return state.get("arg1") == STATE_ON
        return False

    @property
    def brightness(self) -> int | None:
        """Return the brightness of the light (0-255)."""
        if not self._supports_dimming:
            return None
        
        state = self.device_state
        if state and state.get("arg1") == STATE_ON:
            # Daelim uses 1, 3, 6 for brightness levels, convert to 0-255
            # arg3="y" indicates dimming mode is active
            try:
                dim_level = int(state.get("arg2", "6"))
                # Map: 1 -> 85 (low), 3 -> 170 (medium), 6 -> 255 (high)
                if dim_level <= 1:
                    return 85
                elif dim_level <= 3:
                    return 170
                else:
                    return 255
            except (ValueError, TypeError):
                return 255
        return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        
        if brightness is not None and self._supports_dimming:
            await self.coordinator.api.set_light(self._uid, STATE_ON, brightness)
        else:
            await self.coordinator.api.set_light(self._uid, STATE_ON)
        
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        await self.coordinator.api.set_light(self._uid, STATE_OFF)
        await self.coordinator.async_request_refresh()


class DaelimAllLights(LightEntity):
    """Representation of all Daelim Smart Home lights control."""

    _attr_has_entity_name = True
    _attr_name = "전체 조명 (All Lights)"
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(
        self,
        coordinator: DaelimDataUpdateCoordinator,
    ) -> None:
        """Initialize the all lights control."""
        self.coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_all_lights"
        self._is_on = False

    @property
    def is_on(self) -> bool:
        """Return true if any light is on."""
        devices = self.coordinator.data.get("devices", {})
        for key, state in devices.items():
            if key.startswith(f"{DEVICE_LIGHT}_"):
                if state.get("arg1") == STATE_ON:
                    return True
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on all lights."""
        await self.coordinator.api.set_light_all(STATE_ON)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off all lights."""
        await self.coordinator.api.set_light_all(STATE_OFF)
        await self.coordinator.async_request_refresh()
