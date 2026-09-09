"""Shared pytest fixtures.

The integration tests run against a *real* PostgreSQL database
(``A4S_TEST_DATABASE_URL``) because several behaviours we care about are
enforced in the database itself: the append-only audit trigger, JSONB
round-tripping and the CHECK constraints generated from the Python enums.
Substituting SQLite would silently skip exactly the guarantees we want to
prove, so the suite is honest about needing Postgres.

The database URL is rewritten *before* ``app.core.config`` is imported so that
the application, Alembic and the tests all agree on which database they use.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_dotenv() -> None:
    env_file = BACKEND_ROOT.parent / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

_TEST_URL = os.environ.get("A4S_TEST_DATABASE_URL")
if not _TEST_URL:
    _TEST_URL = "postgresql+asyncpg://postgres@127.0.0.1:5432/a4s_test"
# Point the whole process at the test database before settings are created.
os.environ["A4S_DATABASE_URL"] = _TEST_URL
os.environ["A4S_ENV"] = "test"
os.environ.setdefault("A4S_JWT_SECRET", "test-only-secret-0123456789abcdef0123456789")
os.environ.setdefault("A4S_SIM_AUTOSTART", "false")
# Use a dedicated Redis logical database so the suite never touches a
# developer's cached state. If Redis is not running, init_event_bus falls back
# to the in-memory bus automatically and the WebSocket tests still pass -- they
# assert on the abstract EventBus contract, not on a specific backend.
os.environ["A4S_REDIS_URL"] = os.environ.get("A4S_TEST_REDIS_URL", "redis://127.0.0.1:6379/15")
# The suite issues far more logins than a human would; the production limits
# are asserted separately in test_rate_limiting.py rather than throttling here.
os.environ["A4S_RATE_LIMIT_DEFAULT"] = "100000/minute"
os.environ["A4S_RATE_LIMIT_LOGIN"] = "100000/minute"
os.environ["A4S_LOG_LEVEL"] = "WARNING"
os.environ["A4S_DEBUG"] = "false"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import delete, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models.auth import RefreshToken, User  # noqa: E402
from app.models.personnel import (  # noqa: E402
    DigitalTwinState,
    HealthAlert,
    HealthPrediction,
    Personnel,
    RiskAssessment,
    VitalReading,
)
from app.models.system import SecurityEvent  # noqa: E402
from seeds.seed import resolve_seed_passwords  # noqa: E402
from seeds.seed import run as run_seed  # noqa: E402

assert settings.database_url == _TEST_URL, "test database wiring failed"


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    """Drop, re-create and migrate the test schema once per session."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        cwd=BACKEND_ROOT,
        env={**os.environ, "A4S_DATABASE_URL": _TEST_URL},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.exit(
            "alembic downgrade failed - is PostgreSQL running and "
            f"{_TEST_URL} reachable?\n{result.stdout}\n{result.stderr}",
            returncode=1,
        )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env={**os.environ, "A4S_DATABASE_URL": _TEST_URL},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.exit(f"alembic upgrade failed\n{result.stdout}\n{result.stderr}", returncode=1)
    yield


@pytest_asyncio.fixture(scope="session", autouse=True)
async def seeded(migrated_database: None) -> AsyncIterator[None]:
    """Seed reference data once; individual tests clean up what they add."""
    await run_seed(["permissions", "users", "config", "personnel", "terrain", "uav"], 0)
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def session(seeded: None) -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as db:
        yield db


@pytest_asyncio.fixture
async def client(seeded: None) -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://testserver/api/v1") as ac,
    ):
        yield ac


@pytest.fixture(scope="session")
def passwords() -> dict[str, str]:
    return resolve_seed_passwords()


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    response = await client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    tokens = response.json()["tokens"]
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest_asyncio.fixture
async def admin_headers(client: AsyncClient, passwords: dict[str, str]) -> dict[str, str]:
    return await _login(client, "admin@a4s.local", passwords["admin@a4s.local"])


@pytest_asyncio.fixture
async def commander_headers(client: AsyncClient, passwords: dict[str, str]) -> dict[str, str]:
    return await _login(client, "commander@a4s.local", passwords["commander@a4s.local"])


@pytest_asyncio.fixture
async def medic_headers(client: AsyncClient, passwords: dict[str, str]) -> dict[str, str]:
    return await _login(client, "medic@a4s.local", passwords["medic@a4s.local"])


@pytest_asyncio.fixture
async def operator_headers(client: AsyncClient, passwords: dict[str, str]) -> dict[str, str]:
    return await _login(client, "operator@a4s.local", passwords["operator@a4s.local"])


@pytest_asyncio.fixture
async def viewer_headers(client: AsyncClient, passwords: dict[str, str]) -> dict[str, str]:
    return await _login(client, "viewer@a4s.local", passwords["viewer@a4s.local"])


@pytest_asyncio.fixture
async def a_person_id(client: AsyncClient, commander_headers: dict[str, str]) -> str:
    response = await client.get("/personnel", params={"limit": 1}, headers=commander_headers)
    assert response.status_code == 200, response.text
    return response.json()["items"][0]["id"]


@pytest_asyncio.fixture
async def clean_transient(session: AsyncSession) -> AsyncIterator[None]:
    """Remove rows produced by a test so ordering never matters."""
    yield
    for model in (
        HealthAlert,
        HealthPrediction,
        RiskAssessment,
        VitalReading,
        DigitalTwinState,
        SecurityEvent,
        RefreshToken,
    ):
        await session.execute(delete(model))
    await session.commit()


@pytest.fixture
def unique_suffix() -> str:
    return uuid.uuid4().hex[:8]


__all__ = ["Base", "Personnel", "User", "text"]


@pytest_asyncio.fixture
async def running_simulation(
    client: AsyncClient, admin_headers: dict[str, str]
) -> AsyncIterator[dict[str, object]]:
    """Start the simulation engine so swarm/scenario endpoints are live.

    The engine holds in-process state (UAV swarm, environment, sim clock), so a
    number of endpoints legitimately refuse to work until a run exists. Tests
    that need that state use this fixture and always stop the run afterwards.
    """
    response = await client.post(
        "/simulation/start",
        json={
            "scenario": "MIXED",
            "seed": 424242,
            "speed": 1,
            "tick_seconds": 60.0,
            "sim_seconds_per_tick": 60.0,
            "reset_first": True,
        },
        headers=admin_headers,
    )
    assert response.status_code in (200, 201), response.text
    try:
        yield response.json()
    finally:
        await client.post("/simulation/stop", json={}, headers=admin_headers)
