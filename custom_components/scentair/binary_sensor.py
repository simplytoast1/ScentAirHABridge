"""Binary sensor platform for ScentAir."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ScentAirConfigEntry
from .coordinator import ScentAirDataUpdateCoordinator
from .entity import ScentAirEntity, async_setup_scentair_platform


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ScentAirConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ScentAir binary sensor from a config entry."""

    def _factory(
        coordinator: ScentAirDataUpdateCoordinator, asset_id: str, data: dict
    ) -> list[ScentAirOnlineSensor]:
        # Check if status field exists (it should for all assets)
        if "fields" in data:
            return [ScentAirOnlineSensor(coordinator, asset_id)]
        return []

    async_setup_scentair_platform(entry, async_add_entities, _factory)


class ScentAirOnlineSensor(ScentAirEntity, BinarySensorEntity):
    """Representation of the ScentAir Online Status."""

    _attr_name = "Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(
        self, coordinator: ScentAirDataUpdateCoordinator, asset_id: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, asset_id)
        self._attr_unique_id = f"{asset_id}_online"

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
