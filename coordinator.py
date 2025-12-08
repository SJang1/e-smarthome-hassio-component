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
from .const import DOMAIN, DEFAULT_UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


class DaelimDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Daelim Smart Home data."""

    def __init__(
        self, 
        hass: HomeAssistant, 
        api: DaelimSmartHomeAPI,
        update_interval: int = DEFAULT_UPDATE_INTERVAL,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )
        self.api = api
        self._update_interval_seconds = update_interval

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
                if energy_data:
                    _LOGGER.info("Energy monthly data received: items=%s", list(energy_data.keys()) if isinstance(energy_data, dict) else type(energy_data))
                else:
                    _LOGGER.warning("Energy monthly query returned None")
            except Exception as ex:
                _LOGGER.warning("Failed to fetch monthly energy data: %s", ex)
            
            try:
                energy_yearly = await self.api.query_all_energy_yearly()
                if energy_yearly:
                    _LOGGER.info("Energy yearly data received for types: %s", list(energy_yearly.keys()) if isinstance(energy_yearly, dict) else type(energy_yearly))
                else:
                    _LOGGER.warning("Energy yearly query returned None")
            except Exception as ex:
                _LOGGER.warning("Failed to fetch yearly energy data: %s", ex)
            
            result = {
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
            _LOGGER.debug("Coordinator data keys: %s", list(result.keys()))
            return result
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
