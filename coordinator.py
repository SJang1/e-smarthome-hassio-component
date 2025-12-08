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
            await self.api.query_all_devices()
            return {
                "devices": self.api.device_states,
                "guard_mode": self.api.guard_mode,
                "lights": self.api.lights,
                "heating": self.api.heating,
                "gas": self.api.gas,
                "fan": self.api.fan,
                "wallsocket": self.api.wallsocket,
            }
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
