"""Alarm Control Panel platform for Daelim Smart Home (Guard/Security Mode)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, GUARD_MODE_OFF, GUARD_MODE_AWAY
from .coordinator import DaelimDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daelim Smart Home alarm control panel."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DaelimDataUpdateCoordinator = data["coordinator"]
    
    async_add_entities([DaelimAlarmPanel(coordinator)])


class DaelimAlarmPanel(AlarmControlPanelEntity):
    """Representation of Daelim Smart Home security/guard mode."""

    _attr_has_entity_name = True
    _attr_name = "방범모드 (Security)"
    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_AWAY
    )
    _attr_code_format = CodeFormat.NUMBER
    _attr_code_arm_required = False  # Can arm without code

    def __init__(
        self,
        coordinator: DaelimDataUpdateCoordinator,
    ) -> None:
        """Initialize the alarm panel."""
        self.coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_alarm_panel"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "security")},
            name="Daelim Security System",
            manufacturer="대림건설 (Daelim)",
            model="e편한세상 Smart Home",
        )

    @property
    def state(self) -> AlarmControlPanelState | None:
        """Return the state of the alarm."""
        guard_mode = self.coordinator.data.get("guard_mode", GUARD_MODE_OFF)
        if guard_mode == GUARD_MODE_AWAY:
            return AlarmControlPanelState.ARMED_AWAY
        return AlarmControlPanelState.DISARMED

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            "guard_mode_raw": self.coordinator.data.get("guard_mode"),
        }

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Disarm the alarm (외출해제)."""
        await self.coordinator.api.set_guard_mode(GUARD_MODE_OFF, password=code)
        await self.coordinator.async_request_refresh()

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Arm the alarm in away mode (외출모드)."""
        await self.coordinator.api.set_guard_mode(GUARD_MODE_AWAY, password=code)
        await self.coordinator.async_request_refresh()
