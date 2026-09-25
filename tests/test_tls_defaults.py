"""TLS verification must be on by default in every HTTP client in the repo.

The LangChain tools, CrewAI tools and the evangelist agent send API keys and
bearer tokens. They used to default ``TLS_VERIFY`` to "0", sending those
credentials over unverified TLS. Only an explicit ``TLS_VERIFY=0`` (for a
trusted self-signed test node) may turn verification off.
"""

from __future__ import annotations

import importlib
import sys
import types

import pytest

MODULES = ["rustchain_langchain.tools", "rustchain_crewai", "evangelist_agent"]


@pytest.fixture
def optional_deps(monkeypatch):
    """Stub requests/crewai when not installed; only module-level config is tested."""
    try:
        import requests  # noqa: F401
    except ImportError:
        monkeypatch.setitem(sys.modules, "requests", types.ModuleType("requests"))
    try:
        import crewai.tools  # noqa: F401
    except ImportError:
        from pydantic import BaseModel

        crewai = types.ModuleType("crewai")
        crewai_tools = types.ModuleType("crewai.tools")
        crewai_tools.BaseTool = type("BaseTool", (BaseModel,), {})
        crewai.tools = crewai_tools
        monkeypatch.setitem(sys.modules, "crewai", crewai)
        monkeypatch.setitem(sys.modules, "crewai.tools", crewai_tools)


def _fresh_import(name: str):
    for mod in [m for m in sys.modules if m == name or m.startswith(name + ".")]:
        sys.modules.pop(mod)
    return importlib.import_module(name)


@pytest.fixture(autouse=True)
def _restore_modules():
    saved = {m: sys.modules.get(m) for m in MODULES + ["rustchain_langchain"]}
    yield
    for name, mod in saved.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod


@pytest.mark.parametrize("module_name", MODULES)
def test_tls_verification_on_by_default(module_name, monkeypatch, optional_deps):
    monkeypatch.delenv("TLS_VERIFY", raising=False)
    monkeypatch.delenv("RUSTCHAIN_NODE", raising=False)

    module = _fresh_import(module_name)

    assert module._TLS_VERIFY is True
    # The default node must be one whose certificate verifies (not a bare IP).
    assert module.RUSTCHAIN_NODE == "https://rustchain.org"


@pytest.mark.parametrize("module_name", MODULES)
@pytest.mark.parametrize("value", ["0", "false", "No"])
def test_tls_verification_can_be_disabled_explicitly(module_name, value, monkeypatch, optional_deps):
    monkeypatch.setenv("TLS_VERIFY", value)

    assert _fresh_import(module_name)._TLS_VERIFY is False


def test_evangelist_http_client_verifies(monkeypatch, optional_deps):
    monkeypatch.delenv("TLS_VERIFY", raising=False)
    import httpx

    captured = {}
    real_client = httpx.Client

    def spy(*args, **kwargs):
        captured.update(kwargs)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", spy)
    _fresh_import("evangelist_agent")

    assert captured["verify"] is True
