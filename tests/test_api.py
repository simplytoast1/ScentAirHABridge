"""Regression tests for the ScentAir API client.

api.py depends only on aiohttp, so it is loaded straight from its file and
these tests run without Home Assistant installed. The backend is simulated by
FakeCloud, which plays Firebase auth and Firestore well enough to catch the
auth and URL-building mistakes that matter.
"""
from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
from pathlib import Path

import aiohttp
import pytest

API_PATH = (
    Path(__file__).resolve().parents[1] / "custom_components" / "scentair" / "api.py"
)
_spec = importlib.util.spec_from_file_location("scentair_api", API_PATH)
api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api)

ORG_ID = "org-123"
ORG_BASE = f"{api.FIRESTORE_BASE}/organizations/{ORG_ID}"
LOCATIONS_URL = f"{ORG_BASE}/locations"


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    """Keep the retry policy but skip the real backoff sleeps."""
    monkeypatch.setattr(api, "RETRY_DELAYS", (0,) * len(api.RETRY_DELAYS))


def firebase_error(message: str, code: int = 400) -> dict:
    return {"error": {"code": code, "message": message}}


def make_id_token(claims: dict, serial: int) -> str:
    """Build an unsigned JWT shaped like a Firebase ID token."""

    def b64(obj: dict) -> str:
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{b64({'alg': 'none'})}.{b64({'claims': claims, 'serial': serial})}.sig"


class FakeResponse:
    """Stands in for aiohttp.ClientResponse. A body that is an exception is raised by json()."""

    def __init__(self, status: int, body=None) -> None:
        self.status = status
        self._body = body

    async def json(self, content_type: str | None = "application/json"):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _PendingRequest:
    """Async context manager returned by FakeSession, like aiohttp's."""

    def __init__(self, handler, call: dict) -> None:
        self._handler = handler
        self._call = call

    async def __aenter__(self):
        await asyncio.sleep(0)  # yield like real I/O so concurrent requests interleave
        result = self._handler(self._call)
        if isinstance(result, BaseException):
            raise result
        return result

    async def __aexit__(self, *exc_info) -> bool:
        return False


class FakeSession:
    def __init__(self, handler) -> None:
        self._handler = handler
        self.calls: list[dict] = []

    def request(self, method: str, url: str, **kwargs):
        params = kwargs.get("params")
        if isinstance(params, dict):
            kwargs["params"] = dict(params)  # snapshot: the client mutates it between pages
        call = {"method": method, "url": url, **kwargs}
        self.calls.append(call)
        return _PendingRequest(self._handler, call)


class FakeCloud:
    """Simulates the Firebase auth and Firestore endpoints the client talks to."""

    def __init__(self) -> None:
        self.session = FakeSession(self._handle)
        self.claims: dict = {"orgId": ORG_ID}
        # Like Firebase, an issued ID token stays valid until it expires, even
        # after a newer one has been issued.
        self.valid_tokens: set[str] = set()
        self.serial = 0
        self.login_calls = 0
        self.refresh_calls = 0
        self.login_response = None  # override what the sign-in endpoint returns
        self.refresh_revoked = False
        self.pages: dict[str, list[dict]] = {}
        # One-shot failures (a FakeResponse or an exception to raise), served
        # in order to the next sign-in or Firestore requests.
        self.auth_failures: list = []
        self.firestore_failures: list = []

    def client(self):
        return api.ScentAirAPI(self.session, username="user@example.com", password="pw")

    def expire_token(self) -> None:
        """Make every ID token issued so far invalid, like the hourly expiry."""
        self.valid_tokens.clear()

    def firestore_calls(self, method: str | None = None) -> list[dict]:
        return [
            c
            for c in self.session.calls
            if c["url"].startswith(api.FIRESTORE_BASE)
            and (method is None or c["method"] == method)
        ]

    def _issue_token(self) -> str:
        self.serial += 1
        token = make_id_token(self.claims, self.serial)
        self.valid_tokens.add(token)
        return token

    def _handle(self, call: dict):
        url = call["url"]
        if url == api.AUTH_URL:
            self.login_calls += 1
            if self.auth_failures:
                return self.auth_failures.pop(0)
            if self.login_response is not None:
                return self.login_response
            return FakeResponse(
                200,
                {"idToken": self._issue_token(), "refreshToken": "rt", "localId": "uid-1"},
            )
        if url == api.REFRESH_URL:
            self.refresh_calls += 1
            if self.refresh_revoked:
                return FakeResponse(400, firebase_error("INVALID_REFRESH_TOKEN"))
            return FakeResponse(200, {"id_token": self._issue_token(), "refresh_token": "rt"})

        if self.firestore_failures:
            return self.firestore_failures.pop(0)
        token = call["headers"]["Authorization"][len("Bearer ") :]
        if token not in self.valid_tokens:
            return FakeResponse(401, firebase_error("UNAUTHENTICATED", 401))
        if not url.startswith(f"{ORG_BASE}/"):
            # What Firestore answers when the org id in the path is wrong, e.g. "None".
            return FakeResponse(403, firebase_error("Missing or insufficient permissions.", 403))
        if call["method"] == "PATCH":
            return FakeResponse(200, {"name": url})
        pages = self.pages.get(url, [{}])
        return FakeResponse(200, pages[int(call["params"].get("pageToken", 0))])


@pytest.mark.parametrize(
    ("first_call", "expected_url"),
    [
        (lambda c: c.get_locations(), LOCATIONS_URL),
        (lambda c: c.get_assets("loc-1"), f"{LOCATIONS_URL}/loc-1/assets"),
        (
            lambda c: c.control_asset("loc-1", "asset-1", {"fanSpeed": 3}),
            f"{LOCATIONS_URL}/loc-1/assets/asset-1",
        ),
    ],
    ids=["get_locations", "get_assets", "control_asset"],
)
def test_cold_start_logs_in_before_building_urls(first_call, expected_url):
    """Regression for 0.3.1: URLs were built with org id None before the first login."""

    async def scenario():
        cloud = FakeCloud()
        await first_call(cloud.client())
        assert cloud.login_calls == 1
        assert [c["url"] for c in cloud.firestore_calls()] == [expected_url]

    asyncio.run(scenario())


def test_control_asset_sends_precondition_and_typed_fields():
    async def scenario():
        cloud = FakeCloud()
        await cloud.client().control_asset(
            "loc-1", "asset-1", {"fanSpeed": 5, "isBacklightOn": True}
        )
        (patch,) = cloud.firestore_calls("PATCH")
        assert ("currentDocument.exists", "true") in patch["params"]
        masks = sorted(v for k, v in patch["params"] if k == "updateMask.fieldPaths")
        assert masks == ["config.fanSpeed", "config.isBacklightOn"]
        assert patch["json"] == {
            "fields": {
                "config": {
                    "mapValue": {
                        "fields": {
                            "fanSpeed": {"integerValue": "5"},
                            "isBacklightOn": {"booleanValue": True},
                        }
                    }
                }
            }
        }

    asyncio.run(scenario())


def test_control_asset_rejects_unsupported_values_before_sending():
    """A masked field with no value would make Firestore delete it."""

    async def scenario():
        cloud = FakeCloud()
        with pytest.raises(TypeError):
            await cloud.client().control_asset("loc-1", "asset-1", {"fanSpeed": None})
        assert cloud.firestore_calls("PATCH") == []

    asyncio.run(scenario())


def test_expired_token_is_refreshed_once_for_concurrent_requests():
    async def scenario():
        cloud = FakeCloud()
        client = cloud.client()
        await client.get_locations()
        cloud.expire_token()
        await asyncio.gather(*(client.get_assets(f"loc-{i}") for i in range(5)))
        assert cloud.refresh_calls == 1
        assert cloud.login_calls == 1

    asyncio.run(scenario())


def test_revoked_refresh_token_falls_back_to_a_single_login():
    async def scenario():
        cloud = FakeCloud()
        client = cloud.client()
        await client.get_locations()
        cloud.expire_token()
        cloud.refresh_revoked = True
        await asyncio.gather(*(client.get_assets(f"loc-{i}") for i in range(5)))
        assert cloud.refresh_calls == 1
        assert cloud.login_calls == 2  # the initial login plus one fallback

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (FakeResponse(400, firebase_error("INVALID_LOGIN_CREDENTIALS")), api.ScentAirAuthError),
        (
            FakeResponse(
                400,
                firebase_error(
                    "TOO_MANY_ATTEMPTS_TRY_LATER : Access to this account has been "
                    "temporarily disabled due to many failed login attempts."
                ),
            ),
            api.ScentAirRateLimitError,
        ),
        (FakeResponse(400, ValueError("body is not JSON")), api.ScentAirAuthError),
        (FakeResponse(503, {}), api.ScentAirConnectionError),
        (FakeResponse(200, {"unexpected": True}), api.ScentAirError),
        (aiohttp.ClientConnectionError("connection reset"), api.ScentAirConnectionError),
        (TimeoutError(), api.ScentAirConnectionError),
    ],
    ids=[
        "bad-credentials",
        "rate-limited",
        "unreadable-400",
        "server-error",
        "malformed-200",
        "network-error",
        "timeout",
    ],
)
def test_login_failures_are_classified(response, expected):
    """Exact classes matter: only true credential errors may trigger reauth."""

    async def scenario():
        cloud = FakeCloud()
        cloud.login_response = response
        with pytest.raises(api.ScentAirError) as exc_info:
            await cloud.client().login()
        return exc_info.value

    assert type(asyncio.run(scenario())) is expected


def test_account_without_org_is_reported_and_not_half_logged_in():
    async def scenario():
        cloud = FakeCloud()
        cloud.claims = {"role": "CUSTOMER"}  # valid sign-in, no orgId claim
        client = cloud.client()
        for _ in range(2):
            with pytest.raises(api.ScentAirNoOrganizationError):
                await client.get_locations()
        # Each call retried the login instead of reusing a token with no org,
        # and no Firestore URL was ever built with a missing org id.
        assert cloud.login_calls == 2
        assert cloud.firestore_calls() == []

    asyncio.run(scenario())
    # The coordinator relies on this to start a reauth flow.
    assert issubclass(api.ScentAirNoOrganizationError, api.ScentAirAuthError)


def test_list_documents_follows_pagination():
    async def scenario():
        cloud = FakeCloud()
        cloud.pages[LOCATIONS_URL] = [
            {"documents": [{"name": "a"}], "nextPageToken": "1"},
            {"documents": [{"name": "b"}], "nextPageToken": "2"},
            {"documents": [{"name": "c"}]},
        ]
        locations = await cloud.client().get_locations()
        assert [doc["name"] for doc in locations] == ["a", "b", "c"]

    asyncio.run(scenario())


TRANSIENT_FAILURES = [
    pytest.param(lambda: FakeResponse(503, firebase_error("unavailable", 503)), id="http-503"),
    pytest.param(lambda: FakeResponse(429, firebase_error("RESOURCE_EXHAUSTED", 429)), id="http-429"),
    pytest.param(lambda: aiohttp.ClientConnectionError("connection reset"), id="network-error"),
    pytest.param(TimeoutError, id="timeout"),
]


@pytest.mark.parametrize("make_failure", TRANSIENT_FAILURES)
def test_transient_poll_failures_are_retried(make_failure):
    """One blip must not fail the whole poll and mark every entity unavailable."""

    async def scenario():
        cloud = FakeCloud()
        client = cloud.client()
        await client.login()
        cloud.firestore_failures = [make_failure(), make_failure()]
        cloud.pages[LOCATIONS_URL] = [{"documents": [{"name": "loc"}]}]
        assert await client.get_locations() == [{"name": "loc"}]
        assert len(cloud.firestore_calls()) == 1 + len(api.RETRY_DELAYS)

    asyncio.run(scenario())


@pytest.mark.parametrize("make_failure", TRANSIENT_FAILURES)
def test_command_is_resent_unchanged_after_transient_failure(make_failure):
    async def scenario():
        cloud = FakeCloud()
        client = cloud.client()
        await client.login()
        cloud.firestore_failures = [make_failure()]
        await client.control_asset("loc-1", "asset-1", {"fanSpeed": 4})
        first, second = cloud.firestore_calls("PATCH")
        assert (first["url"], first["params"], first["json"]) == (
            second["url"],
            second["params"],
            second["json"],
        )

    asyncio.run(scenario())


def test_retries_are_bounded():
    async def scenario():
        cloud = FakeCloud()
        client = cloud.client()
        await client.login()
        cloud.firestore_failures = [FakeResponse(503, {}) for _ in range(10)]
        with pytest.raises(api.ScentAirConnectionError):
            await client.get_locations()
        assert len(cloud.firestore_calls()) == 1 + len(api.RETRY_DELAYS)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (404, "No document to update: projects/scentconnect/.../assets/asset-1"),
        (403, "Missing or insufficient permissions."),
        (400, "Invalid JSON payload received."),
    ],
    ids=["missing-document", "permission-denied", "bad-request"],
)
def test_definitive_errors_fail_fast_with_the_server_reason(status, message):
    async def scenario():
        cloud = FakeCloud()
        client = cloud.client()
        await client.login()
        cloud.firestore_failures = [FakeResponse(status, firebase_error(message, status))]
        with pytest.raises(api.ScentAirConnectionError, match="ScentAir request failed") as exc_info:
            await client.control_asset("loc-1", "asset-1", {"fanSpeed": 4})
        assert message in str(exc_info.value)
        assert len(cloud.firestore_calls("PATCH")) == 1

    asyncio.run(scenario())


def test_login_retries_transient_failures_but_not_rejections():
    async def scenario():
        cloud = FakeCloud()
        cloud.auth_failures = [aiohttp.ClientConnectionError("reset"), FakeResponse(503, {})]
        await cloud.client().login()
        assert cloud.login_calls == 3

        cloud = FakeCloud()
        cloud.login_response = FakeResponse(400, firebase_error("INVALID_LOGIN_CREDENTIALS"))
        with pytest.raises(api.ScentAirAuthError):
            await cloud.client().login()
        assert cloud.login_calls == 1  # a wrong password is never retried

    asyncio.run(scenario())
