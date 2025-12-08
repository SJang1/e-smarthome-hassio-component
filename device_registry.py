"""Known device configurations for Daelim Smart Home apartments.

This module contains device configurations discovered from HAR captures
and other sources. When the TCP protocol connection fails, the integration
can use these known configurations to create entities.

Device configurations are keyed by apartment ID (apartId).
"""
from __future__ import annotations

import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Known device configurations by apartment ID
# These are captured from actual HAR files and verified device lists
KNOWN_DEVICE_CONFIGS: dict[str, dict[str, Any]] = {
    # 대전 법동 e편한세상 (apartId: 224)
    "224": {
        "light": [
            {"uid": "012611", "dimming": "y", "uname": "거실"},
            {"uid": "012511", "dimming": "n", "uname": "복도"},
            {"uid": "012521", "dimming": "n", "uname": "침실1-1"},
            {"uid": "012522", "dimming": "n", "uname": "침실1-2"},
            {"uid": "012531", "dimming": "n", "uname": "침실2"},
            {"uid": "012541", "dimming": "n", "uname": "침실3"},
        ],
        "gas": [
            {"uid": "012711", "uname": "주방"},
        ],
        "heating": [
            {"uid": "012411", "uname": "거실"},
            {"uid": "012412", "uname": "침실1"},
            {"uid": "012413", "uname": "침실2"},
            {"uid": "012414", "uname": "침실3"},
        ],
        "wallsocket": [
            {"uid": "013111", "uname": "거실1"},
            {"uid": "013121", "uname": "거실2"},
            {"uid": "013131", "uname": "침실1-1"},
            {"uid": "013141", "uname": "침실1-2"},
            {"uid": "013151", "uname": "침실2"},
            {"uid": "013161", "uname": "침실3"},
            {"uid": "013171", "uname": "주방1-1"},
            {"uid": "013181", "uname": "주방1-2"},
        ],
    },
    # Add more apartments here as they are discovered
    # Template for adding new apartments:
    # "APART_ID": {
    #     "light": [{"uid": "...", "dimming": "y/n", "uname": "..."}],
    #     "gas": [{"uid": "...", "uname": "..."}],
    #     "heating": [{"uid": "...", "uname": "..."}],
    #     "fan": [{"uid": "...", "uname": "..."}],  # Optional
    #     "wallsocket": [{"uid": "...", "uname": "..."}],
    # },
}


def get_known_device_config(apart_id: str) -> dict[str, Any] | None:
    """Get known device configuration for an apartment.
    
    Args:
        apart_id: The apartment ID (e.g., "224")
        
    Returns:
        Device configuration dict if known, None otherwise
    """
    config = KNOWN_DEVICE_CONFIGS.get(apart_id)
    if config:
        _LOGGER.info(
            "Found known device configuration for apartment %s: "
            "%d lights, %d heating, %d gas, %d fan, %d wallsocket",
            apart_id,
            len(config.get("light", [])),
            len(config.get("heating", [])),
            len(config.get("gas", [])),
            len(config.get("fan", [])),
            len(config.get("wallsocket", [])),
        )
    return config


def generate_default_device_config(
    apartment_type: str = "standard"
) -> dict[str, Any]:
    """Generate a default device configuration based on apartment type.
    
    This is used as a last resort when no known configuration exists
    and the protocol connection fails.
    
    Args:
        apartment_type: Type of apartment ("standard", "small", "large")
        
    Returns:
        A default device configuration
    """
    # Standard apartment (3 rooms + living room)
    if apartment_type == "standard":
        return {
            "light": [
                {"uid": "010101", "dimming": "y", "uname": "거실"},
                {"uid": "010102", "dimming": "n", "uname": "복도"},
                {"uid": "010103", "dimming": "n", "uname": "침실1"},
                {"uid": "010104", "dimming": "n", "uname": "침실2"},
                {"uid": "010105", "dimming": "n", "uname": "침실3"},
            ],
            "gas": [
                {"uid": "010201", "uname": "주방"},
            ],
            "heating": [
                {"uid": "010301", "uname": "거실"},
                {"uid": "010302", "uname": "침실1"},
                {"uid": "010303", "uname": "침실2"},
                {"uid": "010304", "uname": "침실3"},
            ],
            "wallsocket": [
                {"uid": "010401", "uname": "거실"},
                {"uid": "010402", "uname": "침실1"},
                {"uid": "010403", "uname": "침실2"},
                {"uid": "010404", "uname": "침실3"},
            ],
        }
    
    # Small apartment (1-2 rooms)
    elif apartment_type == "small":
        return {
            "light": [
                {"uid": "010101", "dimming": "y", "uname": "거실"},
                {"uid": "010102", "dimming": "n", "uname": "침실"},
            ],
            "gas": [
                {"uid": "010201", "uname": "주방"},
            ],
            "heating": [
                {"uid": "010301", "uname": "거실"},
                {"uid": "010302", "uname": "침실"},
            ],
            "wallsocket": [
                {"uid": "010401", "uname": "거실"},
                {"uid": "010402", "uname": "침실"},
            ],
        }
    
    # Large apartment (4+ rooms)
    elif apartment_type == "large":
        return {
            "light": [
                {"uid": "010101", "dimming": "y", "uname": "거실"},
                {"uid": "010102", "dimming": "n", "uname": "복도"},
                {"uid": "010103", "dimming": "n", "uname": "안방"},
                {"uid": "010104", "dimming": "n", "uname": "침실1"},
                {"uid": "010105", "dimming": "n", "uname": "침실2"},
                {"uid": "010106", "dimming": "n", "uname": "침실3"},
                {"uid": "010107", "dimming": "n", "uname": "서재"},
            ],
            "gas": [
                {"uid": "010201", "uname": "주방"},
            ],
            "heating": [
                {"uid": "010301", "uname": "거실"},
                {"uid": "010302", "uname": "안방"},
                {"uid": "010303", "uname": "침실1"},
                {"uid": "010304", "uname": "침실2"},
                {"uid": "010305", "uname": "침실3"},
                {"uid": "010306", "uname": "서재"},
            ],
            "wallsocket": [
                {"uid": "010401", "uname": "거실1"},
                {"uid": "010402", "uname": "거실2"},
                {"uid": "010403", "uname": "안방"},
                {"uid": "010404", "uname": "침실1"},
                {"uid": "010405", "uname": "침실2"},
                {"uid": "010406", "uname": "침실3"},
            ],
        }
    
    # Fallback - minimal config
    return {
        "light": [{"uid": "010101", "dimming": "n", "uname": "거실"}],
        "gas": [{"uid": "010201", "uname": "주방"}],
        "heating": [{"uid": "010301", "uname": "거실"}],
    }
