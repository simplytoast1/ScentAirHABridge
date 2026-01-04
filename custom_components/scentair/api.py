"""API Client for ScentAir."""
from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp
import jwt

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Found in HAR file analysis
FIREBASE_API_KEY = "AIzaSyAMBHmmor0ccNy_AZjKAJo5GEJG86ZInWA"
AUTH_URL = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
FIRESTORE_BASE = "https://firestore.googleapis.com/v1/projects/scentconnect/databases/(default)/documents"

class ScentAirAPI:
    """ScentAir API Client."""

    def __init__(self, session: aiohttp.ClientSession, username: str | None = None, password: str | None = None) -> None:
        """Initialize the API client."""
        self._session = session
        self._username = username
        self._password = password
        self._id_token = None
        self._refresh_token = None
        self._org_id = None
        self._user_id = None

    async def login(self) -> None:
        """Log in to Firebase."""
        payload = {
            "email": self._username,
            "password": self._password,
            "returnSecureToken": True,
        }
        
        async with self._session.post(AUTH_URL, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
            
        self._id_token = data["idToken"]
        self._refresh_token = data["refreshToken"]
        self._user_id = data["localId"]
        
        # Decode token to get Organization ID (scent connects specific claim)
        # Note: We don't verify signature here as we trust the IDP response for this internal use
        decoded = jwt.decode(self._id_token, options={"verify_signature": False})
        
        # Claims structure seen in HAR: claims: { portal: "CUSTOMER", role: "ENT_MANAGER", orgId: "..." }
        claims = decoded.get("claims", {})
        self._org_id = claims.get("orgId")
        
        if not self._org_id:
            raise Exception("Could not find Organization ID in token claims")

    async def _refresh_auth_token(self) -> None:
        """Refresh the ID token."""
        url = f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_API_KEY}"
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }
        
        async with self._session.post(url, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
            
        self._id_token = data["id_token"]
        self._refresh_token = data["refresh_token"]
        # org_id typically remains valid for the user session, but user_id is in the token.
        
    async def _request(self, method: str, url: str, **kwargs) -> dict:
        """Make an API request with auto-refresh."""
        if not self._id_token:
            await self.login()
            
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._id_token}"
        
        try:
            async with self._session.request(method, url, headers=headers, **kwargs) as resp:
                if resp.status == 401:
                    _LOGGER.info("Token expired, refreshing...")
                    await self._refresh_auth_token()
                    # Retry once
                    headers["Authorization"] = f"Bearer {self._id_token}"
                    async with self._session.request(method, url, headers=headers, **kwargs) as resp2:
                        resp2.raise_for_status()
                        return await resp2.json()
                
                resp.raise_for_status()
                return await resp.json()
        except Exception as err:
             _LOGGER.error(f"API Request Error: {err}")
             raise

    async def get_locations(self) -> list[dict[str, Any]]:
        """Get list of locations for the organization."""
        url = f"{FIRESTORE_BASE}/organizations/{self._org_id}/locations"
        data = await self._request("GET", url)
        return data.get("documents", [])

    async def get_assets(self, location_id: str) -> list[dict[str, Any]]:
        """Get assets for a specific location."""
        url = f"{FIRESTORE_BASE}/organizations/{self._org_id}/locations/{location_id}/assets"
        data = await self._request("GET", url)
        return data.get("documents", [])

    async def control_asset(self, location_id: str, asset_id: str, changes: dict[str, Any]) -> None:
        """Control an asset (fan speed, lights, etc).
        
        changes: dict of key -> value.
        e.g. {"fanSpeed": 50, "isBacklightOn": True}
        """
        url = f"{FIRESTORE_BASE}/organizations/{self._org_id}/locations/{location_id}/assets/{asset_id}"
        
        # Construct Firestore update mask and fields
        fields = {}
        update_mask = []
        
        for key, value in changes.items():
            field_path = f"config.{key}"
            update_mask.append(f"updateMask.fieldPaths={field_path}")
            
            # Map Python types to Firestore types
            if isinstance(value, bool):
                fields[key] = {"booleanValue": value}
            elif isinstance(value, int):
                fields[key] = {"integerValue": str(value)} # Firestore ints are strings in JSON
            # Add other types if needed
            
        payload = {
            "fields": {
                "config": {
                    "mapValue": {
                        "fields": fields
                    }
                },
            }
        }
        
        # Append mask params to URL
        query = "&".join(update_mask)
        full_url = f"{url}?{query}"
        
        # We don't return anything for control calls usually, or the updated doc
        await self._request("PATCH", full_url, json=payload)

