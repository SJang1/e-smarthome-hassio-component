"""Climate platform for Daelim Smart Home (Heating/Thermostat)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DEVICE_HEATING, STATE_ON, STATE_OFF
from .coordinator import DaelimDataUpdateCoordinator
from .entity import DaelimEntity

_LOGGER = logging.getLogger(__name__)

# Temperature limits for Korean heating systems
MIN_TEMP = 5
MAX_TEMP = 40
TEMP_STEP = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daelim Smart Home climate entities."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DaelimDataUpdateCoordinator = data["coordinator"]
    
    entities: list[DaelimClimate] = []
    
    for heating_info in coordinator.api.heating:
        entities.append(
            DaelimClimate(
                coordinator=coordinator,
                device_info=heating_info,
            )
        )
    
    async_add_entities(entities)


class DaelimClimate(DaelimEntity, ClimateEntity):
    """Representation of a Daelim Smart Home heating/thermostat."""

    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_target_temperature_step = TEMP_STEP

    def __init__(
        self,
        coordinator: DaelimDataUpdateCoordinator,
        device_info: dict,
    ) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator, DEVICE_HEATING, device_info)
        self._attr_name = self._uname

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        state = self.device_state
        if state and state.get("arg1") == STATE_ON:
            return HVACMode.HEAT
        return HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return current HVAC action."""
        state = self.device_state
        if state and state.get("arg1") == STATE_ON:
            # Check if heating is actually running (current temp < target)
            try:
                current = float(state.get("arg3", 0))
                target = float(state.get("arg2", 0))
                if current < target:
                    return HVACAction.HEATING
                return HVACAction.IDLE
            except (ValueError, TypeError):
                return HVACAction.HEATING
        return HVACAction.OFF

    @property
    def current_temperature(self) -> float | None:
        """Return current temperature."""
        state = self.device_state
        if state:
            try:
                # arg3 is current temperature
                return float(state.get("arg3", 0))
            except (ValueError, TypeError):
                return None
        return None

    @property
    def target_temperature(self) -> float | None:
        """Return target temperature."""
        state = self.device_state
        if state:
            try:
                # arg2 is target/set temperature
                return float(state.get("arg2", 20))
            except (ValueError, TypeError):
                return 20
        return 20

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode."""
        if hvac_mode == HVACMode.HEAT:
            await self.coordinator.api.set_heating(self._uid, STATE_ON)
        else:
            await self.coordinator.api.set_heating(self._uid, STATE_OFF)
        
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        
        # Ensure heating is on when setting temperature
        await self.coordinator.api.set_heating(
            self._uid, 
            STATE_ON, 
            temperature
        )
        await self.coordinator.async_request_refresh()
