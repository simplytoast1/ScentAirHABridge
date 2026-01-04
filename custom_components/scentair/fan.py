"""Fan platform for ScentAir."""
from __future__ import annotations

import math
from typing import Any

from homeassistant.components.fan import (
    FanEntity,
    FanEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.percentage import (
    int_states_in_range,
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from .const import DOMAIN
from .coordinator import ScentAirDataUpdateCoordinator

# Fan speed in API is 0-10 (seen in logs as string integer)
SPEED_RANGE = (1, 10) # Assuming 1-10, 0 is likely off or stopped

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ScentAir fan from a config entry."""
    coordinator: ScentAirDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for asset_id, data in coordinator.data.items():
        # Only add if it looks like a fan/diffuser
        if "fields" in data and "config" in data["fields"]:
            entities.append(ScentAirFan(coordinator, asset_id))

    async_add_entities(entities)

class ScentAirFan(CoordinatorEntity, FanEntity):
    """Representation of a ScentAir Fan."""

    _attr_has_entity_name = True
    _attr_name = None # Use device name
    _attr_supported_features = FanEntityFeature.SET_SPEED | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF

    def __init__(self, coordinator: ScentAirDataUpdateCoordinator, asset_id: str) -> None:
        """Initialize the fan."""
        super().__init__(coordinator)
        self._asset_id = asset_id
        
        # Device Info
        self._attr_unique_id = f"{asset_id}_fan"
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
        """Get config map from Firestore data."""
        # Structure: fields -> config -> mapValue -> fields
        try:
            return self._asset_data["fields"]["config"]["mapValue"]["fields"]
        except (KeyError, TypeError):
            return {}

    @property
    def is_on(self) -> bool:
        """Return true if device is on."""
        # If fanSpeed > 0, it's on.
        # Note: Firestore integers are strings
        try:
            speed = int(self._config.get("fanSpeed", {}).get("integerValue", "0"))
            return speed > 0
        except (ValueError, TypeError):
            return False

    @property
    def percentage(self) -> int | None:
        """Return the current speed as a percentage."""
        try:
            speed = int(self._config.get("fanSpeed", {}).get("integerValue", "0"))
            if speed == 0:
                return 0
            return ranged_value_to_percentage(SPEED_RANGE, speed)
        except (ValueError, TypeError):
            return 0

    @property
    def speed_count(self) -> int:
        """Return the number of speeds the fan supports."""
        return int_states_in_range(SPEED_RANGE)

    async def async_turn_on(self, percentage: int | None = None, **kwargs: Any) -> None:
        """Turn on the fan."""
        if percentage is None:
            percentage = 50 # Default to middle speed if not specified

        await self.async_set_percentage(percentage)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the fan off."""
        loc_id = self._asset_data.get("_loc_id")
        await self.coordinator.api.control_asset(loc_id, self._asset_id, {"fanSpeed": 0})
        await self.coordinator.async_request_refresh()

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed of the fan, as a percentage."""
        if percentage == 0:
             await self.async_turn_off()
             return

        speed = math.ceil(percentage_to_ranged_value(SPEED_RANGE, percentage))
        
        loc_id = self._asset_data.get("_loc_id")
        await self.coordinator.api.control_asset(loc_id, self._asset_id, {"fanSpeed": speed})
        await self.coordinator.async_request_refresh()
