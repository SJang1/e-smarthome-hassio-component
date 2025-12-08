"""Base entity for Daelim Smart Home integration."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DaelimDataUpdateCoordinator


class DaelimEntity(CoordinatorEntity[DaelimDataUpdateCoordinator]):
    """Base entity for Daelim Smart Home."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DaelimDataUpdateCoordinator,
        device_type: str,
        device_info: dict,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._device_type = device_type
        self._device_info = device_info
        self._uid = device_info.get("uid", "")
        # Support both 'uname' and 'name' keys for device name
        self._uname = device_info.get("uname") or device_info.get("name") or f"{device_type}_{self._uid}"
        
        # Unique ID for the entity
        self._attr_unique_id = f"{DOMAIN}_{device_type}_{self._uid}"
        
        # Device info for device registry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{device_type}_{self._uid}")},
            name=self._uname,
            manufacturer="대림건설 (Daelim)",
            model="e편한세상 Smart Home",
            via_device=(DOMAIN, "main"),
        )

    @property
    def device_state(self) -> dict | None:
        """Return the current state of the device from coordinator."""
        state_key = f"{self._device_type}_{self._uid}"
        return self.coordinator.data.get("devices", {}).get(state_key)
