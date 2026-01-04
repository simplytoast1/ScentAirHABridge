"""Light platform for ScentAir."""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ColorMode,
    LightEntity,
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
    """Set up ScentAir light from a config entry."""
    coordinator: ScentAirDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for asset_id, data in coordinator.data.items():
        if "fields" in data and "config" in data["fields"]:
            entities.append(ScentAirBacklight(coordinator, asset_id))
            entities.append(ScentAirRGB(coordinator, asset_id))

    async_add_entities(entities)

class ScentAirBacklight(CoordinatorEntity, LightEntity):
    """Representation of the ScentAir Backlight."""

    _attr_has_entity_name = True
    _attr_name = "Backlight"
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF

    def __init__(self, coordinator: ScentAirDataUpdateCoordinator, asset_id: str) -> None:
        """Initialize the light."""
        super().__init__(coordinator)
        self._asset_id = asset_id
        
        self._attr_unique_id = f"{asset_id}_backlight"
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
    def is_on(self) -> bool:
        """Return true if light is on."""
        return self._config.get("isBacklightOn", {}).get("booleanValue", False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light."""
        loc_id = self._asset_data.get("_loc_id")
        await self.coordinator.api.control_asset(loc_id, self._asset_id, {"isBacklightOn": True})
        # Optimistic update
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        loc_id = self._asset_data.get("_loc_id")
        await self.coordinator.api.control_asset(loc_id, self._asset_id, {"isBacklightOn": False})
        await self.coordinator.async_request_refresh()


class ScentAirRGB(CoordinatorEntity, LightEntity):
    """Representation of the ScentAir RGB Light (Accent Light)."""

    _attr_has_entity_name = True
    _attr_name = "Accent Light"
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF

    def __init__(self, coordinator: ScentAirDataUpdateCoordinator, asset_id: str) -> None:
        """Initialize the light."""
        super().__init__(coordinator)
        self._asset_id = asset_id
        
        self._attr_unique_id = f"{asset_id}_rgb"
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
    def is_on(self) -> bool:
        """Return true if light is on."""
        # RGB Light is 0 (off) or >0 (on/color code). Logic based on 'rgbLight' integer.
        try:
            val = int(self._config.get("rgbLight", {}).get("integerValue", "0"))
            return val > 0
        except (ValueError, TypeError):
            return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light."""
        # Default to 7 (White/On) if turning on from off state, or preserve if we knew how
        loc_id = self._asset_data.get("_loc_id")
        await self.coordinator.api.control_asset(loc_id, self._asset_id, {"rgbLight": 7})
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        loc_id = self._asset_data.get("_loc_id")
        await self.coordinator.api.control_asset(loc_id, self._asset_id, {"rgbLight": 0})
        await self.coordinator.async_request_refresh()
