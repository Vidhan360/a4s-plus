"""Regression tests for CORS configuration, preflight OPTIONS, and error responses."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

VERCEL_ORIGIN = "https://a4s-plus.vercel.app"


@pytest.mark.asyncio
async def test_login_preflight_options_allowed() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(
            "OPTIONS",
            "/api/v1/auth/login",
            headers={
                "Origin": VERCEL_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type,Authorization",
            },
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == VERCEL_ORIGIN
        assert "POST" in response.headers.get("access-control-allow-methods", "")
        # Credentials should not be enabled
        assert response.headers.get("access-control-allow-credentials") != "true"


@pytest.mark.asyncio
async def test_login_post_error_response_contains_cors_header() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Invalid payload triggering 422
        response = await client.post(
            "/api/v1/auth/login",
            json={"invalid": "payload"},
            headers={"Origin": VERCEL_ORIGIN},
        )
        assert response.status_code == 422
        assert response.headers.get("access-control-allow-origin") == VERCEL_ORIGIN


@pytest.mark.asyncio
async def test_unhandled_500_error_contains_cors_header() -> None:
    app = create_app()

    @app.get("/test-500-error")
    async def failing_endpoint() -> None:
        raise RuntimeError("Simulated crash")

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.get(
            "/test-500-error",
            headers={"Origin": VERCEL_ORIGIN},
        )
        assert response.status_code == 500
        assert response.headers.get("access-control-allow-origin") == VERCEL_ORIGIN


@pytest.mark.asyncio
async def test_disallowed_origin_rejected() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(
            "OPTIONS",
            "/api/v1/auth/login",
            headers={
                "Origin": "https://unauthorized-domain.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert "access-control-allow-origin" not in response.headers


def test_cors_origin_list_normalizes_trailing_slashes() -> None:
    s = Settings(cors_origins="https://custom-origin.org/ , http://localhost:3000/")
    assert "https://custom-origin.org" in s.cors_origin_list
    assert "http://localhost:3000" in s.cors_origin_list
    assert "https://a4s-plus.vercel.app" in s.cors_origin_list
    for origin in s.cors_origin_list:
        assert not origin.endswith("/")
