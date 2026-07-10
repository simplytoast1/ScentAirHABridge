"""Light platform for ScentAir."""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ScentAirConfigEntry
from .const import SCENTAIR_COLORS
from .coordinator import ScentAirDataUpdateCoordinator
from .entity import ScentAirEntity, async_setup_scentair_platform

# rgbLight value meanings (from user logs): 7 is Black/Off, 8 is White.
RGB_OFF = 7
RGB_WHITE = 8


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ScentAirConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ScentAir light from a config entry."""

    def _factory(
        coordinator: ScentAirDataUpdateCoordinator, asset_id: str, data: dict
    ) -> list[LightEntity]:
        if "config" in data.get("fields", {}):
            return [
                ScentAirBacklight(coordinator, asset_id),
                ScentAirRGB(coordinator, asset_id),
            ]
        return []

    async_setup_scentair_platform(entry, async_add_entities, _factory)


class ScentAirBacklight(ScentAirEntity, LightEntity):
    """Representation of the ScentAir Backlight."""

    _attr_name = "Logo Light"
    _attr_icon = "mdi:led-on"
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF

    def __init__(
        self, coordinator: ScentAirDataUpdateCoordinator, asset_id: str
    ) -> None:
        """Initialize the light."""
        super().__init__(coordinator, asset_id)
        self._attr_unique_id = f"{asset_id}_backlight"

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        return self._config.get("isBacklightOn", {}).get("booleanValue", False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light."""
        await self._async_control({"isBacklightOn": True})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        await self._async_control({"isBacklightOn": False})


class ScentAirRGB(ScentAirEntity, LightEntity):
    """Representation of the ScentAir RGB Light (Accent Light)."""

    _attr_name = "Accent Light"
    _attr_icon = "mdi:lightbulb-variant"
    _attr_supported_color_modes = {ColorMode.HS}
    _attr_color_mode = ColorMode.HS
    _attr_supported_features = LightEntityFeature.EFFECT

    # Use shared constants
    _COLORS = SCENTAIR_COLORS

    # Reverse map for name -> id (Exclude Off)
    _COLOR_TO_ID = {v: k for k, v in _COLORS.items() if k != RGB_OFF}

    # Map for easy HS color matching (Hue, Saturation)
    _HS_MAP = {
        0: (180, 100),  # Aqua
        1: (0, 100),    # Red
        2: (30, 100),   # Orange
        3: (60, 100),   # Yellow
        4: (120, 100),  # Green
        5: (240, 100),  # Blue
        6: (270, 100),  # Purple
        7: (0, 0),      # Black/Off
        8: (0, 0),      # White
    }

    def __init__(
        self, coordinator: ScentAirDataUpdateCoordinator, asset_id: str
    ) -> None:
        """Initialize the light."""
        super().__init__(coordinator, asset_id)
        self._attr_unique_id = f"{asset_id}_rgb"
        self._attr_effect_list = list(self._COLOR_TO_ID.keys())
        current = self._get_current_value()
        self._last_color = current if current != RGB_OFF else None

    def _get_current_value(self) -> int:
        try:
            return int(
                self._config.get("rgbLight", {}).get("integerValue", str(RGB_OFF))
            )
        except (ValueError, TypeError):
            return RGB_OFF  # Default to Off

    @callback
    def _handle_coordinator_update(self) -> None:
        """Track the last color so turn_on can restore it."""
        if (val := self._get_current_value()) != RGB_OFF:
            self._last_color = val
        super()._handle_coordinator_update()

    @property
    def is_on(self) -> bool:
        """Return true if light is on (value != 7)."""
        return self._get_current_value() != RGB_OFF

    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Return the hs color value."""
        val = self._get_current_value()
        if val == RGB_OFF:
            return None
        return self._HS_MAP.get(val, (0, 0))

    @property
    def effect(self) -> str | None:
        """Return the current color effect."""
        val = self._get_current_value()
        if val == RGB_OFF:
            return None
        return self._COLORS.get(val, "White")

    @staticmethod
    def _closest_color(hue: float, sat: float) -> int:
        """Map an HS color to the nearest supported color id."""
        if sat < 20:
            return RGB_WHITE
        # Red=0/360, Orange=30, Yellow=60, Green=120, Aqua=180, Blue=240, Purple=270
        if 15 <= hue < 45:
            return 2  # Orange
        if 45 <= hue < 90:
            return 3  # Yellow
        if 90 <= hue < 150:
            return 4  # Green
        if 150 <= hue < 210:
            return 0  # Aqua
        if 210 <= hue < 260:
            return 5  # Blue
        if 260 <= hue < 315:
            return 6  # Purple
        return 1  # Red

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light."""
        if (effect := kwargs.get(ATTR_EFFECT)) and effect in self._COLOR_TO_ID:
            target_val = self._COLOR_TO_ID[effect]
        elif (hs := kwargs.get(ATTR_HS_COLOR)) is not None:
            target_val = self._closest_color(*hs)
        elif self.is_on:
            # Plain turn_on while already on: keep the current color.
            return
        else:
            # Restore the last known color, defaulting to White.
            target_val = self._last_color if self._last_color is not None else RGB_WHITE

        await self._async_control({"rgbLight": target_val})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        await self._async_control({"rgbLight": RGB_OFF})
