"""Fan platform for ScentAir."""
from __future__ import annotations

import math
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.percentage import (
    int_states_in_range,
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from . import ScentAirConfigEntry
from .coordinator import ScentAirDataUpdateCoordinator
from .entity import ScentAirEntity, async_setup_scentair_platform

# Fan speed in API is 0-10 (seen in logs as string integer); 0 is off.
SPEED_RANGE = (1, 10)
DEFAULT_ON_PERCENTAGE = 50


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ScentAirConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ScentAir fan from a config entry."""

    def _factory(
        coordinator: ScentAirDataUpdateCoordinator, asset_id: str, data: dict
    ) -> list[ScentAirFan]:
        # Only add if it looks like a fan/diffuser
        if "config" in data.get("fields", {}):
            return [ScentAirFan(coordinator, asset_id)]
        return []

    async_setup_scentair_platform(entry, async_add_entities, _factory)


class ScentAirFan(ScentAirEntity, FanEntity):
    """Representation of a ScentAir Fan."""

    _attr_name = None  # Use device name
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )
    # Remove once the minimum supported HA version is 2025.2
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(
        self, coordinator: ScentAirDataUpdateCoordinator, asset_id: str
    ) -> None:
        """Initialize the fan."""
        super().__init__(coordinator, asset_id)
        self._attr_unique_id = f"{asset_id}_fan"
        self._last_on_speed = self._current_speed() or None

    def _current_speed(self) -> int:
        """Return the raw fan speed (0-10) from the asset config."""
        # Note: Firestore integers are strings
        try:
            return int(self._config.get("fanSpeed", {}).get("integerValue", "0"))
        except (ValueError, TypeError):
            return 0

    @callback
    def _handle_coordinator_update(self) -> None:
        """Track the last nonzero speed so turn_on can restore it."""
        if (speed := self._current_speed()) > 0:
            self._last_on_speed = speed
        super()._handle_coordinator_update()

    @property
    def is_on(self) -> bool:
        """Return true if device is on."""
        return self._current_speed() > 0

    @property
    def percentage(self) -> int | None:
        """Return the current speed as a percentage."""
        speed = self._current_speed()
        if speed == 0:
            return 0
        return ranged_value_to_percentage(SPEED_RANGE, speed)

    @property
    def speed_count(self) -> int:
        """Return the number of speeds the fan supports."""
        return int_states_in_range(SPEED_RANGE)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan, restoring the last used speed."""
        if percentage is None:
            if self.is_on:
                return
            if self._last_on_speed:
                percentage = ranged_value_to_percentage(
                    SPEED_RANGE, self._last_on_speed
                )
            else:
                percentage = DEFAULT_ON_PERCENTAGE

        await self.async_set_percentage(percentage)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the fan off."""
        await self._async_control({"fanSpeed": 0})

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed of the fan, as a percentage."""
        if percentage == 0:
            await self.async_turn_off()
            return

        # ceil guarantees any nonzero percentage maps to at least speed 1.
        speed = math.ceil(percentage_to_ranged_value(SPEED_RANGE, percentage))
        await self._async_control({"fanSpeed": speed})
