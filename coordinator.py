"""Data Update Coordinator for Daelim Smart Home."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import DaelimSmartHomeAPI
from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


class DaelimDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Daelim Smart Home data."""

    def __init__(self, hass: HomeAssistant, api: DaelimSmartHomeAPI) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API."""
        try:
            # Ensure protocol is connected before querying
            await self.api.ensure_protocol_connected()
            
            await self.api.query_all_devices()
            
            # Fetch energy data (monthly and yearly)
            # These queries are independent - one failing shouldn't affect others
            energy_data = None
            energy_yearly = None
            
            try:
                energy_data = await self.api.query_energy_monthly()
            except Exception as ex:
                _LOGGER.warning("Failed to fetch monthly energy data: %s", ex)
            
            try:
                energy_yearly = await self.api.query_all_energy_yearly()
            except Exception as ex:
                _LOGGER.warning("Failed to fetch yearly energy data: %s", ex)
            
            return {
                "devices": self.api.device_states,
                "guard_mode": self.api.guard_mode,
                "lights": self.api.lights,
                "heating": self.api.heating,
                "gas": self.api.gas,
                "fan": self.api.fan,
                "wallsocket": self.api.wallsocket,
                "energy": energy_data,
                "energy_yearly": energy_yearly,
            }
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
