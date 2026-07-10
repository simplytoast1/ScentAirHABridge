"""DataUpdateCoordinator for ScentAir."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ScentAirAPI, ScentAirAuthError, ScentAirError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)

# Asset document fields that may hold a human-readable device name.
NAME_FIELD_CANDIDATES = ("name", "deviceName", "assetName", "label")


class ScentAirDataUpdateCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Class to manage fetching ScentAir data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.api = ScentAirAPI(
            async_get_clientsession(hass),
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

    def asset_display_name(self, asset_id: str) -> str:
        """Return a human-readable name for an asset, if the cloud has one."""
        fields = self.data.get(asset_id, {}).get("fields", {})
        for key in NAME_FIELD_CANDIDATES:
            value = fields.get(key, {}).get("stringValue")
            if value:
                return value
        return f"ScentAir {asset_id}"

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Fetch data from API endpoint."""
        try:
            locations = await self.api.get_locations()

            # Firestore paths look like: .../locations/LOC_ID
            location_ids = [
                loc.get("name", "").split("/")[-1] for loc in locations
            ]
            asset_lists = await asyncio.gather(
                *(self.api.get_assets(loc_id) for loc_id in location_ids)
            )
        except ScentAirAuthError as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except ScentAirError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        data: dict[str, dict[str, Any]] = {}
        for loc_id, assets in zip(location_ids, asset_lists):
            for asset in assets:
                # Asset name: .../assets/ASSET_ID
                asset_id = asset.get("name", "").split("/")[-1]

                # Store with location ID reference for control calls
                asset["_loc_id"] = loc_id
                data[asset_id] = asset

        return data
