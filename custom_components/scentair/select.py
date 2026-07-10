"""Select platform for ScentAir."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ScentAirConfigEntry
from .const import SCENTAIR_COLORS
from .coordinator import ScentAirDataUpdateCoordinator
from .entity import ScentAirEntity, async_setup_scentair_platform


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ScentAirConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ScentAir select from a config entry."""

    def _factory(
        coordinator: ScentAirDataUpdateCoordinator, asset_id: str, data: dict
    ) -> list[ScentAirColorSelect]:
        if "config" in data.get("fields", {}):
            return [ScentAirColorSelect(coordinator, asset_id)]
        return []

    async_setup_scentair_platform(entry, async_add_entities, _factory)


class ScentAirColorSelect(ScentAirEntity, SelectEntity):
    """Representation of the ScentAir RGB Light Color Select."""

    _attr_name = "Accent Color"
    _attr_icon = "mdi:palette"
    _attr_options = list(SCENTAIR_COLORS.values())

    # Reverse map for easy lookup
    _NAME_TO_ID = {v: k for k, v in SCENTAIR_COLORS.items()}

    def __init__(
        self, coordinator: ScentAirDataUpdateCoordinator, asset_id: str
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, asset_id)
        self._attr_unique_id = f"{asset_id}_rgb_select"

    @property
    def current_option(self) -> str | None:
        """Return the selected entity option to represent the entity state."""
        try:
            val = int(self._config.get("rgbLight", {}).get("integerValue", "7"))
            return SCENTAIR_COLORS.get(val, "Off")
        except (ValueError, TypeError):
            return "Off"

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        val = self._NAME_TO_ID.get(option)
        if val is None:
            return  # Should not happen

        await self._async_control({"rgbLight": val})
