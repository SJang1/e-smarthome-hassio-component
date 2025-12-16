"""Custom entry helpers for Daelim Smart Home integration.

Provides a service to force-refresh all data and publish the full result.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN
from .coordinator import DaelimDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_UPDATE_ALL = "update_all_data"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register services for this config entry.

    Service: `daelim_smarthome.update_all_data`
    - Forces an immediate coordinator refresh
    - Stores the full result at `hass.data[DOMAIN][entry_id]["last_update_result"]`
    - Fires an event `<DOMAIN>_update_result` with payload `{entry_id, result}`
    """

    async def handle_update_all(call: Any) -> None:
        """Handle service call by scheduling a non-blocking queued update.

        This schedules the coordinator refresh via `coordinator.run_command` so it
        participates in the same command queue as other device commands and
        will not block the caller. The full result is stored under
        `hass.data[DOMAIN][entry_id]["update_all_result"]` and an event is fired
        when the update completes.
        """
        data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if not data:
            _LOGGER.error("No data for entry %s", entry.entry_id)
            return

        coordinator: DaelimDataUpdateCoordinator = data.get("coordinator")
        if not coordinator:
            _LOGGER.error("No coordinator available for entry %s", entry.entry_id)
            return

        async def _background_update() -> None:
            try:
                # Use coordinator.run_command to enqueue and serialize with other commands
                await coordinator.run_command(coordinator.async_refresh)

                # After refresh, coordinator.data contains the full result
                result = coordinator.data

                # Persist the last result (JSON-serializable dict) under update_all_button_result
                hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})["update_all_button_result"] = result

                # Fire an event so automations/users can consume the payload
                hass.bus.async_fire(f"{DOMAIN}_update_all_button_result", {"entry_id": entry.entry_id, "result": result})
                _LOGGER.info("%s: update_all_data completed for entry %s", DOMAIN, entry.entry_id)
            except Exception as ex:  # pragma: no cover - runtime errors
                _LOGGER.exception("%s: update_all_data failed for entry %s: %s", DOMAIN, entry.entry_id, ex)

        # Schedule the background update task and return immediately (non-blocking)
        hass.async_create_task(_background_update())

    hass.services.async_register(DOMAIN, SERVICE_UPDATE_ALL, handle_update_all)

    # Ensure service is removed when the entry unloads
    entry.async_on_unload(lambda: hass.services.async_remove(DOMAIN, SERVICE_UPDATE_ALL))

    # Register UI entities directly on platform objects (button & sensor)
    try:
        coord = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    except Exception:  # pragma: no cover - defensive
        _LOGGER.error("Coordinator not available when registering UI entities for entry %s", entry.entry_id)
        return

    # Import here to avoid circular imports at module load time
    from homeassistant.helpers import entity_platform as ep

    # Use async_get_platforms (available on some HA versions) and find
    # the platform instance that matches our integration `DOMAIN`.
    try:
        # async_get_platforms returns a list (not a coroutine) in some HA versions
        button_platforms = ep.async_get_platforms(hass, "button")
        btn_plat = None
        for p in button_platforms:
            # platform_name may identify which integration provided the platform
            if getattr(p, "platform_name", None) == DOMAIN:
                btn_plat = p
                break
        # Fallback: take first platform if name-match not found
        if btn_plat is None and button_platforms:
            btn_plat = button_platforms[0]

        if btn_plat:
            # Avoid duplicate unique_id creation if an entity already exists
            try:
                from homeassistant.helpers import entity_registry as er

                registry = er.async_get(hass)
                unique_id = f"{DOMAIN}_update_all_{entry.entry_id}"
                existing = registry.async_get_entity_id("button", DOMAIN, unique_id)
                if existing:
                    _LOGGER.info("Update button already registered as %s, skipping creation", existing)
                else:
                    maybe_coro = btn_plat.async_add_entities([DaelimUpdateAllButton(coord, entry.entry_id)])
                    # async_add_entities may be a coroutine on some HA versions
                    try:
                        import inspect

                        if inspect.isawaitable(maybe_coro):
                            await maybe_coro
                    except Exception:
                        _LOGGER.debug("async_add_entities did not require awaiting or failed to await for button platform")
            except Exception as ex:
                _LOGGER.exception("Error checking entity registry for update button: %s", ex)
        else:
            _LOGGER.warning("No button platform found to add update button for %s", entry.entry_id)
    except Exception as ex:  # pragma: no cover - runtime
        _LOGGER.exception("Failed to add update button to button platform: %s", ex)

    try:
        sensor_platforms = ep.async_get_platforms(hass, "sensor")
        sen_plat = None
        for p in sensor_platforms:
            if getattr(p, "platform_name", None) == DOMAIN:
                sen_plat = p
                break
        if sen_plat is None and sensor_platforms:
            sen_plat = sensor_platforms[0]

        if sen_plat:
            try:
                from homeassistant.helpers import entity_registry as er

                registry = er.async_get(hass)
                unique_id = f"{DOMAIN}_update_all_result_{entry.entry_id}"
                existing = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
                if existing:
                    _LOGGER.info("Update result sensor already registered as %s, skipping creation", existing)
                else:
                    maybe_coro = sen_plat.async_add_entities([DaelimUpdateResultSensor(coord, entry.entry_id)])
                    try:
                        import inspect

                        if inspect.isawaitable(maybe_coro):
                            await maybe_coro
                    except Exception:
                        _LOGGER.debug("async_add_entities did not require awaiting or failed to await for sensor platform")
            except Exception as ex:
                _LOGGER.exception("Error checking entity registry for update result sensor: %s", ex)
        else:
            _LOGGER.warning("No sensor platform found to add update result sensor for %s", entry.entry_id)
    except Exception as ex:  # pragma: no cover - runtime
        _LOGGER.exception("Failed to add update result sensor to sensor platform: %s", ex)


# --- UI entity classes (kept here so update logic is centralized) ---
from homeassistant.components.button import ButtonEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from datetime import datetime


class DaelimUpdateAllButton(ButtonEntity):
    """Button entity that triggers update-all (non-blocking, queued)."""

    _attr_has_entity_name = True
    _attr_name = "e편한세상 스마트홈 전체 데이터 업데이트"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: DaelimDataUpdateCoordinator, entry_id: str) -> None:
        self.coordinator = coordinator
        self._entry_id = entry_id
        self._attr_unique_id = f"{DOMAIN}_update_all_{entry_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "update_all", entry_id)},
            name="e편한세상 스마트홈 전체 데이터 업데이트",
            manufacturer="대림건설 (Daelim)",
            model="e편한세상 스마트홈 전체 데이터 업데이트",
            via_device=(DOMAIN, "main"),
        )

    async def async_press(self) -> None:
        hass = self.coordinator.hass

        async def _do_update() -> None:
            try:
                await self.coordinator.run_command(self.coordinator.async_refresh)
                result = self.coordinator.data
                hass.data.setdefault(DOMAIN, {}).setdefault(self._entry_id, {})["update_all_button_result"] = result
                hass.bus.async_fire(f"{DOMAIN}_update_all_button_result", {"entry_id": self._entry_id, "result": result})
                _LOGGER.info("Update-all-data button completed for entry %s", self._entry_id)
            except Exception as ex:
                _LOGGER.exception("Failed to update all data from button for entry %s: %s", self._entry_id, ex)

        hass.async_create_task(_do_update())


class DaelimUpdateResultSensor(SensorEntity):
    """Sensor that exposes the last update-all result as attributes."""

    _attr_has_entity_name = True
    _attr_name = "e편한세상 스마트홈 전체 업데이트 결과"
    _attr_icon = "mdi:file-document"

    def __init__(self, coordinator: DaelimDataUpdateCoordinator, entry_id: str) -> None:
        self.coordinator = coordinator
        self._entry_id = entry_id
        self._attr_unique_id = f"{DOMAIN}_update_all_result_{entry_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "update_all_result", entry_id)},
            name="e편한세상 스마트홈 전체 업데이트 결과",
            manufacturer="대림건설 (Daelim)",
            model="e편한세상 스마트홈 전체 업데이트 결과",
            via_device=(DOMAIN, "main"),
        )

        self._state: str | None = None
        self._attrs: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:  # type: ignore[override]
        # Listen for update results fired by service/button
        self.hass.bus.async_listen(f"{DOMAIN}_update_all_button_result", self._handle_event)

        # Initialize from stored result if present
        entry_store = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        result = entry_store.get("update_all_button_result")
        if result is not None:
            self._state = datetime.utcnow().isoformat()
            self._attrs = {"result": result}

    async def _handle_event(self, event: Any) -> None:
        payload = event.data
        if payload.get("entry_id") != self._entry_id:
            return
        result = payload.get("result")
        self._state = datetime.utcnow().isoformat()
        self._attrs = {"result": result}
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        return self._state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._attrs

