"""Unit tests for security headers and documentation Content-Security-Policy."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.main import app


def test_api_docs_allows_swagger_ui_cdn_assets() -> None:
    client = TestClient(app)
    response = client.get("/api/docs")
    assert response.status_code == 200
    csp = response.headers.get("Content-Security-Policy", "")
    assert "https://cdn.jsdelivr.net" in csp
    assert "'unsafe-inline'" in csp
    assert "https://fastapi.tiangolo.com" in csp


def test_docs_redirects_to_api_docs() -> None:
    client = TestClient(app, follow_redirects=False)
    response = client.get("/docs")
    assert response.status_code == 307
    assert response.headers["location"] == "/api/docs"


def test_redoc_redirects_to_api_redoc() -> None:
    client = TestClient(app, follow_redirects=False)
    response = client.get("/redoc")
    assert response.status_code == 307
    assert response.headers["location"] == "/api/redoc"


def test_api_endpoints_maintain_restrictive_csp() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/meta")
    assert response.status_code == 200
    csp = response.headers.get("Content-Security-Policy", "")
    assert csp == "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
