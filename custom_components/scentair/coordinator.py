"""DataUpdateCoordinator for ScentAir."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ScentAirAPI
from .const import CONF_PASSWORD, CONF_USERNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)

class ScentAirDataUpdateCoordinator(DataUpdateCoordinator):
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
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, dict]:
        """Fetch data from API endpoint."""
        try:
            # Login if needed (handled internally by API check usually, but good to be explicit on first run)
            if not self.api._id_token:
                await self.api.login()

            locations = await self.api.get_locations()
            
            data = {}
            for loc in locations:
                # Firestore paths look like: .../locations/LOC_ID
                loc_name = loc.get("name", "")
                loc_id = loc_name.split("/")[-1]
                
                assets = await self.api.get_assets(loc_id)
                for asset in assets:
                    # Flatten data for easier consumption by entities
                    # Asset name: .../assets/ASSET_ID
                    asset_path = asset.get("name", "")
                    asset_id = asset_path.split("/")[-1]
                    
                    # Store with location ID reference for control calls
                    asset["_loc_id"] = loc_id
                    data[asset_id] = asset
                    
            return data

        except Exception as err:
            _LOGGER.exception("Error fetching data")
            raise UpdateFailed(f"Error communicating with API: {err}") from err
