"""API Client for ScentAir."""
from __future__ import annotations

import asyncio
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

# Per attempt. Firebase and Firestore answer in well under a second, and a
# shorter timeout lets a retry on a fresh connection rescue a stalled one.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)

# Seconds to wait before each retry of a transient failure (network error,
# timeout, or one of RETRY_STATUSES). Two retries, so three attempts in all.
RETRY_DELAYS = (1, 3)
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

# Firebase auth endpoints signal rejected credentials with these statuses.
AUTH_ERROR_STATUSES = (400, 401, 403)

# Firebase error code for a temporary lockout after repeated failed sign-ins.
# It arrives as a 400 like bad credentials, but the credentials may be fine.
RATE_LIMIT_ERROR = "TOO_MANY_ATTEMPTS_TRY_LATER"


class ScentAirError(Exception):
    """Base error for the ScentAir API client."""


class ScentAirAuthError(ScentAirError):
    """Credentials or tokens were rejected."""


class ScentAirNoOrganizationError(ScentAirAuthError):
    """Sign-in worked, but the account has no ScentConnect organization."""


class ScentAirConnectionError(ScentAirError):
    """Error communicating with the ScentAir cloud."""


class ScentAirRateLimitError(ScentAirError):
    """Firebase is temporarily refusing sign-ins for this account."""


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


def _error_reason(status: int, body: Any) -> str:
    """Return the message a Google API put in an error body, or the status."""
    try:
        return str(body["error"]["message"])
    except (KeyError, TypeError):
        return f"HTTP {status}"


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
        # Serializes login and token refresh, so concurrent requests that all
        # hit an expired token cause one refresh (or one login) instead of one
        # each. Parallel logins with a stale password would count as several
        # failed sign-ins, which can trip Firebase's temporary lockout.
        self._auth_lock = asyncio.Lock()

    @property
    def user_id(self) -> str | None:
        """Return the Firebase user id (stable per account)."""
        return self._user_id

    async def _send(self, method: str, url: str, **kwargs: Any) -> tuple[int, Any]:
        """Send a request, retrying transient failures. Return (status, JSON body).

        Network errors, timeouts, and RETRY_STATUSES responses are retried
        after RETRY_DELAYS. Other statuses are definitive answers and are
        returned as-is for the caller to judge. Retrying is safe because every
        request this client makes is idempotent: reads, sign-ins, token
        refreshes, and PATCHes that set absolute values, so a retry after an
        ambiguous failure cannot apply a change twice.

        The body is None when the response is not JSON.
        """
        for delay in (*RETRY_DELAYS, None):
            try:
                async with self._session.request(
                    method, url, timeout=REQUEST_TIMEOUT, **kwargs
                ) as resp:
                    if resp.status not in RETRY_STATUSES or delay is None:
                        try:
                            body = await resp.json(content_type=None)
                        except ValueError:
                            body = None
                        return resp.status, body
                    failure = f"HTTP {resp.status}"
            except (aiohttp.ClientError, TimeoutError) as err:
                if delay is None:
                    raise ScentAirConnectionError(
                        f"Error communicating with ScentAir: {err!r}"
                    ) from err
                failure = repr(err)
            _LOGGER.debug(
                "%s %s failed (%s), retrying in %ss",
                method,
                url.split("?")[0],
                failure,
                delay,
            )
            await asyncio.sleep(delay)
        raise AssertionError("unreachable")  # the last pass always returns or raises

    async def _post_auth(
        self, url: str, payload: dict[str, Any], action: str
    ) -> dict[str, Any]:
        """POST to a Firebase auth endpoint and classify its failures."""
        status, body = await self._send("POST", url, json=payload)
        if status in AUTH_ERROR_STATUSES:
            reason = _error_reason(status, body)
            if reason.startswith(RATE_LIMIT_ERROR):
                raise ScentAirRateLimitError(
                    f"{action} temporarily blocked after too many attempts"
                )
            raise ScentAirAuthError(f"{action} rejected: {reason}")
        if status >= 400 or not isinstance(body, dict):
            raise ScentAirConnectionError(
                f"{action} failed: {_error_reason(status, body)}"
            )
        return body

    async def login(self) -> None:
        """Log in to Firebase with the stored credentials."""
        data = await self._post_auth(
            AUTH_URL,
            {
                "email": self._username,
                "password": self._password,
                "returnSecureToken": True,
            },
            "Login",
        )
        try:
            id_token = data["idToken"]
            refresh_token = data["refreshToken"]
            user_id = data["localId"]
        except (KeyError, TypeError) as err:
            raise ScentAirError(f"Unexpected login response, missing {err}") from err

        # Claims structure seen in HAR: claims: { portal: "CUSTOMER", role: "ENT_MANAGER", orgId: "..." }
        claims = _decode_jwt_payload(id_token).get("claims") or {}
        org_id = claims.get("orgId")
        if not org_id:
            raise ScentAirNoOrganizationError(
                "Account has no ScentConnect organization (no orgId claim)"
            )

        # Commit the session only once it is complete, so a failed login can
        # never leave a token behind without the org id that URLs need.
        self._id_token = id_token
        self._refresh_token = refresh_token
        self._user_id = user_id
        self._org_id = org_id

    async def _refresh_auth_token(self) -> None:
        """Exchange the refresh token for a new ID token."""
        data = await self._post_auth(
            REFRESH_URL,
            {"grant_type": "refresh_token", "refresh_token": self._refresh_token},
            "Token refresh",
        )
        try:
            id_token = data["id_token"]
            refresh_token = data["refresh_token"]
        except (KeyError, TypeError) as err:
            raise ScentAirError(
                f"Unexpected token refresh response, missing {err}"
            ) from err
        self._id_token = id_token
        self._refresh_token = refresh_token

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._id_token}"}

    async def _ensure_login(self) -> None:
        """Log in if there is no session yet.

        Must run BEFORE building any Firestore URL: login() is what
        populates self._org_id, which those URLs interpolate.
        """
        if self._id_token and self._org_id:
            return
        async with self._auth_lock:
            if not (self._id_token and self._org_id):
                await self.login()

    async def _reauthenticate(self, rejected_token: str | None) -> None:
        """Replace an ID token that Firestore rejected."""
        async with self._auth_lock:
            if self._id_token != rejected_token:
                # Another request already replaced it while this one waited.
                return
            _LOGGER.debug("ID token rejected, refreshing")
            try:
                await self._refresh_auth_token()
            except ScentAirAuthError as err:
                # The refresh token itself was revoked (e.g. after a password
                # change): fall back to a full login.
                _LOGGER.debug("%s, logging in again", err)
                self._id_token = None
                self._refresh_token = None
                await self.login()

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        """Make a Firestore request, re-establishing auth once on a 401."""
        await self._ensure_login()

        sent_token = self._id_token
        status, body = await self._send(
            method, url, headers=self._auth_headers(), **kwargs
        )
        if status == 401:
            await self._reauthenticate(sent_token)
            status, body = await self._send(
                method, url, headers=self._auth_headers(), **kwargs
            )
            if status == 401:
                raise ScentAirAuthError("Request unauthorized after re-authentication")
        if status >= 400:
            raise ScentAirConnectionError(
                f"ScentAir request failed: {_error_reason(status, body)}"
            )
        if not isinstance(body, dict):
            raise ScentAirError("Unexpected non-JSON response from ScentAir")
        return body

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
        await self._ensure_login()
        return await self._list_documents(
            f"{FIRESTORE_BASE}/organizations/{self._org_id}/locations"
        )

    async def get_assets(self, location_id: str) -> list[dict[str, Any]]:
        """Get assets for a specific location."""
        await self._ensure_login()
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

        await self._ensure_login()
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

        # The ScentConnect portal sends this same precondition. Without it a
        # Firestore PATCH is an upsert, so writing to an asset that was deleted
        # or moved since the last poll would create a stray document instead
        # of failing.
        params.append(("currentDocument.exists", "true"))

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
