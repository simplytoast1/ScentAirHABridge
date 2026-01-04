"""Select platform for ScentAir."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SCENTAIR_COLORS
from .coordinator import ScentAirDataUpdateCoordinator

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ScentAir select from a config entry."""
    coordinator: ScentAirDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for asset_id, data in coordinator.data.items():
        if "fields" in data and "config" in data["fields"]:
            entities.append(ScentAirColorSelect(coordinator, asset_id))

    async_add_entities(entities)

class ScentAirColorSelect(CoordinatorEntity, SelectEntity):
    """Representation of the ScentAir RGB Light Color Select."""

    _attr_has_entity_name = True
    _attr_name = "Accent Color"
    _attr_icon = "mdi:palette-swatch"

    def __init__(self, coordinator: ScentAirDataUpdateCoordinator, asset_id: str) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._asset_id = asset_id
        self._attr_unique_id = f"{asset_id}_rgb_select"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, asset_id)},
            "name": f"ScentAir {asset_id}",
            "manufacturer": "ScentAir",
        }
        # List of available color names
        self._attr_options = list(SCENTAIR_COLORS.values())
        
        # Reverse map for easy lookup
        self._name_to_id = {v: k for k, v in SCENTAIR_COLORS.items()}

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
    def current_option(self) -> str | None:
        """Return the selected entity option to represent the entity state."""
        try:
            val = int(self._config.get("rgbLight", {}).get("integerValue", "7"))
            return SCENTAIR_COLORS.get(val, "Off")
        except (ValueError, TypeError):
            return "Off"

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        val = self._name_to_id.get(option)
        if val is None:
            return # Should not happen

        loc_id = self._asset_data.get("_loc_id")
        await self.coordinator.api.control_asset(loc_id, self._asset_id, {"rgbLight": val})
        await self.coordinator.async_request_refresh()
