"""Daelim Smart Home (e편한세상) Integration for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    CONF_APART_ID,
    CONF_DONG,
    CONF_HO,
    CONF_CONTROL_INFO,
    CONF_DEVICE_UUID,
    CONF_LOGIN_PIN,
    DEFAULT_INTERNAL_PORT,
)
from .api import DaelimSmartHomeAPI
from .coordinator import DaelimDataUpdateCoordinator
from .device_registry import get_known_device_config

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.LIGHT,
    Platform.CLIMATE,
    Platform.SWITCH,
    Platform.FAN,
    Platform.ALARM_CONTROL_PANEL,
    Platform.BUTTON,
    Platform.SENSOR,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Daelim Smart Home from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    session = async_get_clientsession(hass)
    
    # Get or generate device UUID for protocol authentication
    device_uuid = entry.data.get(CONF_DEVICE_UUID)
    
    # All apartment info (danji_name, server IP) is auto-discovered from apartId
    api = DaelimSmartHomeAPI(
        session=session,
        host=entry.data[CONF_HOST],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        apart_id=entry.data[CONF_APART_ID],
        dong=entry.data[CONF_DONG],
        ho=entry.data[CONF_HO],
        device_uuid=device_uuid,
    )
    
    # Save generated UUID if it was not in config
    if not device_uuid:
        _LOGGER.info("Generated new device UUID for protocol authentication")
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_DEVICE_UUID: api.device_uuid}
        )

    # Authenticate and get initial data (this also auto-discovers server IP)
    if not await api.authenticate():
        _LOGGER.error("Failed to authenticate with Daelim Smart Home")
        return False

    # Get UI list info (device configuration)
    await api.get_ui_list_info()
    
    # Connect to apartment server for device control
    # The IP is auto-discovered from selectApartInfoCheck.do (public IP)
    # This is non-blocking - if connection fails, we use stored device config
    protocol_connected = False
    stored_control_info = entry.data.get(CONF_CONTROL_INFO)
    
    if api.internal_ip:
        try:
            if await api.connect_protocol():
                _LOGGER.info(
                    "Connected to apartment server at %s:%s",
                    api.internal_ip, DEFAULT_INTERNAL_PORT
                )
                protocol_connected = True
                
                # Save device config for future use if we got new data
                new_control_info = api.get_control_info_for_storage()
                if new_control_info and new_control_info != stored_control_info:
                    _LOGGER.info("Updating stored device configuration")
                    hass.config_entries.async_update_entry(
                        entry,
                        data={**entry.data, CONF_CONTROL_INFO: new_control_info}
                    )
            else:
                _LOGGER.warning(
                    "Could not connect to apartment server at %s:%s. "
                    "Will use stored device configuration if available.",
                    api.internal_ip, DEFAULT_INTERNAL_PORT
                )
        except Exception as ex:
            _LOGGER.warning(
                "Protocol connection failed (will use stored config): %s", ex
            )
    else:
        _LOGGER.warning(
            "No server IP available (selectApartInfoCheck.do returned empty ipAddress). "
            "Will use stored device configuration if available."
        )
    
    # If protocol connection failed, try to use stored device configuration
    # or fall back to known device configurations
    apart_id = entry.data[CONF_APART_ID]
    
    if not protocol_connected and stored_control_info:
        _LOGGER.info(
            "Using stored device configuration (protocol connection failed)"
        )
        if api.set_devices_from_stored_config(stored_control_info):
            _LOGGER.info("Successfully loaded devices from stored configuration")
        else:
            _LOGGER.warning("Failed to load devices from stored configuration")
    elif not protocol_connected and not stored_control_info:
        # Try to get known device configuration for this apartment
        known_config = get_known_device_config(apart_id)
        if known_config:
            _LOGGER.info(
                "Using known device configuration for apartment %s", apart_id
            )
            if api.set_devices_from_stored_config(known_config):
                _LOGGER.info("Successfully loaded devices from known configuration")
                # Save to entry for future use
                hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_CONTROL_INFO: known_config}
                )
            else:
                _LOGGER.warning("Failed to load devices from known configuration")
        else:
            _LOGGER.warning(
                "No device configuration available for apartment %s. "
                "Add device configuration via options flow or reconfigure.",
                apart_id
            )

    coordinator = DaelimDataUpdateCoordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
    }

    # Create the main hub device that child devices will reference via via_device
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "main")},
        manufacturer="대림건설 (Daelim)",
        model="e편한세상 Smart Home Hub",
        name=api.danji_display_name or f"e편한세상 {entry.data[CONF_DONG]}동 {entry.data[CONF_HO]}호",
        sw_version="1.0",
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # Disconnect protocol client
        data = hass.data[DOMAIN].get(entry.entry_id)
        if data:
            api = data.get("api")
            if api:
                await api.disconnect_protocol()
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
