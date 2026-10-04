from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fake_ollama import FakeOllama  # noqa: E402


@pytest.fixture(scope="session")
def fake_ollama():
    with FakeOllama() as fake:
        yield fake


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAGENT_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def settings(fake_ollama, home):
    from localagent.config import Settings, save_settings

    s = Settings(ollama_url=fake_ollama.url)
    save_settings(s, home)
    return s


@pytest.fixture
async def runtime(settings, home):
    from localagent.runtime import Runtime

    rt = Runtime(settings, home)
    yield rt
    await rt.aclose()


@pytest.fixture
def client(settings, home):
    from fastapi.testclient import TestClient

    from localagent.server import create_app

    with TestClient(create_app(settings, home)) as c:
        yield c
