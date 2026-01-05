"""WHOOP API client."""

import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from whoop_coach.config import get_settings


@dataclass
class TokenResponse:
    """OAuth token response."""

    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "Bearer"

    def to_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_in": self.expires_in,
            "token_type": self.token_type,
            "obtained_at": datetime.utcnow().isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TokenResponse":
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_in=data.get("expires_in", 3600),
            token_type=data.get("token_type", "Bearer"),
        )


class WhoopClient:
    """WHOOP API client with OAuth support."""

    AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
    TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
    API_BASE = "https://api.prod.whoop.com/developer"

    # v2 endpoints
    SCOPES = "read:recovery read:cycles read:workout read:sleep read:body_measurement offline"

    def __init__(self, access_token: str | None = None):
        self.access_token = access_token
        self._settings = get_settings()
        self._client = httpx.AsyncClient(timeout=30.0)

    @classmethod
    def generate_state(cls) -> str:
        """Generate secure random state for OAuth (64 hex chars)."""
        return secrets.token_hex(32)

    def build_authorize_url(self, state: str) -> str:
        """Build WHOOP OAuth authorization URL."""
        params = {
            "client_id": self._settings.WHOOP_CLIENT_ID,
            "redirect_uri": self._settings.WHOOP_REDIRECT_URI,
            "response_type": "code",
            "scope": self.SCOPES,
            "state": state,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> TokenResponse:
        """Exchange authorization code for tokens."""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self._settings.WHOOP_CLIENT_ID,
            "client_secret": self._settings.WHOOP_CLIENT_SECRET,
            "redirect_uri": self._settings.WHOOP_REDIRECT_URI,
        }
        response = await self._client.post(self.TOKEN_URL, data=data)
        response.raise_for_status()
        json_data = response.json()
        return TokenResponse(
            access_token=json_data["access_token"],
            refresh_token=json_data["refresh_token"],
            expires_in=json_data.get("expires_in", 3600),
        )

    async def refresh_tokens(self, refresh_token: str) -> TokenResponse:
        """Refresh access token using refresh token."""
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self._settings.WHOOP_CLIENT_ID,
            "client_secret": self._settings.WHOOP_CLIENT_SECRET,
        }
        response = await self._client.post(self.TOKEN_URL, data=data)
        response.raise_for_status()
        json_data = response.json()
        return TokenResponse(
            access_token=json_data["access_token"],
            refresh_token=json_data.get("refresh_token", refresh_token),
            expires_in=json_data.get("expires_in", 3600),
        )

    async def _request(
        self, method: str, endpoint: str, **kwargs
    ) -> dict[str, Any]:
        """Make authenticated API request with retry logic."""
        if not self.access_token:
            raise ValueError("No access token available")

        headers = {"Authorization": f"Bearer {self.access_token}"}
        url = f"{self.API_BASE}{endpoint}"

        # Retry logic for 429/5xx
        max_retries = 2
        for attempt in range(max_retries + 1):
            response = await self._client.request(
                method, url, headers=headers, **kwargs
            )

            if response.status_code == 429:
                if attempt < max_retries:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
                    continue
            elif response.status_code >= 500:
                if attempt < max_retries:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
                    continue

            # Debug: log 400 errors
            if response.status_code == 400:
                import logging
                logging.error(f"WHOOP 400 error: {response.text}")

            response.raise_for_status()
            return response.json()

        response.raise_for_status()
        return {}

    # === v2 API Methods ===

    async def get_profile(self) -> dict[str, Any]:
        """Get user profile. GET /v2/user/profile/basic"""
        return await self._request("GET", "/v2/user/profile/basic")

    async def get_body_measurement(self) -> dict[str, Any]:
        """Get body measurements (includes max_heart_rate). GET /v2/user/measurement/body"""
        return await self._request("GET", "/v2/user/measurement/body")

    async def get_cycles(self, limit: int = 1) -> list[dict[str, Any]]:
        """Get cycles. GET /v2/cycle"""
        data = await self._request("GET", f"/v2/cycle?limit={limit}")
        return data.get("records", [])

    async def get_recovery(self, cycle_id: int) -> dict[str, Any] | None:
        """Get recovery for a cycle. GET /v2/cycle/{cycleId}/recovery"""
        try:
            return await self._request("GET", f"/v2/cycle/{cycle_id}/recovery")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None  # Recovery not yet available
            raise

    async def get_workouts(self, limit: int = 5) -> list[dict[str, Any]]:
        """Get recent workouts. GET /v2/activity/workout"""
        data = await self._request("GET", f"/v2/activity/workout?limit={limit}")
        return data.get("records", [])

    async def get_sleep(self, sleep_id: str) -> dict[str, Any]:
        """Get sleep by ID. GET /v2/activity/sleep/{sleepId}
        
        Returns sleep data including cycle_id and timezone_offset.
        """
        return await self._request("GET", f"/v2/activity/sleep/{sleep_id}")

    async def close(self):
        """Close HTTP client."""
        await self._client.aclose()
