"""Light platform for ScentAir."""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ColorMode,
    LightEntity,
    LightEntityFeature,
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
    _attr_icon = "mdi:led-on"
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
    _attr_icon = "mdi:lightbulb-variant"
    _attr_supported_color_modes = {ColorMode.HS}
    _attr_color_mode = ColorMode.HS
    _attr_supported_features = LightEntityFeature.EFFECT

    # Mapping based on analysis:
    # 0=Black(Off), 1=Red, 2=Orange, 3=Yellow, 4=Green, 5=Blue, 6=Purple, 7=White, 8=Aqua
    # Mapping based on analysis:
    # 0=Black(Off), 1=Red, 2=Orange, 3=Yellow, 4=Green, 5=Blue, 6=Purple, 7=White(Off/Idle?), 8=Aqua
    _COLORS = {
        0: "Off",
        1: "Red",
        2: "Orange",
        3: "Yellow",
        4: "Green",
        5: "Blue",
        6: "Purple",
        7: "White (Idle)", # User reports 7 is considered off
        8: "Aqua"
    }
    # Reverse map for name -> id (Exclude 0 and 7 from selectable effects if 7 is off)
    _COLOR_TO_ID = {v: k for k, v in _COLORS.items() if k not in (0, 7)}
    
    # Map for easy HS color matching (Hue, Saturation)
    _HS_MAP = {
        1: (0, 100),    # Red
        2: (30, 100),   # Orange
        3: (60, 100),   # Yellow
        4: (120, 100),  # Green
        5: (240, 100),  # Blue
        6: (270, 100),  # Purple
        7: (0, 0),      # White (Idle)
        8: (180, 100),  # Aqua
    }

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
        self._attr_effect_list = list(self._COLOR_TO_ID.keys())

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
        """Return true if light is on (value > 0 and not 7)."""
        val = self._get_current_value()
        # User reports 7 is 'off'
        return val > 0 and val != 7

    @property
    def brightness_step_pct(self) -> float | None:
        """Return brightness."""
        # Simple On/Off brightness for now, or could map to 7/8? No, strictly preset.
        return 100 if self.is_on else 0

    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Return the hs color value."""
        val = self._get_current_value()
        return self._HS_MAP.get(val, (0, 0)) # Default to white if unknown

    @property
    def effect(self) -> str | None:
        """Return the current start effect."""
        val = self._get_current_value()
        return self._COLORS.get(val, "White") if val > 0 else None

    def _get_current_value(self) -> int:
        try:
            return int(self._config.get("rgbLight", {}).get("integerValue", "0"))
        except (ValueError, TypeError):
            return 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light."""
        loc_id = self._asset_data.get("_loc_id")
        target_val = 2 # Default to Orange if just toggled on, as 7 is Off

        # Handle Effect selection
        if (effect := kwargs.get("effect")) and effect in self._COLOR_TO_ID:
            target_val = self._COLOR_TO_ID[effect]
            
        # Handle HS Color selection (Find closest match)
        elif (hs := kwargs.get("hs_color")):
            hue, sat = hs
            # Simple nearest neighbor logic
            if sat < 20:
                target_val = 2 # Fallback for white -> Orange
            else:
                # Map hue to colors
                # Red=0/360, Orange=30, Yellow=60, Green=120, Aqua=180, Blue=240, Purple=270
                if 15 <= hue < 45: target_val = 2 # Orange
                elif 45 <= hue < 90: target_val = 3 # Yellow
                elif 90 <= hue < 150: target_val = 4 # Green
                elif 150 <= hue < 210: target_val = 8 # Aqua
                elif 210 <= hue < 260: target_val = 5 # Blue
                elif 260 <= hue < 315: target_val = 6 # Purple
                else: target_val = 1 # Red

        await self.coordinator.api.control_asset(loc_id, self._asset_id, {"rgbLight": target_val})
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        loc_id = self._asset_data.get("_loc_id")
        await self.coordinator.api.control_asset(loc_id, self._asset_id, {"rgbLight": 0})
        await self.coordinator.async_request_refresh()
