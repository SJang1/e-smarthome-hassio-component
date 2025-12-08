"""Daelim Smart Home Protocol Implementation.

This module implements the proprietary binary protocol used by the Daelim e편한세상
Smart Home system. Communication is over TCP with a binary header + JSON payload.

Binary Protocol Structure (28-byte header + JSON):
  [0-3]   Length (big-endian uint32) - length of data after first 4 bytes
  [4-11]  LoginPin (8 bytes ASCII, padded with zeros or spaces)
  [12-15] Type (big-endian uint32) - 1=Login, 2=Security, 3=Device
  [16-19] Subtype (big-endian uint32) - operation subtype
  [20-23] Direction (4 bytes) - 0x00,0x01,0x00,0x03 for request, 0x00,0x03,0x00,0x01 for response
  [24-27] Reserved (big-endian uint32) - 0 for request, error code for response
  [28+]   JSON payload

Authentication Flow:
1. Send CertPin request with pin="00000000" -> get certpin
2. Send LoginPin request with pin=certpin -> get loginpin + controlinfo
3. Send Menu request with pin=loginpin -> get device list
4. Use loginpin for all subsequent device control

Based on Wireshark capture analysis of the e편한세상 mobile app.
"""
from __future__ import annotations

import asyncio
import json
import logging
import struct
from typing import Any

_LOGGER = logging.getLogger(__name__)


# =============================================================================
# Protocol Constants
# =============================================================================

# Message Types
TYPE_LOGIN = 1
TYPE_GUARD = 2  # Security/Guard mode
TYPE_DEVICE = 3  # Device control (lights, heating, gas, fan, etc.)
TYPE_EMS = 4  # Energy Management System
TYPE_INFO = 5  # Information (notices, parcels, visitors, etc.)
TYPE_SETTING = 7  # Settings
TYPE_EVCALL = 8  # Elevator call

# Login Subtypes
SUBTYPE_CERTPIN_REQ = 5
SUBTYPE_CERTPIN_RES = 6
SUBTYPE_MENU_REQ = 7
SUBTYPE_MENU_RES = 8
SUBTYPE_LOGINPIN_REQ = 9
SUBTYPE_LOGINPIN_RES = 10

# Security Subtypes
SUBTYPE_SEC_QUERY_REQ = 1
SUBTYPE_SEC_QUERY_RES = 2
SUBTYPE_SEC_SET_REQ = 3
SUBTYPE_SEC_SET_RES = 4

# Device Subtypes
SUBTYPE_DEVICE_QUERY_REQ = 1
SUBTYPE_DEVICE_QUERY_RES = 2
SUBTYPE_DEVICE_INVOKE_REQ = 3
SUBTYPE_DEVICE_INVOKE_RES = 4

# Elevator Subtypes
SUBTYPE_EVCALL_REQ = 1
SUBTYPE_EVCALL_RES = 2

# Info Subtypes
SUBTYPE_SERVICE_CNT_REQ = 45
SUBTYPE_SERVICE_CNT_RES = 46

# Device Names
DEVICE_LIGHT = "light"
DEVICE_HEATING = "heating"
DEVICE_GAS = "gas"
DEVICE_FAN = "fan"
DEVICE_WALLSOCKET = "wallsocket"
DEVICE_ALL = "all"

# State values
STATE_ON = "on"
STATE_OFF = "off"

# Guard modes
GUARD_MODE_ON = "1"
GUARD_MODE_OFF = "0"

# Error codes
ERROR_SUCCESS = 0
ERROR_GENERAL = 1
ERROR_NOT_REGISTERED = 2
ERROR_INVALID_LOGINPIN = 3
ERROR_INVALID_CREDENTIALS = 4
ERROR_CERTPIN_FAILED = 6
ERROR_NO_HOUSEHOLD = 7
ERROR_WALLPAD_COMM = 8
ERROR_DEVICE_COMM = 9
ERROR_DEVICE_CONTROL = 10
ERROR_NOT_FOUND = 11
ERROR_SESSION_EXPIRED = 17
ERROR_NETWORK = 18
ERROR_DUPLICATE_ID = 19
ERROR_UNVERIFIED_USER = 25
ERROR_ALREADY_REGISTERED = 39

# Message error map
MESSAGE_ERR = {
    0: "성공",
    1: "오류가 발생하였습니다",
    2: "등록된 스마트폰이 아닙니다",
    3: "로그인핀이 유효하지 않습니다",
    4: "아이디 또는 암호가 올바르지 않습니다",
    6: "인증핀 생성에 실패하였습니다",
    7: "세대정보를 찾을 수 없습니다",
    8: "단지서버와의 통신이 원활하지 않습니다",
    9: "해당 기기와 접속이 원활하지 않습니다",
    10: "해당 기기 제어에 실패하였습니다",
    11: "해당 정보를 찾을 수 없습니다",
    17: "서비스 이용이 없어 자동 로그아웃 되었습니다",
    18: "네트워크가 원활하지 않습니다",
    19: "중복된 아이디입니다",
    25: "회원가입 미인증 사용자입니다",
    34: "외출모드를 실행할 수 없습니다. 현관문 확인 필요",
    39: "이미 등록된 스마트폰입니다",
}

# Direction markers (4 bytes each)
DIRECTION_REQUEST = bytes([0x00, 0x01, 0x00, 0x03])
DIRECTION_RESPONSE = bytes([0x00, 0x03, 0x00, 0x01])


# =============================================================================
# Protocol Client
# =============================================================================

class DaelimProtocolClient:
    """Daelim Smart Home protocol client.
    
    Handles TCP communication with the apartment's smart home server
    using the proprietary binary protocol.
    """
    
    DEFAULT_PORT = 25301
    HEADER_SIZE = 28  # 4 + 8 + 4 + 4 + 4 + 4
    
    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
    ) -> None:
        """Initialize the protocol client."""
        self._host = host
        self._port = port
        self._login_pin = "00000000"
        self._cert_pin: str | None = None
        
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        self._logged_in = False
        
        self._lock = asyncio.Lock()
        self._control_info: dict = {}
        self._uuid: str = ""
        
    @property
    def connected(self) -> bool:
        """Return True if connected."""
        return self._connected
    
    @property
    def logged_in(self) -> bool:
        """Return True if logged in."""
        return self._logged_in
    
    @property
    def control_info(self) -> dict:
        """Return device control info from login."""
        return self._control_info
    
    @property
    def login_pin(self) -> str:
        """Return current login pin."""
        return self._login_pin
    
    def set_uuid(self, uuid: str) -> None:
        """Set device UUID for authentication."""
        self._uuid = uuid
    
    async def connect(self) -> bool:
        """Connect to the smart home server."""
        if self._connected:
            return True
        
        try:
            _LOGGER.info("Connecting to %s:%s", self._host, self._port)
            
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=10.0
            )
            
            self._connected = True
            _LOGGER.info("Connected to Daelim server")
            return True
            
        except asyncio.TimeoutError:
            _LOGGER.error("Connection timeout")
            return False
        except Exception as ex:
            _LOGGER.error("Connection failed: %s", ex)
            return False
    
    async def disconnect(self) -> None:
        """Disconnect from the server."""
        self._connected = False
        self._logged_in = False
        
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        
        self._reader = None
        _LOGGER.info("Disconnected from Daelim server")
    
    def _build_message(
        self,
        msg_type: int,
        subtype: int,
        payload: dict,
    ) -> bytes:
        """Build a protocol message with binary header.
        
        Format:
          [0-3]   Length (of everything after these 4 bytes)
          [4-11]  LoginPin (8 bytes ASCII)
          [12-15] Type
          [16-19] Subtype
          [20-23] Direction (request marker)
          [24-27] Reserved (0)
          [28+]   JSON payload
        """
        json_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        
        # Length = 8 (pin) + 4 (type) + 4 (subtype) + 4 (direction) + 4 (reserved) + json
        length = 8 + 4 + 4 + 4 + 4 + len(json_bytes)
        
        # Pad login_pin to exactly 8 chars
        pin = self._login_pin.ljust(8)[:8]
        
        message = struct.pack('>I', length)              # [0-3]
        message += pin.encode('ascii')                   # [4-11]
        message += struct.pack('>I', msg_type)           # [12-15]
        message += struct.pack('>I', subtype)            # [16-19]
        message += DIRECTION_REQUEST                     # [20-23]
        message += struct.pack('>I', 0)                  # [24-27]
        message += json_bytes                            # [28+]
        
        return message
    
    def _parse_response(self, data: bytes) -> dict:
        """Parse response with binary header.
        
        Returns dict with:
          - type: message type
          - subtype: message subtype
          - error: error code (0 = success)
          - body: parsed JSON payload
        """
        if len(data) < self.HEADER_SIZE:
            return {"error": -1, "body": {}}
        
        try:
            # Header structure (28 bytes):
            # [0-3]   Length
            # [4-11]  LoginPin
            # [12-15] Type
            # [16-19] Subtype
            # [20-23] Direction
            # [24-27] Error code (0 = success)
            msg_type = struct.unpack('>I', data[12:16])[0]
            subtype = struct.unpack('>I', data[16:20])[0]
            error_code = struct.unpack('>I', data[24:28])[0]
            
            body = {}
            if len(data) > self.HEADER_SIZE:
                json_bytes = data[self.HEADER_SIZE:]
                body = json.loads(json_bytes.decode('utf-8'))
            
            return {
                "type": msg_type,
                "subtype": subtype,
                "error": error_code,
                "body": body,
            }
            
        except Exception as ex:
            _LOGGER.error("Parse error: %s", ex)
            return {"error": -1, "body": {}}
    
    async def _send_and_receive(
        self,
        msg_type: int,
        subtype: int,
        payload: dict,
        timeout: float = 5.0,
    ) -> dict:
        """Send request and wait for response."""
        if not self._connected or not self._writer or not self._reader:
            return {"error": -1, "body": {}}
        
        async with self._lock:
            try:
                message = self._build_message(msg_type, subtype, payload)
                
                _LOGGER.debug(
                    "Sending: type=%d, subtype=%d, pin=%s",
                    msg_type, subtype, self._login_pin
                )
                
                self._writer.write(message)
                await self._writer.drain()
                
                response_data = await asyncio.wait_for(
                    self._reader.read(8192),
                    timeout=timeout
                )
                
                if not response_data:
                    return {"error": -1, "body": {}}
                
                result = self._parse_response(response_data)
                
                _LOGGER.debug(
                    "Received: type=%d, subtype=%d, error=%d",
                    result.get("type", 0),
                    result.get("subtype", 0),
                    result.get("error", 0)
                )
                
                return result
                
            except asyncio.TimeoutError:
                _LOGGER.error("Request timeout")
                return {"error": -1, "body": {}}
            except Exception as ex:
                _LOGGER.error("Send/receive error: %s", ex)
                return {"error": -1, "body": {}}
    
    # =========================================================================
    # Authentication
    # =========================================================================
    
    async def login(self, user_id: str, password: str, uuid: str = "") -> dict:
        """Full login flow.
        
        1. Connect (if not connected)
        2. Get CertPin (pin=00000000, subtype=5)
        3. Get LoginPin (pin=certpin, subtype=9)
        4. Get Menu (pin=loginpin, subtype=7)
        
        Returns response dict with error code and control_info.
        """
        self._uuid = uuid
        
        if not self._connected:
            if not await self.connect():
                return {"error": -1, "body": {}}
        
        try:
            # Step 1: Get CertPin
            self._login_pin = "00000000"
            payload = {"id": user_id, "pw": password}
            if uuid:
                payload["UUID"] = uuid
            
            response = await self._send_and_receive(
                TYPE_LOGIN, SUBTYPE_CERTPIN_REQ, payload
            )
            
            if response.get("error", 0) != ERROR_SUCCESS:
                _LOGGER.error("CertPin request failed: %s", response)
                return response
            
            body = response.get("body", {})
            if "certpin" not in body:
                _LOGGER.error("No certpin in response")
                return {"error": -1, "body": {}}
            
            self._cert_pin = body["certpin"]
            _LOGGER.info("Got CertPin: %s", self._cert_pin)
            
            # Step 2: Get LoginPin
            self._login_pin = self._cert_pin
            payload = {"id": user_id, "pw": password, "certpin": self._cert_pin}
            
            response = await self._send_and_receive(
                TYPE_LOGIN, SUBTYPE_LOGINPIN_REQ, payload
            )
            
            if response.get("error", 0) != ERROR_SUCCESS:
                _LOGGER.error("LoginPin request failed: %s", response)
                return response
            
            body = response.get("body", {})
            if "loginpin" not in body:
                _LOGGER.error("No loginpin in response")
                return {"error": -1, "body": {}}
            
            self._login_pin = body["loginpin"]
            _LOGGER.info("Got LoginPin: %s", self._login_pin)
            
            # Step 3: Get Menu (returns control_info)
            response = await self._send_and_receive(
                TYPE_LOGIN, SUBTYPE_MENU_REQ, {}
            )
            
            if response.get("error", 0) != ERROR_SUCCESS:
                error = response.get("error", 0)
                # Error 0 with empty body is actually OK
                if error != 0:
                    _LOGGER.warning("Menu request returned error: %d", error)
            
            # Parse control_info from menu response
            body = response.get("body", {})
            if "controlinfo" in body:
                self._control_info = body["controlinfo"]
            else:
                # The body itself might be the control info
                self._control_info = body
            
            self._logged_in = True
            _LOGGER.info("Login successful!")
            
            return {"error": ERROR_SUCCESS, "body": self._control_info}
            
        except Exception as ex:
            _LOGGER.error("Login error: %s", ex)
            await self.disconnect()
            return {"error": -1, "body": {}}
    
    # =========================================================================
    # Device Control
    # =========================================================================
    
    async def query_devices(self, device_type: str = "light") -> dict:
        """Query device states."""
        payload = {
            "type": "query",
            "item": [{"device": device_type, "uid": "All"}]
        }
        return await self._send_and_receive(TYPE_DEVICE, SUBTYPE_DEVICE_QUERY_REQ, payload)
    
    async def control_device(
        self,
        device: str,
        uid: str,
        state: str,
        **kwargs: Any,
    ) -> dict:
        """Control a device."""
        item = {
            "device": device,
            "uid": uid,
            "arg1": state,
        }
        
        # Add optional arguments (arg2, arg3, etc.)
        for key, value in kwargs.items():
            if key.startswith("arg"):
                item[key] = str(value)
        
        payload = {
            "type": "invoke",
            "item": [item]
        }
        
        return await self._send_and_receive(TYPE_DEVICE, SUBTYPE_DEVICE_INVOKE_REQ, payload)
    
    async def set_light(
        self,
        uid: str,
        state: str,
        brightness: int | None = None,
    ) -> dict:
        """Set light state."""
        kwargs = {}
        if brightness is not None:
            kwargs["arg2"] = brightness
        return await self.control_device(DEVICE_LIGHT, uid, state, **kwargs)
    
    async def set_heating(
        self,
        uid: str,
        state: str,
        temperature: int | None = None,
    ) -> dict:
        """Set heating state."""
        kwargs = {}
        if temperature is not None:
            kwargs["arg2"] = temperature
        return await self.control_device(DEVICE_HEATING, uid, state, **kwargs)
    
    async def set_gas(self, uid: str, state: str) -> dict:
        """Set gas valve state (typically only 'off' allowed)."""
        return await self.control_device(DEVICE_GAS, uid, state)
    
    async def set_fan(
        self,
        uid: str,
        state: str,
        speed: str | None = None,
        mode: str | None = None,
    ) -> dict:
        """Set fan/ventilation state."""
        kwargs = {}
        if speed is not None:
            kwargs["arg2"] = speed
        if mode is not None:
            kwargs["arg3"] = mode
        return await self.control_device(DEVICE_FAN, uid, state, **kwargs)
    
    async def set_wallsocket(self, uid: str, state: str) -> dict:
        """Set standby power outlet state."""
        return await self.control_device(DEVICE_WALLSOCKET, uid, state)
    
    async def all_off(self) -> dict:
        """Turn off all devices."""
        payload = {
            "type": "invoke",
            "item": [{"device": "all", "uid": "all", "arg1": STATE_OFF}]
        }
        return await self._send_and_receive(TYPE_DEVICE, SUBTYPE_DEVICE_REQ, payload)
    
    # =========================================================================
    # Security/Guard Mode
    # =========================================================================
    
    async def query_guard_mode(self) -> dict:
        """Query guard/security mode status."""
        return await self._send_and_receive(TYPE_GUARD, SUBTYPE_SEC_QUERY_REQ, {})
    
    async def set_guard_mode(
        self,
        mode: str,
        password: str | None = None,
    ) -> dict:
        """Set guard/security mode."""
        payload = {"mode": mode}
        if password:
            payload["pwd"] = password
        return await self._send_and_receive(TYPE_GUARD, SUBTYPE_SEC_SET_REQ, payload)
    
    # =========================================================================
    # Elevator
    # =========================================================================
    
    async def call_elevator(self) -> dict:
        """Call elevator."""
        return await self._send_and_receive(TYPE_EVCALL, SUBTYPE_EVCALL_REQ, {})
    
    # =========================================================================
    # Energy
    # =========================================================================
    
    async def query_energy(self) -> dict:
        """Query current energy usage."""
        return await self._send_and_receive(TYPE_EMS, 1, {})

