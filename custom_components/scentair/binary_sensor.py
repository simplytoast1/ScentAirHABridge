"""Binary sensor platform for ScentAir."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ScentAirDataUpdateCoordinator

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ScentAir binary sensor from a config entry."""
    coordinator: ScentAirDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for asset_id, data in coordinator.data.items():
        # Check if status field exists (it should for all assets)
        if "fields" in data:
            entities.append(ScentAirOnlineSensor(coordinator, asset_id))

    async_add_entities(entities)

class ScentAirOnlineSensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of the ScentAir Online Status."""

    _attr_has_entity_name = True
    _attr_name = "Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: ScentAirDataUpdateCoordinator, asset_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._asset_id = asset_id
        
        self._attr_unique_id = f"{asset_id}_online"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, asset_id)},
            "name": f"ScentAir {asset_id}",
            "manufacturer": "ScentAir",
        }

    @property
    def _asset_data(self) -> dict:
        """Get current asset data."""
        return self.coordinator.data.get(self._asset_id, {})

    @property
    def is_on(self) -> bool:
        """Return true if the device is connected (Online)."""
        # Check direct field 'isOnline' (seen in user dumps)
        fields = self._asset_data.get("fields", {})
        if "isOnline" in fields:
            return fields["isOnline"].get("booleanValue", False)
            
        # Fallback to 'status.isOnline' if previously observed structure exists
        status = fields.get("status", {}).get("mapValue", {}).get("fields", {})
        return status.get("isOnline", {}).get("booleanValue", False)
