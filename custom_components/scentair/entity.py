"""Base entity and platform helpers for ScentAir."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ScentAirError
from .const import DOMAIN
from .coordinator import ScentAirDataUpdateCoordinator

EntityFactory = Callable[
    [ScentAirDataUpdateCoordinator, str, dict[str, Any]], list[Entity]
]


def async_setup_scentair_platform(
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    entity_factory: EntityFactory,
) -> None:
    """Add entities for current assets and for assets discovered later.

    entity_factory is called once per asset and returns the platform's
    entities for it (empty list if the asset does not qualify yet).
    """
    coordinator: ScentAirDataUpdateCoordinator = entry.runtime_data
    known: set[str] = set()

    def _async_add_new_assets() -> None:
        new_entities: list[Entity] = []
        for asset_id, data in coordinator.data.items():
            if asset_id in known:
                continue
            entities = entity_factory(coordinator, asset_id, data)
            if entities:
                known.add(asset_id)
                new_entities.extend(entities)
        if new_entities:
            async_add_entities(new_entities)

    _async_add_new_assets()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_assets))


class ScentAirEntity(CoordinatorEntity[ScentAirDataUpdateCoordinator]):
    """Common ScentAir entity backed by one asset document."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: ScentAirDataUpdateCoordinator, asset_id: str
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._asset_id = asset_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, asset_id)},
            name=coordinator.asset_display_name(asset_id),
            manufacturer="ScentAir",
        )

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
    def available(self) -> bool:
        """Return False when the asset disappears from coordinator data."""
        return super().available and self._asset_id in self.coordinator.data

    async def _async_control(self, changes: dict[str, Any]) -> None:
        """Send a config change for this asset and request a refresh."""
        loc_id = self._asset_data.get("_loc_id")
        if not loc_id:
            raise HomeAssistantError(
                f"No location known for {self.entity_id}; device data unavailable"
            )
        try:
            await self.coordinator.api.control_asset(loc_id, self._asset_id, changes)
        except ScentAirError as err:
            raise HomeAssistantError(
                f"Failed to update {self.entity_id}: {err}"
            ) from err
        await self.coordinator.async_request_refresh()
