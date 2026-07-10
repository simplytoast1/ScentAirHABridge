"""API Client for ScentAir."""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

# Firebase web API key for the ScentConnect project. This is a public client
# identifier (visible to anyone using the web portal), not a secret.
FIREBASE_API_KEY = "AIzaSyAMBHmmor0ccNy_AZjKAJo5GEJG86ZInWA"
AUTH_URL = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
REFRESH_URL = f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_API_KEY}"
FIRESTORE_BASE = "https://firestore.googleapis.com/v1/projects/scentconnect/databases/(default)/documents"

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

# Firebase auth endpoints signal rejected credentials with these statuses.
AUTH_ERROR_STATUSES = (400, 401, 403)


class ScentAirError(Exception):
    """Base error for the ScentAir API client."""


class ScentAirAuthError(ScentAirError):
    """Credentials or tokens were rejected."""


class ScentAirConnectionError(ScentAirError):
    """Error communicating with the ScentAir cloud."""


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    """Decode a JWT payload without verifying the signature.

    The token comes straight from the Firebase token endpoint over HTTPS,
    so signature verification adds nothing here.
    """
    try:
        payload = token.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except (IndexError, ValueError) as err:
        raise ScentAirAuthError(f"Could not decode ID token: {err}") from err


class ScentAirAPI:
    """ScentAir API Client."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        """Initialize the API client."""
        self._session = session
        self._username = username
        self._password = password
        self._id_token: str | None = None
        self._refresh_token: str | None = None
        self._org_id: str | None = None
        self._user_id: str | None = None

    @property
    def user_id(self) -> str | None:
        """Return the Firebase user id (stable per account)."""
        return self._user_id

    async def login(self) -> None:
        """Log in to Firebase with the stored credentials."""
        payload = {
            "email": self._username,
            "password": self._password,
            "returnSecureToken": True,
        }

        try:
            async with self._session.post(
                AUTH_URL, json=payload, timeout=REQUEST_TIMEOUT
            ) as resp:
                if resp.status in AUTH_ERROR_STATUSES:
                    raise ScentAirAuthError(
                        f"Login rejected with status {resp.status}"
                    )
                resp.raise_for_status()
                data = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ScentAirConnectionError(f"Error connecting to ScentAir: {err}") from err

        self._id_token = data["idToken"]
        self._refresh_token = data["refreshToken"]
        self._user_id = data["localId"]

        # Claims structure seen in HAR: claims: { portal: "CUSTOMER", role: "ENT_MANAGER", orgId: "..." }
        decoded = _decode_jwt_payload(self._id_token)
        claims = decoded.get("claims", {})
        self._org_id = claims.get("orgId")

        if not self._org_id:
            raise ScentAirAuthError("Could not find Organization ID in token claims")

    async def _refresh_auth_token(self) -> None:
        """Refresh the ID token."""
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }

        try:
            async with self._session.post(
                REFRESH_URL, json=payload, timeout=REQUEST_TIMEOUT
            ) as resp:
                if resp.status in AUTH_ERROR_STATUSES:
                    raise ScentAirAuthError(
                        f"Token refresh rejected with status {resp.status}"
                    )
                resp.raise_for_status()
                data = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ScentAirConnectionError(f"Error connecting to ScentAir: {err}") from err

        self._id_token = data["id_token"]
        self._refresh_token = data["refresh_token"]

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._id_token}"}

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        """Make an API request, re-establishing auth on a 401."""
        if not self._id_token:
            await self.login()

        try:
            async with self._session.request(
                method, url, headers=self._auth_headers(), timeout=REQUEST_TIMEOUT, **kwargs
            ) as resp:
                if resp.status != 401:
                    resp.raise_for_status()
                    return await resp.json()

            # Token rejected: refresh it, falling back to a full login when the
            # refresh token itself has been revoked (e.g. after a password change).
            _LOGGER.debug("ID token rejected, refreshing")
            try:
                await self._refresh_auth_token()
            except ScentAirAuthError:
                self._id_token = None
                self._refresh_token = None
                await self.login()

            async with self._session.request(
                method, url, headers=self._auth_headers(), timeout=REQUEST_TIMEOUT, **kwargs
            ) as resp:
                if resp.status == 401:
                    raise ScentAirAuthError("Request unauthorized after re-authentication")
                resp.raise_for_status()
                return await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ScentAirConnectionError(f"Error communicating with ScentAir: {err}") from err

    async def _list_documents(self, url: str) -> list[dict[str, Any]]:
        """List all documents in a Firestore collection, following pagination."""
        documents: list[dict[str, Any]] = []
        params: dict[str, str] = {"pageSize": "300"}
        while True:
            data = await self._request("GET", url, params=params)
            documents.extend(data.get("documents", []))
            next_token = data.get("nextPageToken")
            if not next_token:
                return documents
            params["pageToken"] = next_token

    async def get_locations(self) -> list[dict[str, Any]]:
        """Get list of locations for the organization."""
        return await self._list_documents(
            f"{FIRESTORE_BASE}/organizations/{self._org_id}/locations"
        )

    async def get_assets(self, location_id: str) -> list[dict[str, Any]]:
        """Get assets for a specific location."""
        return await self._list_documents(
            f"{FIRESTORE_BASE}/organizations/{self._org_id}/locations/{location_id}/assets"
        )

    async def control_asset(
        self, location_id: str, asset_id: str, changes: dict[str, Any]
    ) -> None:
        """Control an asset (fan speed, lights, etc).

        changes: dict of key -> value.
        e.g. {"fanSpeed": 50, "isBacklightOn": True}
        """
        if not location_id or not asset_id:
            raise ValueError("location_id and asset_id are required")

        url = f"{FIRESTORE_BASE}/organizations/{self._org_id}/locations/{location_id}/assets/{asset_id}"

        fields: dict[str, dict[str, Any]] = {}
        params: list[tuple[str, str]] = []

        for key, value in changes.items():
            # A field path listed in updateMask without a matching value in the
            # payload makes Firestore DELETE that field, so every path appended
            # here must have a value mapped below.
            if isinstance(value, bool):
                fields[key] = {"booleanValue": value}
            elif isinstance(value, int):
                fields[key] = {"integerValue": str(value)}  # Firestore ints are strings in JSON
            elif isinstance(value, float):
                fields[key] = {"doubleValue": value}
            elif isinstance(value, str):
                fields[key] = {"stringValue": value}
            else:
                raise TypeError(
                    f"Unsupported value type for {key}: {type(value).__name__}"
                )
            params.append(("updateMask.fieldPaths", f"config.{key}"))

        payload = {
            "fields": {
                "config": {
                    "mapValue": {
                        "fields": fields,
                    }
                },
            }
        }

        await self._request("PATCH", url, params=params, json=payload)
