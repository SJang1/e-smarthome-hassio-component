"""Config flow for Daelim Smart Home integration."""
from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant import data_entry_flow
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    DOMAIN,
    CONF_APART_ID,
    CONF_DONG,
    CONF_HO,
    CONF_CONTROL_INFO,
    DEFAULT_HOST,
)
from .api import DaelimSmartHomeAPI, fetch_apartment_list, get_dong_list

_LOGGER = logging.getLogger(__name__)


class DaelimSmartHomeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Daelim Smart Home."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._apartments: list[dict] = []
        self._selected_apartment: dict | None = None
        self._host: str = DEFAULT_HOST
        self._username: str = ""
        self._password: str = ""
        self._apart_id: str = ""
        self._dong: str = ""

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> DaelimSmartHomeOptionsFlow:
        """Get the options flow for this handler."""
        return DaelimSmartHomeOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - fetch apartments and show selection."""
        errors: dict[str, str] = {}

        # Fetch apartment list if not already fetched
        if not self._apartments:
            session = async_get_clientsession(self.hass)
            self._apartments = await fetch_apartment_list(session, DEFAULT_HOST)
            
            if not self._apartments:
                errors["base"] = "cannot_connect"
                # Fall back to manual entry
                return await self.async_step_manual()

        if user_input is not None:
            self._apart_id = user_input[CONF_APART_ID]
            
            # Find selected apartment info
            for apt in self._apartments:
                if apt.get("apartId") == self._apart_id:
                    self._selected_apartment = apt
                    break
            
            if self._selected_apartment:
                return await self.async_step_dong()
            else:
                errors["base"] = "invalid_apartment"

        # Build apartment options for dropdown
        apt_options = [
            {
                "value": apt["apartId"],
                "label": f"{apt.get('name', 'Unknown')} ({apt.get('danjiArea', '')})",
            }
            for apt in self._apartments
        ]
        
        # Sort by name
        apt_options.sort(key=lambda x: x["label"])

        data_schema = vol.Schema(
            {
                vol.Required(CONF_APART_ID): SelectSelector(
                    SelectSelectorConfig(
                        options=apt_options,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "apartment_count": str(len(self._apartments)),
            },
        )

    async def async_step_dong(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle dong (building) selection step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._dong = user_input[CONF_DONG]
            return await self.async_step_credentials()

        # Get available dong list from selected apartment
        dong_info = self._selected_apartment.get("danjiDongInfo", "")
        dong_list = get_dong_list(dong_info)
        
        if not dong_list:
            # No dong info available, use text input
            data_schema = vol.Schema(
                {
                    vol.Required(CONF_DONG): str,
                }
            )
        else:
            # Build dong options for dropdown
            dong_options = [
                {"value": d, "label": f"{d}동"}
                for d in dong_list
            ]
            
            data_schema = vol.Schema(
                {
                    vol.Required(CONF_DONG): SelectSelector(
                        SelectSelectorConfig(
                            options=dong_options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            )

        return self.async_show_form(
            step_id="dong",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "apartment_name": self._selected_apartment.get("name", ""),
            },
        )

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle credentials and unit number input."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]
            ho = user_input[CONF_HO]

            # Validate connection
            session = async_get_clientsession(self.hass)
            
            api = DaelimSmartHomeAPI(
                session=session,
                host=self._host,
                username=self._username,
                password=self._password,
                apart_id=self._apart_id,
                dong=self._dong,
                ho=ho,
            )

            try:
                if await api.authenticate():
                    # Create unique ID based on apartment info
                    unique_id = f"{self._apart_id}_{self._dong}_{ho}"
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()
                    
                    # Create display name
                    display_name = (
                        api.danji_display_name 
                        or self._selected_apartment.get("name") 
                        or "e편한세상"
                    )
                    title = f"{display_name} {self._dong}동 {ho}호"

                    return self.async_create_entry(
                        title=title,
                        data={
                            CONF_HOST: self._host,
                            CONF_USERNAME: self._username,
                            CONF_PASSWORD: self._password,
                            CONF_APART_ID: self._apart_id,
                            CONF_DONG: self._dong,
                            CONF_HO: ho,
                        },
                    )
                else:
                    errors["base"] = "invalid_auth"
            except data_entry_flow.AbortFlow:
                # Re-raise abort flows (like already_configured)
                raise
            except Exception as ex:
                _LOGGER.exception("Unexpected exception: %s", ex)
                errors["base"] = "cannot_connect"

        data_schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_HO): str,
            }
        )

        return self.async_show_form(
            step_id="credentials",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "apartment_name": self._selected_apartment.get("name", ""),
                "dong": self._dong,
            },
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual entry fallback when apartment list cannot be fetched."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate connection
            session = async_get_clientsession(self.hass)
            
            api = DaelimSmartHomeAPI(
                session=session,
                host=user_input[CONF_HOST],
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                apart_id=user_input[CONF_APART_ID],
                dong=user_input[CONF_DONG],
                ho=user_input[CONF_HO],
            )

            try:
                if await api.authenticate():
                    # Create unique ID based on apartment info
                    unique_id = f"{user_input[CONF_APART_ID]}_{user_input[CONF_DONG]}_{user_input[CONF_HO]}"
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()
                    
                    # Create display name
                    display_name = api.danji_display_name or "e편한세상"
                    title = f"{display_name} {user_input[CONF_DONG]}동 {user_input[CONF_HO]}호"

                    return self.async_create_entry(
                        title=title,
                        data=user_input,
                    )
                else:
                    errors["base"] = "invalid_auth"
            except data_entry_flow.AbortFlow:
                # Re-raise abort flows (like already_configured)
                raise
            except Exception as ex:
                _LOGGER.exception("Unexpected exception: %s", ex)
                errors["base"] = "cannot_connect"

        # Manual entry schema - all fields required
        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_APART_ID): str,
                vol.Required(CONF_DONG): str,
                vol.Required(CONF_HO): str,
            }
        )

        return self.async_show_form(
            step_id="manual",
            data_schema=data_schema,
            errors=errors,
        )


class DaelimSmartHomeOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Daelim Smart Home."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial options step."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["device_config"],
        )

    async def async_step_device_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual device configuration.
        
        This allows users to enter device configuration JSON when the 
        protocol connection to the apartment server fails.
        """
        errors: dict[str, str] = {}

        # Get existing control_info from config entry
        existing_config = self._config_entry.data.get(CONF_CONTROL_INFO, {})
        
        if user_input is not None:
            control_info_str = user_input.get("control_info", "").strip()
            
            if control_info_str:
                try:
                    control_info = json.loads(control_info_str)
                    
                    # Validate structure
                    valid_keys = {"light", "heating", "gas", "fan", "wallsocket"}
                    if not any(key in control_info for key in valid_keys):
                        errors["control_info"] = "invalid_device_config"
                    else:
                        # Update config entry data with new control_info
                        new_data = {**self._config_entry.data, CONF_CONTROL_INFO: control_info}
                        self.hass.config_entries.async_update_entry(
                            self._config_entry,
                            data=new_data
                        )
                        _LOGGER.info("Updated device configuration")
                        
                        return self.async_create_entry(
                            title="",
                            data={}
                        )
                except json.JSONDecodeError:
                    errors["control_info"] = "invalid_json"
            else:
                # Empty input clears the config
                if CONF_CONTROL_INFO in self._config_entry.data:
                    new_data = {k: v for k, v in self._config_entry.data.items() if k != CONF_CONTROL_INFO}
                    self.hass.config_entries.async_update_entry(
                        self._config_entry,
                        data=new_data
                    )
                return self.async_create_entry(title="", data={})

        # Format existing config as JSON for display
        if existing_config:
            default_value = json.dumps(existing_config, indent=2, ensure_ascii=False)
        else:
            default_value = ""

        data_schema = vol.Schema(
            {
                vol.Optional("control_info", default=default_value): TextSelector(
                    TextSelectorConfig(
                        type=TextSelectorType.TEXT,
                        multiline=True,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="device_config",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "example_config": EXAMPLE_CONTROL_INFO,
            },
        )


# Example control_info for documentation
EXAMPLE_CONTROL_INFO = '''
{
  "light": [
    {"uid": "012611", "dimming": "y", "uname": "거실"},
    {"uid": "012511", "dimming": "n", "uname": "복도"}
  ],
  "gas": [{"uid": "012711", "uname": "주방"}],
  "heating": [
    {"uid": "012411", "uname": "거실"},
    {"uid": "012412", "uname": "침실1"}
  ],
  "wallsocket": [
    {"uid": "013111", "uname": "거실1"},
    {"uid": "013121", "uname": "거실2"}
  ]
}
'''
