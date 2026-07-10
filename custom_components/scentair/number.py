"""Number platform for ScentAir."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
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
    """Set up ScentAir number from a config entry."""

    def _factory(
        coordinator: ScentAirDataUpdateCoordinator, asset_id: str, data: dict
    ) -> list[ScentAirFanSpeedNumber]:
        if "config" in data.get("fields", {}):
            return [ScentAirFanSpeedNumber(coordinator, asset_id)]
        return []

    async_setup_scentair_platform(entry, async_add_entities, _factory)


class ScentAirFanSpeedNumber(ScentAirEntity, NumberEntity):
    """Representation of the ScentAir Fan Speed Value."""

    _attr_name = "Fan Speed"
    _attr_icon = "mdi:fan-speed-2"
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0  # 0 is Off
    _attr_native_max_value = 10
    _attr_native_step = 1

    def __init__(
        self, coordinator: ScentAirDataUpdateCoordinator, asset_id: str
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, asset_id)
        self._attr_unique_id = f"{asset_id}_fan_speed"

    @property
    def native_value(self) -> float | None:
        """Return the entity value."""
        try:
            return float(self._config.get("fanSpeed", {}).get("integerValue", "0"))
        except (ValueError, TypeError):
            return 0.0

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        await self._async_control({"fanSpeed": int(value)})
