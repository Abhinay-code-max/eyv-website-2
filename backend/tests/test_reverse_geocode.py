"""Unit tests for the reverse_geocode service function and
GET /api/locations/reverse-geocode endpoint.

Nominatim is mocked via unittest.mock.patch so no real HTTP requests are made.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

import os
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("REVENUECAT_WEBHOOK_AUTH_KEY", "test-rcat-key")

import server
from services import locations_service


# ───────────────────────── helpers ──────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _mock_nominatim_reverse_200(lat=12.9716, lon=77.5946, city="Bangalore",
                                country="India", country_code="in"):
    """Build a mock httpx.Response that looks like Nominatim's /reverse 200."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "lat": str(lat),
        "lon": str(lon),
        "display_name": f"{city}, India",
        "address": {
            "city": city,
            "country": country,
            "country_code": country_code,
        },
    }
    return mock_resp


# ═══════════════ 1. Service-layer unit tests ════════════════════════════════

class TestReverseGeocodeService:
    def setup_method(self):
        # Wipe the cache before each test
        locations_service._nominatim_reverse_cache.clear()

    def test_successful_reverse_geocode_returns_city_and_country(self):
        """Happy path: Nominatim 200 → structured dict with name/city/country/lat/lng."""
        mock_resp = _mock_nominatim_reverse_200()
        with patch("services.locations_service.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)
            result = _run(locations_service.reverse_geocode(12.9716, 77.5946))

        assert result is not None
        assert result["city"] == "Bangalore"
        assert result["country"] == "India"
        assert result["country_code"] == "IN"
        assert abs(result["lat"] - 12.9716) < 0.001
        assert abs(result["lng"] - 77.5946) < 0.001
        assert result["name"] == "Bangalore"   # city preferred over display_name split

    def test_result_is_cached_and_nominatim_called_only_once(self):
        """Second call with same coords must hit cache, not Nominatim again."""
        mock_resp = _mock_nominatim_reverse_200()
        with patch("services.locations_service.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)
            _run(locations_service.reverse_geocode(12.9716, 77.5946))
            _run(locations_service.reverse_geocode(12.9716, 77.5946))
            assert mock_http.get.call_count == 1  # second call served from cache

    def test_nominatim_404_returns_none(self):
        """Nominatim returning 404 (no feature at coords) → None, no crash."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch("services.locations_service.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)
            result = _run(locations_service.reverse_geocode(0.0, 0.0))
        assert result is None

    def test_network_exception_returns_none(self):
        """Any network error → None, no unhandled exception."""
        with patch("services.locations_service.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=Exception("connection error"))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)
            result = _run(locations_service.reverse_geocode(99.0, 99.0))
        assert result is None

    def test_town_used_when_no_city_in_address(self):
        """Falls back to town/village/county when city is absent."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "lat": "51.5",
            "lon": "-0.1",
            "display_name": "Little Missenden, England",
            "address": {
                "town": "Little Missenden",
                "country": "United Kingdom",
                "country_code": "gb",
            },
        }
        with patch("services.locations_service.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)
            result = _run(locations_service.reverse_geocode(51.5, -0.1))
        assert result is not None
        assert result["name"] == "Little Missenden"
        assert result["city"] == "Little Missenden"


# ═══════════════ 2. Endpoint-level integration tests ════════════════════════

@pytest.fixture(scope="module")
def client():
    return TestClient(server.app)


class TestReverseGeocodeEndpoint:
    """Tests hit GET /api/locations/reverse-geocode via TestClient (no real HTTP)."""

    def setup_method(self):
        locations_service._nominatim_reverse_cache.clear()

    def _auth_headers(self):
        """Minimal cookie-based auth that get_current_user accepts in test mode."""
        # TestClient keeps cookies across requests - log in first if needed.
        # We use the test server's /api/auth/login endpoint mock if available,
        # otherwise patch get_current_user directly (simpler and sufficient here).
        return {}

    def _patched_auth(self):
        """Patch get_current_user to return a dummy user for endpoint tests."""
        from unittest.mock import patch as _patch
        from types import SimpleNamespace
        dummy = SimpleNamespace(user_id="test-user")
        return _patch("routes.search.get_current_user", AsyncMock(return_value=dummy))

    def test_endpoint_returns_200_with_mocked_nominatim(self):
        mock_resp = _mock_nominatim_reverse_200()
        with self._patched_auth(), \
             patch("services.locations_service.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)
            client = TestClient(server.app)
            r = client.get("/api/locations/reverse-geocode", params={"lat": 12.9716, "lng": 77.5946})
        assert r.status_code == 200
        data = r.json()
        assert data["city"] == "Bangalore"
        assert data["country"] == "India"
        assert "lat" in data and "lng" in data

    def test_endpoint_returns_404_when_nominatim_returns_none(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with self._patched_auth(), \
             patch("services.locations_service.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=None)
            client = TestClient(server.app)
            r = client.get("/api/locations/reverse-geocode", params={"lat": 0.0, "lng": 0.0})
        assert r.status_code == 404

    def test_endpoint_requires_lat_and_lng(self):
        with self._patched_auth():
            client = TestClient(server.app)
            r = client.get("/api/locations/reverse-geocode", params={"lat": 12.97})
        # Missing lng → FastAPI 422 Unprocessable Entity
        assert r.status_code == 422

    def test_endpoint_unauthenticated_returns_401(self):
        """Without a valid session, get_current_user raises 401."""
        client = TestClient(server.app, raise_server_exceptions=False)
        r = client.get("/api/locations/reverse-geocode", params={"lat": 12.97, "lng": 77.59})
        assert r.status_code == 401
