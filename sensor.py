"""Sensor platform for Daelim Smart Home energy monitoring."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfEnergy,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DaelimDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Energy type configuration
# Maps API type to (name_ko, name_en, device_class, unit, icon)
ENERGY_TYPES = {
    "Elec": ("전기", "Electricity", SensorDeviceClass.ENERGY, UnitOfEnergy.KILO_WATT_HOUR, "mdi:flash"),
    "Gas": ("가스", "Gas", SensorDeviceClass.GAS, UnitOfVolume.CUBIC_METERS, "mdi:fire"),
    "Water": ("수도", "Water", SensorDeviceClass.WATER, UnitOfVolume.CUBIC_METERS, "mdi:water"),
    "Hotwater": ("온수", "Hot Water", SensorDeviceClass.WATER, UnitOfVolume.CUBIC_METERS, "mdi:water-boiler"),
    "Heating": ("난방", "Heating", SensorDeviceClass.ENERGY, UnitOfEnergy.KILO_WATT_HOUR, "mdi:radiator"),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Daelim Smart Home energy sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DaelimDataUpdateCoordinator = data["coordinator"]
    
    _LOGGER.info("Setting up energy sensors. Coordinator data: %s", 
                 list(coordinator.data.keys()) if coordinator.data else None)
    
    entities: list[SensorEntity] = []
    
    # Create sensors for each energy type
    for energy_type, (name_ko, name_en, device_class, unit, icon) in ENERGY_TYPES.items():
        # Current month usage
        entities.append(
            DaelimEnergySensor(
                coordinator=coordinator,
                energy_type=energy_type,
                name_ko=name_ko,
                name_en=name_en,
                device_class=device_class,
                unit=unit,
                icon=icon,
                sensor_type="current",
            )
        )
        # Total usage
        entities.append(
            DaelimEnergySensor(
                coordinator=coordinator,
                energy_type=energy_type,
                name_ko=name_ko,
                name_en=name_en,
                device_class=device_class,
                unit=unit,
                icon=icon,
                sensor_type="total",
            )
        )
        # Average usage
        entities.append(
            DaelimEnergySensor(
                coordinator=coordinator,
                energy_type=energy_type,
                name_ko=name_ko,
                name_en=name_en,
                device_class=device_class,
                unit=unit,
                icon=icon,
                sensor_type="average",
            )
        )
        # Yearly total
        entities.append(
            DaelimEnergyYearlySensor(
                coordinator=coordinator,
                energy_type=energy_type,
                name_ko=name_ko,
                name_en=name_en,
                device_class=device_class,
                unit=unit,
                icon=icon,
            )
        )
    
    async_add_entities(entities)


class DaelimEnergySensor(CoordinatorEntity[DaelimDataUpdateCoordinator], SensorEntity):
    """Representation of a Daelim Smart Home energy sensor."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        coordinator: DaelimDataUpdateCoordinator,
        energy_type: str,
        name_ko: str,
        name_en: str,
        device_class: SensorDeviceClass,
        unit: str,
        icon: str,
        sensor_type: str,  # "current", "total", or "average"
    ) -> None:
        """Initialize the energy sensor."""
        super().__init__(coordinator)
        self._energy_type = energy_type
        self._name_ko = name_ko
        self._name_en = name_en
        self._sensor_type = sensor_type
        
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        
        # Set sensor-type-specific attributes
        if sensor_type == "current":
            self._attr_name = f"{name_ko} 당월 ({name_en} This Month)"
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING
            self._attr_device_class = device_class
        elif sensor_type == "total":
            self._attr_name = f"{name_ko} 누적 ({name_en} Total)"
            self._attr_state_class = SensorStateClass.TOTAL
            self._attr_device_class = device_class
        else:  # average
            self._attr_name = f"{name_ko} 평균 ({name_en} Average)"
            # For average, we can't use device_class with MEASUREMENT state_class
            # as energy/gas/water device classes require total or total_increasing
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_device_class = None  # No device_class for averages
        
        self._attr_unique_id = f"{DOMAIN}_energy_{energy_type.lower()}_{sensor_type}"
        
        # Device info for grouping
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "energy_monitor")},
            name="에너지 모니터 (Energy Monitor)",
            manufacturer="대림건설 (Daelim)",
            model="e편한세상 Smart Home EMS",
            via_device=(DOMAIN, "main"),
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not self.coordinator.last_update_success:
            _LOGGER.debug("Sensor %s unavailable: last_update_success=False", self._attr_unique_id)
            return False
        if not self.coordinator.data:
            _LOGGER.debug("Sensor %s unavailable: coordinator.data is None", self._attr_unique_id)
            return False
        energy_available = self.coordinator.data.get("energy") is not None
        if not energy_available:
            _LOGGER.debug("Sensor %s unavailable: energy data is None", self._attr_unique_id)
        return energy_available

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None
        energy_data = self.coordinator.data.get("energy")
        if not energy_data:
            return None
        
        items = energy_data.get("item", [])
        for item in items:
            if item.get("type") == self._energy_type:
                datavalue = item.get("datavalue", [])
                if len(datavalue) >= 4:
                    # datavalue format: [current, ?, total, avg]
                    if self._sensor_type == "current":
                        return self._parse_value(datavalue[0])
                    elif self._sensor_type == "total":
                        return self._parse_value(datavalue[2])
                    else:  # average
                        return self._parse_value(datavalue[3])
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}
        energy_data = self.coordinator.data.get("energy")
        if not energy_data:
            return {}
        
        attrs = {
            "query_day": energy_data.get("queryday"),
        }
        
        items = energy_data.get("item", [])
        for item in items:
            if item.get("type") == self._energy_type:
                datavalue = item.get("datavalue", [])
                if len(datavalue) >= 4:
                    attrs["raw_data"] = datavalue
        
        return attrs

    def _parse_value(self, value: Any) -> float | None:
        """Parse a value to float."""
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None


class DaelimEnergyYearlySensor(CoordinatorEntity[DaelimDataUpdateCoordinator], SensorEntity):
    """Representation of a Daelim Smart Home yearly energy sensor."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        coordinator: DaelimDataUpdateCoordinator,
        energy_type: str,
        name_ko: str,
        name_en: str,
        device_class: SensorDeviceClass,
        unit: str,
        icon: str,
    ) -> None:
        """Initialize the yearly energy sensor."""
        super().__init__(coordinator)
        self._energy_type = energy_type
        self._name_ko = name_ko
        self._name_en = name_en
        
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_name = f"{name_ko} 연간 ({name_en} Yearly)"
        self._attr_unique_id = f"{DOMAIN}_energy_{energy_type.lower()}_yearly"
        
        # Device info for grouping
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "energy_monitor")},
            name="에너지 모니터 (Energy Monitor)",
            manufacturer="대림건설 (Daelim)",
            model="e편한세상 Smart Home EMS",
            via_device=(DOMAIN, "main"),
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not self.coordinator.last_update_success:
            return False
        if not self.coordinator.data:
            return False
        yearly_data = self.coordinator.data.get("energy_yearly", {})
        return yearly_data.get(self._energy_type) is not None

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor (yearly total from rank).
        
        Response format:
        {
            "total": [145, 1504],   # [rank_position, total_households]
            "rank": [145, 1504],    # [my_usage, apartment_average]
            "type": "Elec",
            "gubun": "year",
            "year": "2025"
        }
        """
        if not self.coordinator.data:
            return None
        yearly_data = self.coordinator.data.get("energy_yearly", {})
        type_data = yearly_data.get(self._energy_type)
        if not type_data:
            return None
        
        # rank[0] is my usage, rank[1] is apartment average
        rank = type_data.get("rank", [])
        if len(rank) >= 1:
            try:
                return float(rank[0])
            except (ValueError, TypeError):
                pass
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes with yearly data."""
        if not self.coordinator.data:
            return {}
        yearly_data = self.coordinator.data.get("energy_yearly", {})
        type_data = yearly_data.get(self._energy_type)
        if not type_data:
            return {}
        
        attrs = {
            "year": type_data.get("year"),
        }
        
        # rank[0] = my usage, rank[1] = apartment average
        rank = type_data.get("rank", [])
        if len(rank) >= 2:
            attrs["my_usage"] = rank[0]
            attrs["apartment_average"] = rank[1]
        
        # total[0] = my rank, total[1] = total households
        total = type_data.get("total", [])
        if len(total) >= 2:
            attrs["my_rank"] = total[0]
            attrs["total_households"] = total[1]
        
        return attrs
