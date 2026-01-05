"""Number platform for ScentAir."""
from __future__ import annotations

from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberMode,
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
    """Set up ScentAir number from a config entry."""
    coordinator: ScentAirDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for asset_id, data in coordinator.data.items():
        if "fields" in data and "config" in data["fields"]:
            entities.append(ScentAirFanSpeedNumber(coordinator, asset_id))

    async_add_entities(entities)

class ScentAirFanSpeedNumber(CoordinatorEntity, NumberEntity):
    """Representation of the ScentAir Fan Speed Value."""

    _attr_has_entity_name = True
    _attr_name = "Fan Speed"
    _attr_icon = "mdi:fan-speed-2"
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0 # 0 is Off
    _attr_native_max_value = 10
    _attr_native_step = 1

    def __init__(self, coordinator: ScentAirDataUpdateCoordinator, asset_id: str) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._asset_id = asset_id
        self._attr_unique_id = f"{asset_id}_fan_speed"
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
    def _config(self) -> dict:
        """Get config map."""
        try:
            return self._asset_data["fields"]["config"]["mapValue"]["fields"]
        except (KeyError, TypeError):
            return {}

    @property
    def native_value(self) -> float | None:
        """Return the entity value."""
        try:
            return float(self._config.get("fanSpeed", {}).get("integerValue", "0"))
        except (ValueError, TypeError):
            return 0.0

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        val = int(value)
        loc_id = self._asset_data.get("_loc_id")
        await self.coordinator.api.control_asset(loc_id, self._asset_id, {"fanSpeed": val})
        await self.coordinator.async_request_refresh()
