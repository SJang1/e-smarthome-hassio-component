"""API Client for Daelim Smart Home.

IMPORTANT ARCHITECTURE NOTES:
============================
The Daelim Smart Home (e편한세상) system uses a hybrid architecture:

1. HTTP REST API (smarthome.daelim.co.kr):
   - Authentication (loginProc.do)
   - Apartment info (selectApartInfoCheck.do, choice_1.do)
   - Menu configuration (getApartMenuInfo.do)
   - Logging/analytics (sendLog.do)

2. TCP to apartment server (ipAddress from apartment info):
   - Actual device control (lights, heating, gas, fan, etc.)
   - Guard mode control
   - Elevator call
   - Uses proprietary binary protocol over TCP port 25301
   - Binary header (28 bytes) + JSON payload
   - The IP is a PUBLIC IP (e.g., 210.219.229.70) accessible from anywhere

BINARY PROTOCOL FORMAT:
======================
  [0-3]   Length (big-endian uint32) - length of data after first 4 bytes
  [4-11]  LoginPin (8 bytes ASCII, padded)
  [12-15] Type (big-endian uint32) - 1=Login, 2=Security, 3=Device
  [16-19] Subtype (big-endian uint32) - operation subtype
  [20-23] Direction (4 bytes) - 0x00,0x01,0x00,0x03 for request
  [24-27] Reserved (big-endian uint32) - 0 for request, error code for response
  [28+]   JSON payload

AUTHENTICATION FLOW:
===================
1. CertPin request (pin=00000000, subtype=5) -> get certpin
2. LoginPin request (pin=certpin, subtype=9) -> get loginpin
3. Menu request (pin=loginpin, subtype=7) -> get device list
4. Device control (pin=loginpin, subtype=1)

APARTMENT DISCOVERY:
===================
The /main/choice_1.do page contains a complete JavaScript array with all
apartment information embedded in the HTML. This includes:
- apartId, name (display name), danjiDirectoryName
- ip (server IP for TCP control)
- danjiDongInfo (available building/dong numbers)
- Location data, weather info, etc.

This allows us to:
1. Fetch all apartments and let users select from a dropdown
2. Auto-populate available dong numbers
3. Avoid requiring manual apartment ID input

This API client handles the HTTP parts and uses DaelimProtocolClient
for device control when the internal IP is available.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid as uuid_module
from typing import Any

import aiohttp

from .const import (
    TYPE_DEVICE,
    DEVICE_LIGHT,
    DEVICE_HEATING,
    DEVICE_GAS,
    DEVICE_FAN,
    DEVICE_WALLSOCKET,
    STATE_OFF,
    GUARD_MODE_OFF,
)
from .daelim_protocol import (
    DaelimProtocolClient,
    ERROR_SUCCESS,
    MESSAGE_ERR,
    GUARD_MODE_ON,
)

_LOGGER = logging.getLogger(__name__)


async def fetch_apartment_list(
    session: aiohttp.ClientSession,
    host: str = "smarthome.daelim.co.kr",
) -> list[dict[str, Any]]:
    """Fetch the list of all apartments from the choice page.
    
    Parses the JavaScript 'region' array embedded in /main/choice_1.do.
    
    Returns:
        List of apartment dictionaries with keys like:
        - apartId, name, danjiDirectoryName, ip, danjiDongInfo
        - status (LIVE/DEV), danjiArea, etc.
    """
    url = f"https://{host}/main/choice_1.do"
    apartments = []
    
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        
        async with session.get(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            if response.status != 200:
                _LOGGER.error("Failed to fetch apartment list: HTTP %s", response.status)
                return apartments
            
            html = await response.text()
            
            # Parse each region.push({...}) block
            # Pattern to match region.push({ ... }) blocks
            pattern = r'region\.push\(\{([^}]+)\}\)'
            matches = re.findall(pattern, html, re.DOTALL)
            
            for match in matches:
                apt = {}
                # Parse each key-value pair
                # Handle both quoted and unquoted values
                kv_pattern = r'(\w+)\s*:\s*(?:"([^"]*)"|\'([^\']*)\'|([^,\n]+))'
                for kv_match in re.finditer(kv_pattern, match):
                    key = kv_match.group(1)
                    # Value is in group 2 (double quoted), 3 (single quoted), or 4 (unquoted)
                    value = kv_match.group(2) or kv_match.group(3) or kv_match.group(4)
                    if value:
                        value = value.strip().strip('"').strip("'")
                        apt[key] = value
                
                if apt.get("apartId") and apt.get("name"):
                    apartments.append(apt)
            
            # Filter to only LIVE apartments by default
            live_apartments = [a for a in apartments if a.get("status") == "LIVE"]
            
            _LOGGER.info(
                "Fetched %d apartments (%d LIVE)",
                len(apartments),
                len(live_apartments)
            )
            
            return live_apartments
            
    except asyncio.TimeoutError:
        _LOGGER.error("Timeout fetching apartment list")
        return apartments
    except Exception as ex:
        _LOGGER.error("Error fetching apartment list: %s", ex)
        return apartments


def get_dong_list(danji_dong_info: str) -> list[str]:
    """Parse danjiDongInfo string into list of dong numbers.
    
    Args:
        danji_dong_info: Comma-separated string like "101,102,103,104"
        
    Returns:
        List of dong numbers as strings
    """
    if not danji_dong_info:
        return []
    return [d.strip() for d in danji_dong_info.split(",") if d.strip()]


class DaelimSmartHomeAPI:
    """API Client for Daelim Smart Home e편한세상."""

    # Default port for apartment server
    DEFAULT_PORT = 25301

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
        apart_id: str,
        dong: str,
        ho: str,
        device_uuid: str | None = None,
    ) -> None:
        """Initialize the API client.
        
        All apartment info (danji_name, server IP) is auto-discovered from apartId.
        
        Args:
            session: aiohttp client session
            host: API host (smarthome.daelim.co.kr)
            username: Daelim account username
            password: Daelim account password
            apart_id: Apartment ID
            dong: Building number (dong)
            ho: Unit number (ho)
            device_uuid: Optional device UUID for protocol auth (auto-generated if not provided)
        """
        self._session = session
        self._host = host
        self._username = username
        self._password = password
        self._apart_id = apart_id
        self._dong = dong
        self._ho = ho
        self._danji_name: str | None = None  # Auto-discovered
        self._danji_display_name: str | None = None
        self._ip_address: str | None = None  # Auto-discovered from selectApartInfoCheck.do
        
        # Device UUID for protocol authentication
        # Generate a unique UUID if not provided (stored persistently in config entry)
        self._device_uuid = device_uuid or uuid_module.uuid4().hex.upper()
        
        self._base_url = f"https://{host}"
        self._jsession_id: str | None = None
        self._session_id: str | None = None
        
        # Saved pins for protocol session resumption
        self._cert_pin: str | None = None
        self._login_pin: str | None = None
        
        # Protocol client for device control
        self._protocol_client: DaelimProtocolClient | None = None
        
        # User-Agent to mimic mobile app
        self._user_agent = (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
        )
        
        # Device configuration from UI list
        self._lights: list[dict] = []
        self._heating: list[dict] = []
        self._gas: list[dict] = []
        self._fan: list[dict] = []
        self._wallsocket: list[dict] = []
        
        # Current device states
        self._device_states: dict[str, dict] = {}
        self._guard_mode: str = GUARD_MODE_OFF
        self._available_menus: list[dict] = []
    
    @property
    def device_uuid(self) -> str:
        """Return device UUID for protocol authentication."""
        return self._device_uuid

    @property
    def danji_name(self) -> str | None:
        """Return the danji directory name."""
        return self._danji_name
    
    @property
    def danji_display_name(self) -> str | None:
        """Return the danji display name (Korean)."""
        return self._danji_display_name

    @property
    def lights(self) -> list[dict]:
        """Return list of light devices."""
        return self._lights

    @property
    def heating(self) -> list[dict]:
        """Return list of heating devices."""
        return self._heating

    @property
    def gas(self) -> list[dict]:
        """Return list of gas valve devices."""
        return self._gas

    @property
    def fan(self) -> list[dict]:
        """Return list of fan/ventilation devices."""
        return self._fan

    @property
    def wallsocket(self) -> list[dict]:
        """Return list of standby power outlet devices."""
        return self._wallsocket

    @property
    def device_states(self) -> dict[str, dict]:
        """Return current device states."""
        return self._device_states

    @property
    def guard_mode(self) -> str:
        """Return current guard/security mode."""
        return self._guard_mode
    
    @property
    def available_menus(self) -> list[dict]:
        """Return available menu items."""
        return self._available_menus
    
    @property
    def protocol_connected(self) -> bool:
        """Return True if protocol client is connected."""
        return self._protocol_client is not None and self._protocol_client.connected
    
    @property
    def internal_ip(self) -> str | None:
        """Return internal IP address."""
        return self._ip_address

    async def connect_protocol(self) -> bool:
        """Connect to apartment server via protocol client.
        
        Uses the proprietary binary protocol discovered from Wireshark analysis.
        Authentication flow: CertPin -> LoginPin -> Menu
        
        If a saved login_pin exists, tries to reuse it first.
        If expired, performs fresh login automatically.
        
        Returns:
            True if connected and logged in successfully
        """
        if not self._ip_address:
            _LOGGER.warning("Cannot connect protocol client: no server IP discovered")
            return False
        
        try:
            if self._protocol_client:
                await self._protocol_client.disconnect()
            
            self._protocol_client = DaelimProtocolClient(
                host=self._ip_address,
                port=self.DEFAULT_PORT,
            )
            
            # Set saved pins for session resumption
            if self._cert_pin or self._login_pin:
                _LOGGER.info("Setting saved pins for session resumption (cert=%s, login=%s)",
                            self._cert_pin, self._login_pin)
                self._protocol_client.set_saved_pins(self._cert_pin, self._login_pin)
            
            # Connect and login with UUID
            login_response = await self._protocol_client.login(
                self._username,
                self._password,
                uuid=self._device_uuid
            )
            
            if login_response.get("error", 0) != ERROR_SUCCESS:
                error = login_response.get("error", -1)
                _LOGGER.error(
                    "Protocol login failed: %s",
                    MESSAGE_ERR.get(error, f"Error {error}")
                )
                return False
            
            # Save both pins for future reconnections
            self._cert_pin = self._protocol_client.saved_cert_pin
            self._login_pin = self._protocol_client.saved_login_pin
            _LOGGER.debug("Saved pins after login: cert=%s, login=%s", 
                         self._cert_pin, self._login_pin)
            
            # Parse control info from login response
            control_info = self._protocol_client.control_info
            if control_info:
                self.parse_control_info(control_info)
            
            _LOGGER.info(
                "Protocol client connected to %s:%s",
                self._ip_address, self.DEFAULT_PORT
            )
            return True
            
        except Exception as ex:
            _LOGGER.error("Protocol connection failed: %s", ex)
            if self._protocol_client:
                await self._protocol_client.disconnect()
                self._protocol_client = None
            return False
    
    @property
    def saved_cert_pin(self) -> str | None:
        """Return saved cert pin for persistence."""
        return self._cert_pin
    
    @property
    def saved_login_pin(self) -> str | None:
        """Return saved login pin for persistence."""
        return self._login_pin
    
    def set_saved_pins(self, cert_pin: str | None, login_pin: str | None) -> None:
        """Set saved pins from persistent storage."""
        self._cert_pin = cert_pin
        self._login_pin = login_pin

    async def disconnect_protocol(self) -> None:
        """Disconnect protocol client."""
        if self._protocol_client:
            await self._protocol_client.disconnect()
            self._protocol_client = None

    async def ensure_protocol_connected(self) -> bool:
        """Ensure protocol client is connected, reconnecting if necessary.
        
        Returns:
            True if connected (or reconnected successfully)
        """
        if self._protocol_client and self._protocol_client.connected and self._protocol_client.logged_in:
            return True
        
        _LOGGER.info("Protocol client not connected/logged in, attempting to reconnect...")
        return await self.connect_protocol()

    async def get_initial_session(self) -> bool:
        """Get initial JSESSIONID by visiting intro page."""
        try:
            intro_url = f"{self._base_url}/main/intro.do"
            _LOGGER.debug("Getting initial session from %s", intro_url)
            
            headers = {
                "User-Agent": self._user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9",
            }
            
            async with self._session.get(
                intro_url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                _LOGGER.debug("Intro page response status: %s", response.status)
                if response.status == 200:
                    # Extract JSESSIONID from cookies
                    self._extract_jsession_from_response(response)
                    
                    # Also check session's cookie jar
                    if not self._jsession_id:
                        for cookie in self._session.cookie_jar:
                            if cookie.key == "JSESSIONID":
                                self._jsession_id = cookie.value
                                _LOGGER.debug("Got JSESSIONID from cookie jar")
                                break
                    
                    if self._jsession_id:
                        _LOGGER.debug("Got initial JSESSIONID: %s...", self._jsession_id[:8])
                        return True
                    else:
                        _LOGGER.warning("No JSESSIONID found in intro response")
            return False
        except Exception as ex:
            _LOGGER.error("Error getting initial session: %s", ex)
            return False

    async def get_apart_info(self) -> bool:
        """Get apartment info including danjiDirectoryName and ipAddress from apartId.
        
        The ipAddress returned is typically a PUBLIC IP that can be accessed
        from anywhere, not just from within the apartment network.
        """
        try:
            response = await self._api_request(
                "POST",
                "/json/selectApartInfoCheck.do",
                data={"apartId": self._apart_id},
            )
            
            if response and "item" in response and len(response["item"]) > 0:
                apart_info = response["item"][0]
                self._danji_name = apart_info.get("danjiDirectoryName")
                self._danji_display_name = apart_info.get("danjiName")
                
                # Only update IP if not manually configured
                if not self._ip_address:
                    self._ip_address = apart_info.get("ipAddress")
                    _LOGGER.info(
                        "Auto-discovered server IP: %s",
                        self._ip_address
                    )
                
                _LOGGER.info(
                    "Got apartment info: %s (%s) - Server: %s",
                    self._danji_display_name,
                    self._danji_name,
                    self._ip_address,
                )
                return True
            
            _LOGGER.error("No apartment info found for apartId: %s", self._apart_id)
            return False
            
        except Exception as ex:
            _LOGGER.error("Error getting apartment info: %s", ex)
            return False

    async def authenticate(self) -> bool:
        """Authenticate with the Daelim Smart Home server.
        
        Authentication flow based on HAR capture:
        1. GET /main/intro.do to get initial JSESSIONID
        2. POST /json/selectApartInfoCheck.do to get danjiDirectoryName
        3. POST /{danji_name}/main/loginProc.do with user_id, danji_name, dong, ho
        4. Server returns 302 redirect with new JSESSIONID cookie
        5. Use JSESSIONID for all subsequent API calls
        """
        try:
            # Step 1: Get initial session
            if not await self.get_initial_session():
                _LOGGER.warning("Could not get initial session, continuing anyway")
            
            # Step 2: Get apartment info (including danji_name) if not provided
            if not self._danji_name:
                if not await self.get_apart_info():
                    _LOGGER.error("Could not get apartment info")
                    return False
            
            if not self._danji_name:
                _LOGGER.error("No danji_name available for authentication")
                return False
            
            # Step 3: HTTP POST login to get new JSESSIONID
            login_url = f"{self._base_url}/{self._danji_name}/main/loginProc.do"
            
            login_data = {
                "user_id": self._username,
                "danji_name": self._danji_name,
                "dong": self._dong,
                "ho": self._ho,
            }
            
            _LOGGER.debug("Authenticating to %s with dong=%s, ho=%s", 
                         login_url, self._dong, self._ho)
            
            # Build headers with session cookie if available
            headers = {}
            if self._jsession_id:
                headers["Cookie"] = f"JSESSIONID={self._jsession_id}"
            
            async with self._session.post(
                login_url,
                data=login_data,
                headers=headers if headers else None,
                allow_redirects=False,  # Don't follow redirect, we need the cookies
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                _LOGGER.debug("Login response status: %s", response.status)
                
                # Check for 302 redirect (successful login)
                if response.status == 302:
                    # Extract new JSESSIONID from Set-Cookie header
                    self._extract_jsession_from_response(response)
                    
                    if self._jsession_id:
                        _LOGGER.info(
                            "Successfully authenticated with Daelim Smart Home"
                        )
                        return True
                    else:
                        _LOGGER.warning("302 redirect but no JSESSIONID cookie")
                        # Still might be authenticated if cookie jar has it
                        return True
                        
                elif response.status == 200:
                    # Some servers might return 200 with cookies
                    self._extract_jsession_from_response(response)
                    if self._jsession_id:
                        _LOGGER.info("Successfully authenticated (200 response)")
                        return True
                
                _LOGGER.error("Login failed with status: %s", response.status)
                return False
            
        except Exception as ex:
            _LOGGER.error("Authentication error: %s", ex)
            return False
    
    def _extract_jsession_from_response(self, response: aiohttp.ClientResponse) -> None:
        """Extract JSESSIONID from response headers or cookies."""
        # Try Set-Cookie header first
        if "Set-Cookie" in response.headers:
            cookie_header = response.headers.get("Set-Cookie", "")
            if "JSESSIONID=" in cookie_header:
                for part in cookie_header.split(";"):
                    part = part.strip()
                    if part.startswith("JSESSIONID="):
                        self._jsession_id = part.split("=", 1)[1]
                        _LOGGER.debug("Got JSESSIONID from Set-Cookie header")
                        return
        
        # Also check response cookies object
        for cookie in response.cookies.values():
            if cookie.key == "JSESSIONID":
                self._jsession_id = cookie.value
                _LOGGER.debug("Got JSESSIONID from response cookies")
                return

    def parse_control_info(self, control_info: dict) -> None:
        """Parse controlinfo structure from login response.
        
        The controlinfo is obtained during the WebSocket login process and contains
        all device UIDs and names. If you can capture this from the mobile app
        (e.g., via HAR capture of sendLog.do with type=1, subtype=8),
        you can provide it to configure the devices.
        
        Example control_info structure:
        {
            "light": [
                {"uid": "012611", "dimming": "y", "uname": "거실"},
                {"uid": "012511", "dimming": "n", "uname": "복도"},
            ],
            "gas": [{"uid": "012711", "uname": "주방"}],
            "heating": [
                {"uid": "012411", "uname": "거실"},
                {"uid": "012412", "uname": "침실1"},
            ],
            "wallsocket": [
                {"uid": "013111", "uname": "거실1"},
            ]
        }
        """
        if not control_info:
            return
        
        if "light" in control_info:
            self._lights = [
                {
                    "uid": d.get("uid"),
                    "name": d.get("uname", d.get("name", "조명")),
                    "dimming": d.get("dimming", "n"),
                }
                for d in control_info["light"]
            ]
            _LOGGER.info("Parsed %d light devices", len(self._lights))
        
        if "heating" in control_info:
            self._heating = [
                {
                    "uid": d.get("uid"),
                    "name": d.get("uname", d.get("name", "난방")),
                }
                for d in control_info["heating"]
            ]
            _LOGGER.info("Parsed %d heating devices", len(self._heating))
        
        if "gas" in control_info:
            self._gas = [
                {
                    "uid": d.get("uid"),
                    "name": d.get("uname", d.get("name", "가스")),
                }
                for d in control_info["gas"]
            ]
            _LOGGER.info("Parsed %d gas devices", len(self._gas))
        
        if "fan" in control_info:
            self._fan = [
                {
                    "uid": d.get("uid"),
                    "name": d.get("uname", d.get("name", "환기")),
                }
                for d in control_info["fan"]
            ]
            _LOGGER.info("Parsed %d fan devices", len(self._fan))
        
        if "wallsocket" in control_info:
            self._wallsocket = [
                {
                    "uid": d.get("uid"),
                    "name": d.get("uname", d.get("name", "콘센트")),
                }
                for d in control_info["wallsocket"]
            ]
            _LOGGER.info("Parsed %d wallsocket devices", len(self._wallsocket))

    def set_devices_from_stored_config(self, control_info: dict) -> bool:
        """Set devices from stored configuration when protocol connection fails.
        
        This allows the integration to still create entities when the TCP protocol
        cannot connect to the apartment server. The control_info should have been
        captured from a previous successful connection or from HAR capture.
        
        Args:
            control_info: Device configuration dict with keys like 'light', 'heating', etc.
            
        Returns:
            True if any devices were configured, False otherwise.
        """
        if not control_info:
            _LOGGER.debug("No stored control_info provided")
            return False
        
        # Clear existing device lists
        self._lights = []
        self._heating = []
        self._gas = []
        self._fan = []
        self._wallsocket = []
        
        # Parse the stored config
        self.parse_control_info(control_info)
        
        total_devices = (
            len(self._lights) + len(self._heating) + len(self._gas) +
            len(self._fan) + len(self._wallsocket)
        )
        
        if total_devices > 0:
            _LOGGER.info(
                "Loaded %d devices from stored configuration "
                "(lights=%d, heating=%d, gas=%d, fan=%d, wallsocket=%d)",
                total_devices, len(self._lights), len(self._heating),
                len(self._gas), len(self._fan), len(self._wallsocket)
            )
            return True
        
        return False

    def get_control_info_for_storage(self) -> dict:
        """Get current device configuration for storage in config entry.
        
        Returns a dict that can be stored in entry.data[CONF_CONTROL_INFO]
        and later used with set_devices_from_stored_config().
        """
        control_info = {}
        
        if self._lights:
            control_info["light"] = [
                {"uid": d["uid"], "uname": d["name"], "dimming": d.get("dimming", "n")}
                for d in self._lights
            ]
        
        if self._heating:
            control_info["heating"] = [
                {"uid": d["uid"], "uname": d["name"]}
                for d in self._heating
            ]
        
        if self._gas:
            control_info["gas"] = [
                {"uid": d["uid"], "uname": d["name"]}
                for d in self._gas
            ]
        
        if self._fan:
            control_info["fan"] = [
                {"uid": d["uid"], "uname": d["name"]}
                for d in self._fan
            ]
        
        if self._wallsocket:
            control_info["wallsocket"] = [
                {"uid": d["uid"], "uname": d["name"]}
                for d in self._wallsocket
            ]
        
        return control_info

    async def get_ui_list_info(self) -> dict[str, Any]:
        """Get UI list info containing device configuration from menus.
        
        Note: This only detects which control menus are available.
        Actual devices are discovered from the protocol login controlinfo.
        If protocol connection fails, no devices will be created.
        """
        try:
            # Get the apartment menu info to determine available features
            menu_response = await self._api_request(
                "POST",
                "/json/getApartMenuInfo.do",
                data={
                    "apartId": self._apart_id,
                    "searchMenuGubun": "mobile",
                },
            )
            
            if menu_response and "item" in menu_response:
                self._available_menus = [
                    menu for menu in menu_response["item"]
                    if menu.get("useYn") == "Y"
                ]
                _LOGGER.info("Got %d available menus", len(self._available_menus))
                
                # Log which control features are available based on menus
                # (but don't create placeholder devices - actual devices come from protocol)
                for menu in self._available_menus:
                    menu_url = menu.get("menuUrl", "")
                    menu_name = menu.get("menuName", "")
                    
                    if "control_1" in menu_url or "조명" in menu_name:
                        _LOGGER.debug("Menu indicates lighting control available")
                    elif "control_2" in menu_url or "난방" in menu_name:
                        _LOGGER.debug("Menu indicates heating control available")
                    elif "control_4" in menu_url or "가스" in menu_name:
                        _LOGGER.debug("Menu indicates gas control available")
                    elif "control_3" in menu_url or "환기" in menu_name:
                        _LOGGER.debug("Menu indicates ventilation control available")
                    elif "control_6" in menu_url or "대기전력" in menu_name:
                        _LOGGER.debug("Menu indicates standby power control available")
                
                # Log device counts after menu parsing
                _LOGGER.info(
                    "Device counts from protocol: lights=%d, heating=%d, gas=%d, fan=%d, wallsocket=%d",
                    len(self._lights), len(self._heating), len(self._gas),
                    len(self._fan), len(self._wallsocket)
                )
            
            return {"menus": self._available_menus}
            
        except Exception as ex:
            _LOGGER.error("Error getting UI list info: %s", ex)
            return {}

    async def query_all_devices(self) -> dict[str, dict]:
        """Query all device states in a single batch request.
        
        This is much more efficient than querying each device type separately.
        Takes about 10 seconds for all devices instead of 20+ seconds sequentially.
        """
        if not self._protocol_client or not self._protocol_client.connected:
            _LOGGER.debug("Protocol client not connected for batch query, attempting to connect...")
            if not await self.connect_protocol():
                _LOGGER.warning("Cannot query devices - failed to connect")
                return self._device_states
        
        try:
            _LOGGER.debug("Querying ALL devices in single batch request...")
            
            # Use the batch query method (15s timeout for all devices)
            response = await self._protocol_client.query_all_devices(timeout=15.0)
            
            if response.get("error", 0) == ERROR_SUCCESS:
                body = response.get("body", {})
                items = body.get("item", [])
                
                # Count by device type for logging
                type_counts = {}
                
                for item in items:
                    device = item.get("device", "unknown")
                    uid = item.get("uid", "")
                    key = f"{device}_{uid}"
                    self._device_states[key] = item
                    
                    # Count for logging
                    type_counts[device] = type_counts.get(device, 0) + 1
                
                _LOGGER.info(
                    "Batch query complete: %d devices (%s)",
                    len(items),
                    ", ".join(f"{k}={v}" for k, v in type_counts.items())
                )
            else:
                error = response.get("error", -1)
                _LOGGER.warning(
                    "Batch device query failed: %s",
                    MESSAGE_ERR.get(error, f"Error {error}")
                )
            
            # Query guard mode separately (not included in device batch)
            await self._query_guard_mode_safe()
            
            return self._device_states
            
        except Exception as ex:
            _LOGGER.error("Error in batch device query: %s", ex)
            return self._device_states

    async def _ensure_protocol_for_query(self) -> bool:
        """Ensure protocol is connected for a device query, reconnecting if needed."""
        if self._protocol_client and self._protocol_client.connected:
            return True
        
        _LOGGER.debug("Protocol disconnected, reconnecting for query...")
        return await self.connect_protocol()

    async def _query_guard_mode_safe(self) -> None:
        """Query guard mode with auto-reconnection."""
        if not await self._ensure_protocol_for_query():
            _LOGGER.warning("Cannot query guard mode - failed to connect")
            return
        
        await self._query_guard_mode()

    async def _query_device_type(self, device_type: str, timeout: float = 10.0) -> None:
        """Query devices of a specific type.
        
        Uses protocol client if connected, otherwise logs warning.
        
        Args:
            device_type: Type of device to query
            timeout: Request timeout in seconds (default 10s)
        """
        if not self._protocol_client or not self._protocol_client.connected:
            _LOGGER.debug(
                "Device query for %s - protocol client not connected (internal IP: %s)",
                device_type,
                self._ip_address or "unknown"
            )
            return
        
        try:
            response = await self._protocol_client.query_devices(device_type, timeout=timeout)
            if response.get("error", 0) == ERROR_SUCCESS:
                body = response.get("body", {})
                items = body.get("item", [])
                for item in items:
                    device = item.get("device", device_type)
                    uid = item.get("uid", "")
                    key = f"{device}_{uid}"
                    self._device_states[key] = item
                    _LOGGER.debug("Updated state for %s: %s", key, item)
            else:
                error = response.get("error", -1)
                _LOGGER.warning(
                    "Device query failed for %s: %s",
                    device_type, MESSAGE_ERR.get(error, f"Error {error}")
                )
        except Exception as ex:
            _LOGGER.error("Error querying %s devices: %s", device_type, ex)

    async def _query_guard_mode(self) -> None:
        """Query security/guard mode.
        
        Uses protocol client if connected.
        """
        if not self._protocol_client or not self._protocol_client.connected:
            _LOGGER.debug("Guard mode query - protocol client not connected")
            return
        
        try:
            response = await self._protocol_client.query_guard_mode()
            if response.get("error", 0) == ERROR_SUCCESS:
                body = response.get("body", {})
                mode = body.get("mode", GUARD_MODE_OFF)
                self._guard_mode = mode
                _LOGGER.debug("Guard mode: %s", mode)
            else:
                error = response.get("error", -1)
                _LOGGER.warning(
                    "Guard mode query failed: %s",
                    MESSAGE_ERR.get(error, f"Error {error}")
                )
        except Exception as ex:
            _LOGGER.error("Error querying guard mode: %s", ex)

    def _update_device_state_from_response(self, response: dict) -> None:
        """Update device state immediately from control response.
        
        The response contains the new device state, so we can update
        the cached state without waiting for the next polling cycle.
        """
        body = response.get("body", {})
        items = body.get("item", [])
        
        for item in items:
            device = item.get("device", "")
            uid = item.get("uid", "")
            if device and uid:
                key = f"{device}_{uid}"
                self._device_states[key] = item
                _LOGGER.debug("Immediate state update for %s: %s", key, item)

    async def set_light(self, uid: str, state: str, brightness: int | None = None) -> bool:
        """Set light state."""
        # Ensure protocol is connected before attempting control
        if not await self.ensure_protocol_connected():
            _LOGGER.error("Cannot control light: protocol client not connected")
            return False
        
        try:
            # Convert 0-255 to dimming levels 1, 3, 6 (Daelim dimming values)
            dim_level = None
            if brightness is not None:
                # Map: 0-85 -> 1 (low), 86-170 -> 3 (medium), 171-255 -> 6 (high)
                if brightness <= 85:
                    dim_level = 1
                elif brightness <= 170:
                    dim_level = 3
                else:
                    dim_level = 6
            
            response = await self._protocol_client.set_light(uid, state, dim_level)
            error = response.get("error", -1)
            
            # If connection error, explicitly disconnect, then reconnect and retry once
            if error == -1:
                _LOGGER.warning("Light control connection error, reconnecting and retrying...")
                await self.disconnect_protocol()
                if await self.connect_protocol():
                    response = await self._protocol_client.set_light(uid, state, dim_level)
                    error = response.get("error", -1)
            
            if error == ERROR_SUCCESS:
                # Update state immediately from response
                self._update_device_state_from_response(response)
                _LOGGER.debug("Light %s set to %s", uid, state)
                return True
            else:
                _LOGGER.error(
                    "Light control failed: %s",
                    MESSAGE_ERR.get(error, f"Error {error}")
                )
                return False
        except Exception as ex:
            _LOGGER.error("Error setting light: %s", ex)
            return False

    async def set_light_all(self, state: str) -> bool:
        """Set all lights state."""
        if not await self.ensure_protocol_connected():
            _LOGGER.error("Cannot control lights: protocol client not connected")
            return False
        
        try:
            response = await self._protocol_client.set_light("all", state)
            if response.get("error", 0) == ERROR_SUCCESS:
                # Update all light states immediately from response
                self._update_device_state_from_response(response)
                _LOGGER.debug("All lights set to %s", state)
                return True
            else:
                error = response.get("error", -1)
                _LOGGER.error(
                    "All lights control failed: %s",
                    MESSAGE_ERR.get(error, f"Error {error}")
                )
                return False
        except Exception as ex:
            _LOGGER.error("Error setting all lights: %s", ex)
            return False

    async def set_heating(
        self, 
        uid: str, 
        state: str, 
        temperature: float | None = None
    ) -> bool:
        """Set heating state and temperature."""
        if not await self.ensure_protocol_connected():
            _LOGGER.error("Cannot control heating: protocol client not connected")
            return False
        
        try:
            temp = int(temperature) if temperature is not None else None
            response = await self._protocol_client.set_heating(uid, state, temp)
            if response.get("error", 0) == ERROR_SUCCESS:
                # Update state immediately from response
                self._update_device_state_from_response(response)
                _LOGGER.debug("Heating %s set to %s (temp=%s)", uid, state, temp)
                return True
            else:
                error = response.get("error", -1)
                _LOGGER.error(
                    "Heating control failed: %s",
                    MESSAGE_ERR.get(error, f"Error {error}")
                )
                return False
        except Exception as ex:
            _LOGGER.error("Error setting heating: %s", ex)
            return False

    async def set_gas(self, uid: str, state: str) -> bool:
        """Set gas valve state (only 'off' is typically allowed for safety)."""
        if not await self.ensure_protocol_connected():
            _LOGGER.error("Cannot control gas: protocol client not connected")
            return False
        
        try:
            response = await self._protocol_client.set_gas(uid, state)
            if response.get("error", 0) == ERROR_SUCCESS:
                # Update state immediately from response
                self._update_device_state_from_response(response)
                _LOGGER.debug("Gas %s set to %s", uid, state)
                return True
            else:
                error = response.get("error", -1)
                _LOGGER.error(
                    "Gas control failed: %s",
                    MESSAGE_ERR.get(error, f"Error {error}")
                )
                return False
        except Exception as ex:
            _LOGGER.error("Error setting gas: %s", ex)
            return False

    async def set_fan(
        self, 
        uid: str, 
        state: str, 
        speed: str | None = None,
        mode: str | None = None
    ) -> bool:
        """Set fan/ventilation state."""
        if not await self.ensure_protocol_connected():
            _LOGGER.error("Cannot control fan: protocol client not connected")
            return False
        
        try:
            response = await self._protocol_client.set_fan(uid, state, speed, mode)
            if response.get("error", 0) == ERROR_SUCCESS:
                # Update state immediately from response
                self._update_device_state_from_response(response)
                _LOGGER.debug("Fan %s set to %s (speed=%s, mode=%s)", uid, state, speed, mode)
                return True
            else:
                error = response.get("error", -1)
                _LOGGER.error(
                    "Fan control failed: %s",
                    MESSAGE_ERR.get(error, f"Error {error}")
                )
                return False
        except Exception as ex:
            _LOGGER.error("Error setting fan: %s", ex)
            return False

    async def set_wallsocket(self, uid: str, state: str) -> bool:
        """Set standby power outlet state."""
        if not await self.ensure_protocol_connected():
            _LOGGER.error("Cannot control wallsocket: protocol client not connected")
            return False
        
        try:
            response = await self._protocol_client.set_wallsocket(uid, state)
            if response.get("error", 0) == ERROR_SUCCESS:
                # Update state immediately from response
                self._update_device_state_from_response(response)
                _LOGGER.debug("Wallsocket %s set to %s", uid, state)
                return True
            else:
                error = response.get("error", -1)
                _LOGGER.error(
                    "Wallsocket control failed: %s",
                    MESSAGE_ERR.get(error, f"Error {error}")
                )
                return False
        except Exception as ex:
            _LOGGER.error("Error setting wallsocket: %s", ex)
            return False

    async def set_all_off(self) -> bool:
        """Turn off all devices (일괄차단)."""
        if not await self.ensure_protocol_connected():
            _LOGGER.error("Cannot turn off all: protocol client not connected")
            return False
        
        try:
            response = await self._protocol_client.all_off()
            if response.get("error", 0) == ERROR_SUCCESS:
                _LOGGER.debug("All devices turned off")
                return True
            else:
                error = response.get("error", -1)
                _LOGGER.error(
                    "All-off failed: %s",
                    MESSAGE_ERR.get(error, f"Error {error}")
                )
                return False
        except Exception as ex:
            _LOGGER.error("Error turning off all devices: %s", ex)
            return False

    async def set_guard_mode(self, mode: str, password: str | None = None) -> bool:
        """Set guard/security mode (away mode)."""
        if not await self.ensure_protocol_connected():
            _LOGGER.error("Cannot set guard mode: protocol client not connected")
            return False
        
        try:
            response = await self._protocol_client.set_guard_mode(mode, password)
            if response.get("error", 0) == ERROR_SUCCESS:
                self._guard_mode = mode
                _LOGGER.debug("Guard mode set to %s", mode)
                return True
            else:
                error = response.get("error", -1)
                _LOGGER.error(
                    "Guard mode control failed: %s",
                    MESSAGE_ERR.get(error, f"Error {error}")
                )
                return False
        except Exception as ex:
            _LOGGER.error("Error setting guard mode: %s", ex)
            return False

    async def call_elevator(self) -> bool:
        """Call elevator."""
        if not await self.ensure_protocol_connected():
            _LOGGER.error("Cannot call elevator: protocol client not connected")
            return False
        
        try:
            response = await self._protocol_client.call_elevator()
            if response.get("error", 0) == ERROR_SUCCESS:
                _LOGGER.debug("Elevator called")
                return True
            else:
                error = response.get("error", -1)
                _LOGGER.error(
                    "Elevator call failed: %s",
                    MESSAGE_ERR.get(error, f"Error {error}")
                )
                return False
        except Exception as ex:
            _LOGGER.error("Error calling elevator: %s", ex)
            return False

    async def query_energy(self) -> dict | None:
        """Query current energy usage (alias for query_energy_monthly)."""
        return await self.query_energy_monthly()

    async def query_energy_monthly(
        self,
        year: str | None = None,
        month: str | None = None,
    ) -> dict | None:
        """Query monthly energy usage.
        
        Returns:
            Energy data dict with items for each type (Elec, Gas, Water, etc.)
        """
        # Ensure protocol is connected before querying
        if not await self.ensure_protocol_connected():
            _LOGGER.debug("Cannot query energy: protocol client not connected")
            return None
        
        try:
            response = await self._protocol_client.query_energy_monthly(year, month)
            if response.get("error", 0) == ERROR_SUCCESS:
                return response.get("body", {})
            else:
                error = response.get("error", -1)
                _LOGGER.warning(
                    "Energy query failed: %s",
                    MESSAGE_ERR.get(error, f"Error {error}")
                )
                return None
        except Exception as ex:
            _LOGGER.error("Error querying energy: %s", ex)
            return None

    async def query_energy_year(
        self,
        energy_type: str = "Elec",
        year: str | None = None,
    ) -> dict | None:
        """Query yearly energy graph for a specific energy type.
        
        Returns:
            Energy data dict with monthly breakdown for the year.
        """
        # Ensure protocol is connected before querying
        if not await self.ensure_protocol_connected():
            _LOGGER.debug("Cannot query energy year: protocol client not connected")
            return None
        
        try:
            response = await self._protocol_client.query_energy_year(energy_type, year)
            if response.get("error", 0) == ERROR_SUCCESS:
                return response.get("body", {})
            else:
                error = response.get("error", -1)
                _LOGGER.warning(
                    "Energy year query failed: %s",
                    MESSAGE_ERR.get(error, f"Error {error}")
                )
                return None
        except Exception as ex:
            _LOGGER.error("Error querying energy year: %s", ex)
            return None

    async def query_all_energy_yearly(self) -> dict[str, dict | None]:
        """Query yearly energy data for all energy types.
        
        Returns:
            Dict mapping energy type to yearly data.
        """
        energy_types = ["Elec", "Gas", "Water", "Hotwater", "Heating"]
        results = {}
        for energy_type in energy_types:
            results[energy_type] = await self.query_energy_year(energy_type)
        return results

    async def _api_request(
        self,
        method: str,
        path: str,
        data: dict | None = None,
    ) -> dict | None:
        """Make API request."""
        url = f"{self._base_url}{path}"
        
        # Build headers matching what the mobile app sends
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "*/*",
            "User-Agent": self._user_agent,
            "Accept-Language": "ko-KR,ko;q=0.9",
        }
        if self._jsession_id:
            headers["Cookie"] = f"JSESSIONID={self._jsession_id}"
        
        _LOGGER.debug("API request: %s %s", method, path)
        
        try:
            async with self._session.request(
                method,
                url,
                data=data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                # Check for new JSESSIONID in response
                if "Set-Cookie" in response.headers:
                    cookie_header = response.headers.get("Set-Cookie", "")
                    if "JSESSIONID=" in cookie_header:
                        for part in cookie_header.split(";"):
                            part = part.strip()
                            if part.startswith("JSESSIONID="):
                                self._jsession_id = part.split("=", 1)[1]
                                break
                
                if response.status == 200:
                    text = await response.text()
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        _LOGGER.error("Invalid JSON response: %s", text[:200])
                        return None
                elif response.status == 302:
                    # Redirect often means session expired, try to re-auth
                    _LOGGER.warning("Got redirect, session may have expired")
                    return None
                elif response.status == 404:
                    _LOGGER.error(
                        "API request 404 Not Found: %s (JSESSIONID: %s)",
                        path,
                        "present" if self._jsession_id else "missing"
                    )
                    return None
                else:
                    _LOGGER.error("API request failed: %s %s", response.status, path)
                    return None
                    
        except asyncio.TimeoutError:
            _LOGGER.error("API request timeout: %s", path)
            return None
        except Exception as ex:
            _LOGGER.error("API request error (%s): %s", path, ex)
            return None
